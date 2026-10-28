"""Setting up and unloading a config entry."""

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_a_heater_answering_at_start_is_set_up(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    client.close.assert_not_awaited()


async def test_a_heater_silent_at_start_is_retried_and_its_session_closed(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.fetch_all.side_effect = TimeoutError

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    client.close.assert_awaited_once()


async def test_unloading_closes_the_session(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.config_entries.async_unload(entry.entry_id)

    assert entry.state is ConfigEntryState.NOT_LOADED
    client.close.assert_awaited_once()
