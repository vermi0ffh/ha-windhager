"""The HTTP client against a heater asking for digest authentication (RFC 7616, MD5, qop=auth)."""

import hashlib
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.windhager.client import WindhagerHttpClient, heater_id
from custom_components.windhager.const import DEFAULT_USERNAME
from custom_components.windhager.exceptions import InvalidAuth

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
