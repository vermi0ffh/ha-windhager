"""The heater's operating mode: on, or switched off on the heater's screen."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.icon import async_get_icons
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.client import WindhagerHttpClient
from tests.test_entity_names import MODULES

MODE_OID = "/1/60/0/2/59/0"


async def operating_mode(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, code: str) -> State:
    """The operating mode sensor's state once the entry is set up with the heater reporting `code`."""
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    heater.fetch = AsyncMock(
        side_effect=lambda url: MODULES if url == "/1" else {"value": code if url == MODE_OID else "1"}
    )
    client.fetch_all.return_value = await heater.fetch_all()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.states.get("sensor.biowin_operating_mode")


# 2026-10-31: 0 once the heater was switched off on its screen, 5 once switched back on
@pytest.mark.parametrize(("code", "expected"), [("0", "0"), ("5", "5"), ("11", "11"), ("12", "unknown")])
async def test_the_operating_mode_is_its_code_among_the_known_ones(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, code: str, expected: str
) -> None:
    state = await operating_mode(hass, entry, client, code)

    assert state.state == expected
    assert state.attributes["device_class"] == "enum"
    assert state.attributes["options"] == [str(code) for code in range(12)]


@pytest.mark.parametrize(
    ("language", "off", "on"),
    [("en", "Switched off", "On"), ("fr", "Désactivée", "Marche"), ("de", "Ausgeschaltet", "Ein")],
)
async def test_the_operating_mode_is_translated(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str, off: str, on: str
) -> None:
    state = await operating_mode(hass, entry, client, "5")

    translations = await async_get_translations(hass, language, "entity", ["windhager"])

    assert translations["component.windhager.entity.sensor.operating_mode.state.0"] == off
    assert translations["component.windhager.entity.sensor.operating_mode.state.5"] == on
    for code in state.attributes["options"]:
        assert translations[f"component.windhager.entity.sensor.operating_mode.state.{code}"]


async def test_the_operating_mode_belongs_to_the_heater_and_has_icons(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    state = await operating_mode(hass, entry, client, "0")

    icons = (await async_get_icons(hass, "entity", ["windhager"]))["windhager"]

    assert state.name == "BioWIN Operating mode"
    assert icons["sensor"]["operating_mode"]["default"] == "mdi:power"
    assert icons["sensor"]["operating_mode"]["state"]["0"] == "mdi:power-off"
