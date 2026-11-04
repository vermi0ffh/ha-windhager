"""Setting up and unloading a config entry."""

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.exceptions import InvalidAuth


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


async def test_a_password_refused_at_start_stops_the_setup_and_asks_for_a_new_one(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.fetch_all.side_effect = InvalidAuth("refused")

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    client.close.assert_awaited_once()
    assert [flow["context"]["source"] for flow in hass.config_entries.flow.async_progress_by_handler("windhager")] == [
        "reauth"
    ]


async def test_a_password_refused_while_polling_asks_for_a_new_one(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    client.fetch_all.side_effect = InvalidAuth("refused")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert [flow["context"]["source"] for flow in hass.config_entries.flow.async_progress_by_handler("windhager")] == [
        "reauth"
    ]


async def test_unloading_closes_the_session(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.config_entries.async_unload(entry.entry_id)

    assert entry.state is ConfigEntryState.NOT_LOADED
    client.close.assert_awaited_once()


async def test_an_entry_added_before_gets_the_heater_id_as_unique_id(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.fetch_all.return_value = {"devices": [], "heater_id": "0a0000000060", "oids": {}}

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.unique_id == "0a0000000060"


async def test_an_entry_duplicating_another_keeps_no_unique_id(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    MockConfigEntry(domain="windhager", unique_id="0a0000000060", data={"host": "192.0.2.9"}).add_to_hass(hass)
    client.fetch_all.return_value = {"devices": [], "heater_id": "0a0000000060", "oids": {}}

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.unique_id is None
