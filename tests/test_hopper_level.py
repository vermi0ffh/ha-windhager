"""The hopper level: a datapoint the heater's lookups do not list."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.client import WindhagerHttpClient
from tests.test_entity_names import MODULES

HOPPER_OID = "/1/60/0/43/42/0"


async def hopper_level(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, value: str) -> State:
    """The hopper level sensor's state once the entry is set up with the heater reporting `value`."""
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    heater.fetch = AsyncMock(
        side_effect=lambda url: MODULES if url == "/1" else {"value": value if url == HOPPER_OID else "1"}
    )
    client.fetch_all.return_value = await heater.fetch_all()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return hass.states.get("sensor.biowin_hopper_level")


# 2026-10-31: 79 %, the level the heater's mobile app showed
async def test_the_hopper_level_is_a_percentage_with_statistics(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    state = await hopper_level(hass, entry, client, "79")

    assert state.state == "79.0"
    assert state.name == "BioWIN Hopper level"
    assert state.attributes["unit_of_measurement"] == "%"
    assert state.attributes["state_class"] == "measurement"


async def test_a_hopper_level_that_is_not_a_number_is_unknown(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    state = await hopper_level(hass, entry, client, "-.-")

    assert state.state == "unknown"


@pytest.mark.parametrize(
    ("language", "name"), [("en", "Hopper level"), ("fr", "Niveau de la trémie"), ("de", "Füllstand Vorratsbehälter")]
)
async def test_the_hopper_level_is_translated(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str, name: str
) -> None:
    await hopper_level(hass, entry, client, "79")

    translations = await async_get_translations(hass, language, "entity", ["windhager"])

    assert translations["component.windhager.entity.sensor.hopper_level.name"] == name
