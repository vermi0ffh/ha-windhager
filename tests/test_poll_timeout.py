"""A poll's timeout follows the requests it makes."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager import coordinator
from custom_components.windhager.client import MODULES_CHECK_POLLS, SLOW_VALUES_POLLS, WindhagerHttpClient
from custom_components.windhager.coordinator import poll_timeout
from tests.test_entity_names import MODULES


@pytest.mark.parametrize(
    ("requests", "seconds"),
    [
        # Before discovery: the first poll's size is unknown
        (None, 120),
        # A small heater keeps the 20 s it always had
        (10, 20),
        # 2026-11-05: 77 requests on a BioWIN 2 with five circuits, 16.4 and 20.0 s a poll
        (77, 38.5),
    ],
)
def test_the_timeout_is_half_a_second_a_request_and_never_under_twenty(requests: int | None, seconds: float) -> None:
    assert poll_timeout(requests) == seconds


async def test_the_requests_of_each_poll_are_known_beforehand() -> None:
    client = WindhagerHttpClient("192.0.2.1", "secret")
    client.fetch = AsyncMock(side_effect=lambda url: MODULES if url == "/1" else {"value": "1"})

    assert client.requests_next_poll() is None
    await client.fetch_all()

    # Over the polls with and without the slow datapoints and the check of the modules
    for _ in range(max(SLOW_VALUES_POLLS, MODULES_CHECK_POLLS) + 1):
        expected = client.requests_next_poll()
        client.fetch.reset_mock()
        await client.fetch_all()
        assert client.fetch.await_count == expected


@pytest.mark.parametrize(("requests", "state"), [(20, ConfigEntryState.LOADED), (2, ConfigEntryState.SETUP_RETRY)])
async def test_the_poll_gets_the_time_its_requests_need(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, requests: int, state: ConfigEntryState
) -> None:
    # Scaled down: 0.05 s a request, at least 0.1 s, for a poll that takes 0.3 s
    async def slow_poll() -> dict:
        await asyncio.sleep(0.3)
        return {"devices": [], "oids": {}}

    client.fetch_all.side_effect = slow_poll
    client.requests_next_poll.return_value = requests

    with (
        patch.object(coordinator, "POLL_TIMEOUT_PER_REQUEST_S", 0.05),
        patch.object(coordinator, "POLL_TIMEOUT_MIN_S", 0.1),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # 20 requests: 1 s, enough; 2 requests: 0.1 s, not enough
    assert entry.state is state
