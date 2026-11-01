"""The HTTP client against a heater asking for digest authentication (RFC 7616, MD5, qop=auth)."""

import hashlib
import re
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.windhager.client import WindhagerHttpClient, heater_id
from custom_components.windhager.const import DEFAULT_USERNAME
from custom_components.windhager.exceptions import CannotConnect, InvalidAuth, WriteFailed

PASSWORD = "secret"
REALM = "Windhager"
NONCE = "dcd98b7102dd2f0e8b11d0f600bfb0c093"


def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


@dataclass
class Heater:
    """A heater's API on localhost: what it received, how many challenges it sent."""

    host: str
    challenges: int = 0
    # What the heater answers a write with
    write_status: int = 200
    datapoints: list[bytes] = field(default_factory=list)
    # The error texts' files it serves, by language
    error_texts: dict[str, str] = field(default_factory=dict)
    # What it answers a lookup with, by path after /lookup: (status, JSON body)
    lookups: dict[str, tuple[int, object]] = field(default_factory=dict)
    # The paths of the lookups it answered
    looked_up: list[str] = field(default_factory=list)


def authorized(request: web.Request) -> bool:
    """Whether the request answers the challenge with the heater's password."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Digest "):
        return False
    fields = dict(re.findall(r'(\w+)="?([^",]*)"?', header))
    ha1 = md5(f"{DEFAULT_USERNAME}:{REALM}:{PASSWORD}")
    ha2 = md5(f"{request.method}:{fields['uri']}")
    expected = md5(f"{ha1}:{NONCE}:{fields['nc']}:{fields['cnonce']}:{fields['qop']}:{ha2}")
    return fields["username"] == DEFAULT_USERNAME and fields["response"] == expected


@pytest.fixture
async def heater(socket_enabled: None) -> AsyncIterator[Heater]:
    """The heater, on 127.0.0.1 (the only address the test sockets reach)."""
    state = Heater(host="")

    async def handle(request: web.Request) -> web.StreamResponse:
        if not authorized(request):
            state.challenges += 1
            challenge = f'Digest realm="{REALM}", nonce="{NONCE}", qop="auth", algorithm=MD5'
            return web.Response(status=401, headers={"WWW-Authenticate": challenge})
        if request.method == "PUT":
            if state.write_status != 200:
                return web.Response(status=state.write_status)
            state.datapoints.append(await request.read())
            return web.json_response({})
        path = request.path.removeprefix("/api/1.0/lookup")
        state.looked_up.append(path)
        if path in state.lookups:
            status, body = state.lookups[path]
            return web.json_response(body, status=status)
        return web.json_response([{"nodeId": 15, "name": "BioWIN"}])

    async def error_texts(request: web.Request) -> web.StreamResponse:
        text = state.error_texts.get(request.match_info["language"])
        return web.Response(status=404) if text is None else web.Response(text=text, content_type="text/xml")

    app = web.Application()
    app.router.add_route("*", "/api/1.0/{path:.*}", handle)
    app.router.add_get("/res/xml/ErrorTexte_{language}.xml", error_texts)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    state.host = f"127.0.0.1:{server.port}"
    yield state
    await server.close()


async def test_a_lookup_answers_the_challenge_once_for_the_following_requests(heater: Heater) -> None:
    client = WindhagerHttpClient(heater.host, PASSWORD)

    first = await client.fetch("/1")
    second = await client.fetch("/1/15")
    await client.close()

    assert first == second == [{"nodeId": 15, "name": "BioWIN"}]
    assert heater.challenges == 1


async def test_a_datapoint_update_is_authenticated(heater: Heater) -> None:
    client = WindhagerHttpClient(heater.host, PASSWORD)

    await client.update("/1/15/0/3/4/0", "21.5")
    await client.close()

    assert heater.datapoints == [b'{"OID":"/1/15/0/3/4/0","value":"21.5"}']


async def test_a_write_the_heater_refuses_raises_its_status(heater: Heater) -> None:
    heater.write_status = 500
    client = WindhagerHttpClient(heater.host, PASSWORD)

    with pytest.raises(WriteFailed) as refused:
        await client.update("/1/15/0/3/4/0", "21.5")
    await client.close()

    assert refused.value.status == 500


async def test_a_write_with_a_wrong_password_fails_the_authentication(heater: Heater) -> None:
    client = WindhagerHttpClient(heater.host, "wrong")

    with pytest.raises(InvalidAuth):
        await client.update("/1/15/0/3/4/0", "21.5")
    await client.close()

    assert heater.datapoints == []


async def test_a_write_to_a_heater_that_does_not_answer_cannot_connect(socket_enabled: None) -> None:
    # A port nobody listens on: bound then released
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    client = WindhagerHttpClient(f"127.0.0.1:{port}", PASSWORD)

    with pytest.raises(CannotConnect):
        await client.update("/1/15/0/3/4/0", "21.5")
    await client.close()


async def test_a_wrong_password_fails_the_lookup(heater: Heater) -> None:
    client = WindhagerHttpClient(heater.host, "wrong")

    with pytest.raises(InvalidAuth):
        await client.fetch("/1")
    await client.close()

    assert heater.challenges == 2


# The modules of an installation as /1 lists them (fake Neuron IDs): a heating circuit
# module first, then the heater, then a module with no function of interest
CIRCUIT_MODULE = {"nodeId": 15, "neuronId": "0a0000000015", "functions": [{"fctId": 0, "fctType": 14}]}
HEATER_MODULE = {"nodeId": 60, "neuronId": "0a0000000060", "functions": [{"fctId": 0, "fctType": 9}]}
OTHER_MODULE = {"nodeId": 90, "neuronId": "0a0000000090", "functions": [{"fctId": 32, "fctType": -1}]}


@pytest.mark.parametrize(
    ("modules", "expected"),
    [
        ([CIRCUIT_MODULE, HEATER_MODULE, OTHER_MODULE], "0a0000000060"),
        ([OTHER_MODULE, CIRCUIT_MODULE], "0a0000000090"),
        ([], None),
    ],
)
def test_the_heater_is_identified_by_its_module_neuron_id(modules: list[dict], expected: str | None) -> None:
    assert heater_id(modules) == expected


async def test_the_entities_and_devices_are_named_after_the_heater_not_the_host() -> None:
    client = WindhagerHttpClient("192.0.2.1", PASSWORD)
    heater = {**HEATER_MODULE, "functions": [{"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN"}]}
    circuit = {**CIRCUIT_MODULE, "functions": [{"fctId": 0, "fctType": 14, "lock": False, "name": "Circuit"}]}
    client.fetch = AsyncMock(side_effect=lambda url: [circuit, heater] if url == "/1" else {"value": "1"})

    data = await client.fetch_all()

    ids = {device["id"] for device in data["devices"]} | {device["device_id"] for device in data["devices"]}
    assert ids and all(identifier.startswith("0a0000000060") for identifier in ids)


async def polled_client(failure: Exception) -> WindhagerHttpClient:
    """A client that found its datapoints, the heater then failing every request with `failure`."""
    client = WindhagerHttpClient("192.0.2.1", PASSWORD)
    heater = {**HEATER_MODULE, "functions": [{"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN"}]}
    client.fetch = AsyncMock(side_effect=lambda url: [heater] if url == "/1" else {"value": "1"})
    await client.fetch_all()
    client.fetch = AsyncMock(side_effect=failure)
    return client


@pytest.mark.parametrize("failure", [InvalidAuth("refused"), CannotConnect("no answer")])
async def test_a_poll_the_heater_fails_as_a_whole_raises(failure: Exception) -> None:
    client = await polled_client(failure)

    with pytest.raises(type(failure)):
        await client.fetch_all()


async def test_a_datapoint_answered_without_a_value_reads_unknown() -> None:
    client = await polled_client(ValueError("not JSON"))

    data = await client.fetch_all()

    # The datapoints read on every poll; the slow ones keep their last value until read again
    assert client.oids and all(data["oids"][oid] is None for oid in client.oids)


async def test_a_heater_that_does_not_answer_a_lookup_cannot_connect(socket_enabled: None) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    client = WindhagerHttpClient(f"127.0.0.1:{port}", PASSWORD)

    with pytest.raises(CannotConnect):
        await client.fetch("/1")
    await client.close()


async def test_a_module_without_functions_gives_no_entity() -> None:
    client = WindhagerHttpClient("192.0.2.1", PASSWORD)
    heater = {**HEATER_MODULE, "functions": [{"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN"}]}
    bare = {**CIRCUIT_MODULE}
    bare.pop("functions", None)
    client.fetch = AsyncMock(side_effect=lambda url: [bare, heater] if url == "/1" else {"value": "1"})

    data = await client.fetch_all()

    assert data["devices"] and all(device["device_id"].endswith("60") for device in data["devices"])


async def test_a_datapoint_the_heater_gives_as_dashes_reads_unknown() -> None:
    client = await polled_client(ValueError("unused"))
    client.fetch = AsyncMock(return_value={"value": "-.-"})

    data = await client.fetch_all()

    # The datapoints read on every poll; the slow ones keep their last value until read again
    assert client.oids and all(data["oids"][oid] is None for oid in client.oids)


def error_texts(lang: str, text: str) -> str:
    """An error texts' file as the InfoWIN Touch serves it (its format on 2026-10-30)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<ErrorTexte lang="{lang}">\n\t<error code="42" text="{text}"/>\n</ErrorTexte>\n'
    )


async def test_the_error_texts_are_the_heaters_own_in_the_instance_language(heater: Heater) -> None:
    heater.error_texts = {
        "fr": error_texts("fr", "Relai de la turbine défectueux  Débrancher la prise."),
        "de": error_texts("de", "Relais Saugturbine defekt"),
    }
    client = WindhagerHttpClient(heater.host, PASSWORD)

    texts = await client.fetch_error_texts("fr")
    await client.close()

    # The heater's double spaces, between the fault and what to do, are one
    assert texts == {"42": "Relai de la turbine défectueux Débrancher la prise."}


@pytest.mark.parametrize(
    ("served", "expected"),
    [
        # A language the heater does not have: English, then German
        (
            {"en": error_texts("en", "Suction turbine relay defective"), "de": error_texts("de", "Relais")},
            {"42": "Suction turbine relay defective"},
        ),
        ({"de": error_texts("de", "Relais Saugturbine defekt")}, {"42": "Relais Saugturbine defekt"}),
        # None readable: the error shows as its code
        ({}, {}),
        ({"en": "not xml <", "de": "<ErrorTexte"}, {}),
    ],
)
async def test_without_the_instance_language_the_error_texts_fall_back_to_english_then_german(
    heater: Heater, served: dict[str, str], expected: dict[str, str]
) -> None:
    heater.error_texts = served
    client = WindhagerHttpClient(heater.host, PASSWORD)

    texts = await client.fetch_error_texts("it-IT")
    await client.close()

    assert texts == expected


async def test_a_heater_that_does_not_answer_has_no_error_texts(socket_enabled: None) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    client = WindhagerHttpClient(f"127.0.0.1:{port}", PASSWORD)

    texts = await client.fetch_error_texts("en")
    await client.close()

    assert texts == {}


async def polls_listing(modules: list[list[dict]], polls: int) -> tuple[WindhagerHttpClient, AsyncMock]:
    """A client polled `polls` times after its discovery, /1 listing each list of `modules` in turn."""
    client = WindhagerHttpClient("192.0.2.1", PASSWORD)
    lists = iter(modules)
    client.fetch = AsyncMock(side_effect=lambda url: next(lists) if url == "/1" else {"value": "1"})
    await client.fetch_all()
    for _ in range(polls):
        await client.fetch_all()
    return client, client.fetch


HEATER = {**HEATER_MODULE, "functions": [{"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN"}]}
CIRCUIT = {**CIRCUIT_MODULE, "functions": [{"fctId": 0, "fctType": 14, "lock": False, "name": "Circuit"}]}


async def test_the_modules_are_listed_again_every_ten_polls() -> None:
    _, fetch = await polls_listing([[HEATER], [HEATER]], polls=10)

    listings = [call for call in fetch.await_args_list if call.args == ("/1",)]
    assert len(listings) == 2


async def test_a_module_added_to_the_heater_is_discovered_at_the_next_listing() -> None:
    client, _ = await polls_listing([[HEATER], [HEATER, CIRCUIT]], polls=10)

    data = await client.fetch_all()

    assert any(device["type"] == "climate" for device in data["devices"])
    assert "/1/15/0/0/1/0" in data["oids"]


async def test_the_same_modules_keep_their_discovery() -> None:
    client, _ = await polls_listing([[HEATER]], polls=0)
    devices = client.devices
    client.fetch = AsyncMock(side_effect=lambda url: [HEATER] if url == "/1" else {"value": "1"})

    for _ in range(10):
        await client.fetch_all()

    assert client.devices is devices


@pytest.mark.parametrize(("failure", "raised"), [(ValueError("not JSON"), None), (InvalidAuth("refused"), InvalidAuth)])
async def test_a_listing_that_fails_keeps_the_modules_unless_the_heater_fails(
    failure: Exception, raised: type[Exception] | None
) -> None:
    client, _ = await polls_listing([[HEATER]], polls=9)
    devices = client.devices

    def fetch(url: str) -> dict:
        if url == "/1":
            raise failure
        return {"value": "1"}

    client.fetch = AsyncMock(side_effect=fetch)

    if raised:
        with pytest.raises(raised):
            await client.fetch_all()
    else:
        await client.fetch_all()
        assert client.devices is devices


def slow_reads(fetch: AsyncMock) -> int:
    """How many times the pellet consumption, a slow datapoint, was requested."""
    return sum(1 for call in fetch.await_args_list if call.args == ("/1/60/0/23/103/0",))


async def test_the_slow_datapoints_are_read_every_ten_polls_and_keep_their_value() -> None:
    client = WindhagerHttpClient("192.0.2.1", PASSWORD)
    readings = iter(["2.85", "2.86"])

    def fetch(url: str) -> list | dict:
        if url == "/1":
            return [HEATER]
        if url == "/1/60/0/23/103/0":
            return {"value": next(readings)}
        return {"value": "1"}

    client.fetch = AsyncMock(side_effect=fetch)

    first = await client.fetch_all()
    between = [await client.fetch_all() for _ in range(9)]
    eleventh = await client.fetch_all()

    # Read with the first poll, then with the eleventh: in between, the last value
    assert slow_reads(client.fetch) == 2
    assert first["oids"]["/1/60/0/23/103/0"] == "2.85"
    assert all(data["oids"]["/1/60/0/23/103/0"] == "2.85" for data in between)
    assert eleventh["oids"]["/1/60/0/23/103/0"] == "2.86"
    # The other datapoints are read on every poll
    assert sum(1 for call in client.fetch.await_args_list if call.args == ("/1/60/0/0/7/0",)) == 11


async def test_a_module_discovered_again_has_its_slow_datapoints_read_at_once() -> None:
    client, fetch = await polls_listing([[HEATER], [HEATER, CIRCUIT]], polls=4)
    assert slow_reads(fetch) == 1

    # The tenth poll lists the modules again, finds the circuit, and reads the slow datapoints
    for _ in range(6):
        await client.fetch_all()

    assert slow_reads(fetch) == 2


async def test_a_slow_datapoint_whose_request_failed_is_read_again_with_the_next_poll() -> None:
    client = WindhagerHttpClient("192.0.2.1", PASSWORD)
    answers = iter([ValueError("timed out"), {"value": "2.85"}])

    def fetch(url: str) -> list | dict:
        if url == "/1":
            return [HEATER]
        if url == "/1/60/0/23/103/0":
            answer = next(answers)
            if isinstance(answer, Exception):
                raise answer
            return answer
        if url == "/1/60/0/23/100/0":
            # Answered without a value: left as it is until the next slow read
            return {"OID": url}
        return {"value": "1"}

    client.fetch = AsyncMock(side_effect=fetch)

    first = await client.fetch_all()
    second = await client.fetch_all()
    await client.fetch_all()

    assert first["oids"]["/1/60/0/23/103/0"] is None
    assert second["oids"]["/1/60/0/23/103/0"] == "2.85"
    requested = [call.args[0] for call in client.fetch.await_args_list]
    assert requested.count("/1/60/0/23/103/0") == 2
    assert requested.count("/1/60/0/23/100/0") == 1


async def test_a_slow_datapoint_the_heater_refuses_with_409_waits_for_the_next_slow_read(heater: Heater) -> None:
    # A datapoint a function does not have, or has locked, is refused with a 409 and a
    # JSON body, the same every time (read on a BioWIN Hybrid on 2026-11-01): an answer,
    # not a failed request, so it is not requested again with the next poll
    refused = {"code": 409, "message": "Conflict", "reason": "Target returns invalid Identifier: 63-127"}
    heater.lookups = {"/1": (200, [HEATER]), "/1/60/0/23/103/0": (409, refused)}
    client = WindhagerHttpClient(heater.host, PASSWORD)

    first = await client.fetch_all()
    for _ in range(9):
        await client.fetch_all()
    await client.close()

    assert first["oids"]["/1/60/0/23/103/0"] is None
    assert heater.looked_up.count("/1/60/0/23/103/0") == 1
