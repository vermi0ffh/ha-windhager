"""The heater's error: a sensor naming it with the heater's own text, and a problem sensor."""

from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

ERROR_OID = "/1/60/0/2/0/0"
DEVICE = {"device_id": "biowin", "device_name": "BioWIN"}
ERROR = {"id": "error", "key": "heater_error", "type": "error", "oid": ERROR_OID, **DEVICE}
PROBLEM = {"id": "problem", "key": "heater_problem", "type": "problem", "oid": ERROR_OID, **DEVICE}
TEXTS = {"42": "Relai de la turbine d'aspiration défectueuse"}


async def set_up(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, code: str | None) -> None:
    client.fetch_all.return_value = {"devices": [ERROR, PROBLEM], "oids": {ERROR_OID: code}}
    client.fetch_error_texts.return_value = TEXTS
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_an_error_is_named_with_the_heaters_text_and_is_a_problem(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client, "42")

    error = hass.states.get("sensor.biowin_heater_error")
    assert error.state == "42: Relai de la turbine d'aspiration défectueuse"
    assert error.attributes["code"] == 42
    problem = hass.states.get("binary_sensor.biowin_heater_problem")
    assert (problem.state, problem.attributes["device_class"]) == ("on", "problem")


async def test_the_texts_are_read_in_the_instance_language(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    hass.config.language = "fr"

    await set_up(hass, entry, client, "42")

    client.fetch_error_texts.assert_awaited_once_with("fr")


async def test_an_error_the_heater_has_no_text_for_shows_its_code(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client, "5")

    error = hass.states.get("sensor.biowin_heater_error")
    assert (error.state, error.attributes["code"]) == ("5", 5)


@pytest.mark.parametrize(
    ("code", "error", "problem"),
    [
        # The heater's value without an error (2026-10-30)
        ("-", "none", "off"),
        # Not read: unknown, not "no error"
        (None, "unknown", "unknown"),
    ],
)
async def test_without_an_error_there_is_no_problem_and_unread_is_unknown(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, code: str | None, error: str, problem: str
) -> None:
    await set_up(hass, entry, client, code)

    sensor = hass.states.get("sensor.biowin_heater_error")
    assert (sensor.state, sensor.attributes["code"]) == (error, None)
    assert hass.states.get("binary_sensor.biowin_heater_problem").state == problem


@pytest.mark.parametrize(("language", "none"), [("en", "No error"), ("fr", "Aucune erreur"), ("de", "Kein Fehler")])
async def test_the_error_entities_are_translated(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str, none: str
) -> None:
    await set_up(hass, entry, client, "-")

    translations = await async_get_translations(hass, language, "entity", ["windhager"])

    assert translations["component.windhager.entity.sensor.heater_error.state.none"] == none
    assert translations["component.windhager.entity.sensor.heater_error.name"]
    assert translations["component.windhager.entity.binary_sensor.heater_problem.name"]
