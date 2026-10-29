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
        return web.json_response([{"nodeId": 15, "name": "BioWIN"}])

    app = web.Application()
    app.router.add_route("*", "/api/1.0/{path:.*}", handle)
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

    assert data["oids"] and all(value is None for value in data["oids"].values())


async def test_a_heater_that_does_not_answer_a_lookup_cannot_connect(socket_enabled: None) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    client = WindhagerHttpClient(f"127.0.0.1:{port}", PASSWORD)

    with pytest.raises(CannotConnect):
        await client.fetch("/1")
    await client.close()
