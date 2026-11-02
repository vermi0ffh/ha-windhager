"""The enum sensors and the heater's own texts of their codes (res/xml/AufzaehlTexte)."""

from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.sensor import enum_key

STATUS_OID = "/1/60/0/2/1/0"
MODE_OID = "/1/60/0/2/59/0"
DEVICE = {"device_id": "biowin", "device_name": "BioWIN"}
STATUS = {"id": "status", "key": "heater_status", "type": "select", "oid": STATUS_OID, **DEVICE}
MODE = {"id": "mode", "key": "operating_mode", "type": "operating_mode", "oid": MODE_OID, **DEVICE}
# As the InfoWIN Touch names them (2026-11-01), with a code 18 a newer firmware could add
TEXTS = {
    "2/1": {"3": "Standby", "8": "Modulationsbetrieb", "18": "Neuer Status"},
    "2/59": {"0": "Ausgeschaltet", "5": "Ein"},
}


async def set_up(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, status: str, texts: dict
) -> tuple[State, State]:
    """The status and operating mode sensors once set up, the heater reporting `status` and mode 5."""
    client.fetch_all.return_value = {"devices": [STATUS, MODE], "oids": {STATUS_OID: status, MODE_OID: "5"}}
    client.fetch_enum_texts.return_value = texts
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.states.get("sensor.biowin_heater_status"), hass.states.get("sensor.biowin_operating_mode")


def test_the_texts_key_is_the_datapoints_group_and_member() -> None:
    assert enum_key(STATUS_OID) == "2/1"
    assert enum_key(MODE_OID) == "2/59"
    assert enum_key(None) == ""


async def test_a_known_code_carries_the_heaters_text(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    status, mode = await set_up(hass, entry, client, "8", TEXTS)

    assert (status.state, status.attributes["heater_text"]) == ("8", "Modulationsbetrieb")
    assert (mode.state, mode.attributes["heater_text"]) == ("5", "Ein")


async def test_a_code_only_the_heater_names_is_a_state_with_its_text(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    status, _ = await set_up(hass, entry, client, "18", TEXTS)

    assert (status.state, status.attributes["heater_text"]) == ("18", "Neuer Status")
    assert status.attributes["options"] == [str(code) for code in range(19)]


async def test_without_the_heaters_texts_the_known_codes_stay_the_options(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    status, mode = await set_up(hass, entry, client, "18", {})

    # As before the heater's texts: a code the translations do not name is unknown
    assert (status.state, status.attributes["heater_text"]) == ("unknown", None)
    assert status.attributes["options"] == [str(code) for code in range(18)]
    assert (mode.state, mode.attributes["heater_text"]) == ("5", None)
    assert mode.attributes["options"] == [str(code) for code in range(12)]


async def test_the_texts_are_read_in_the_instance_language(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    hass.config.language = "fr"

    await set_up(hass, entry, client, "3", TEXTS)

    client.fetch_enum_texts.assert_awaited_once_with("fr")


@pytest.mark.parametrize("language", ["en", "fr", "de"])
async def test_the_heater_text_attribute_is_translated(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str
) -> None:
    await set_up(hass, entry, client, "3", TEXTS)

    translations = await async_get_translations(hass, language, "entity", ["windhager"])

    for key in ("heater_status", "operating_mode"):
        assert translations[f"component.windhager.entity.sensor.{key}.state_attributes.heater_text.name"]
