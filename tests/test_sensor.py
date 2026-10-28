"""The heater status sensor."""

from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

STATUS_OID = "/1/15/0/2/1/0"
STATUS = {
    "id": "heater_status",
    "name": "BioWIN Heater status",
    "type": "select",
    "oid": STATUS_OID,
    "device_id": "biowin",
    "device_name": "BioWIN",
}


async def heater_status(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, code: str) -> State:
    """The status sensor's state once the entry is set up with the heater reporting `code`."""
    client.fetch_all.return_value = {"devices": [STATUS], "oids": {STATUS_OID: code}}
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    [state] = hass.states.async_all("sensor")
    return state


@pytest.mark.parametrize(("code", "expected"), [("3", "3"), ("17", "17"), ("16", "unknown")])
async def test_the_heater_status_is_its_code_among_the_known_ones(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, code: str, expected: str
) -> None:
    state = await heater_status(hass, entry, client, code)

    assert state.state == expected
    assert state.attributes["device_class"] == "enum"
    assert state.attributes["options"] == [str(code) for code in (*range(16), 17)]


@pytest.mark.parametrize(("language", "label"), [("en", "Standby"), ("fr", "Veille"), ("de", "Standby")])
async def test_the_heater_status_is_translated(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str, label: str
) -> None:
    await heater_status(hass, entry, client, "3")

    translations = await async_get_translations(hass, language, "entity", ["windhager"])

    assert translations["component.windhager.entity.sensor.heater_status.state.3"] == label
