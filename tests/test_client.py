"""The HTTP client against a heater asking for digest authentication (RFC 7616, MD5, qop=auth)."""

import hashlib
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.windhager.client import WindhagerHttpClient
from custom_components.windhager.const import DEFAULT_USERNAME

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

    with pytest.raises(Exception):
        await client.fetch("/1")
    await client.close()

    assert heater.challenges == 2
