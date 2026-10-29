"""How Home Assistant shows the entities: categories, disabled by default, state classes, icons."""

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.icon import async_get_icons
from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.test_entity_names import heater_data, set_up

CORRECTIONS = {
    "sensor.circuit_comfort_temperature_correction",
    "sensor.circuit_current_temperature_correction",
}


async def test_the_settings_and_maintenance_counters_are_diagnostics(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client, "en")

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)

    assert {entity.entity_id for entity in entities if entity.entity_category == "diagnostic"} == CORRECTIONS | {
        "sensor.circuit_current_temperature_real",
        "sensor.biowin_running_time_until_stage_1_cleaning",
        "sensor.biowin_running_time_until_stage_2_cleaning",
    }


async def test_a_new_installation_has_the_corrections_disabled(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client, "en")

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)

    assert {entity.entity_id for entity in entities if entity.disabled_by is not None} == CORRECTIONS


async def test_a_correction_created_before_stays_enabled(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    data = await heater_data()
    [correction] = [device for device in data["devices"] if device.get("key") == "comfort_temperature_correction"]
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        "windhager",
        correction["id"],
        config_entry=entry,
        suggested_object_id="circuit_comfort_temperature_correction",
    )

    await set_up(hass, entry, client, "en")

    assert hass.states.get("sensor.circuit_comfort_temperature_correction").state == "1.0"


async def test_the_temperatures_keep_long_term_statistics(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client, "en")

    temperatures = [
        state for state in hass.states.async_all("sensor") if state.attributes.get("device_class") == "temperature"
    ]

    assert temperatures and all(state.attributes.get("state_class") == "measurement" for state in temperatures)


async def test_the_heater_status_and_presets_have_icons(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client, "en")

    icons = (await async_get_icons(hass, "entity", ["windhager"]))["windhager"]

    assert icons["sensor"]["heater_status"]["state"]["3"] == "mdi:power-sleep"
    assert icons["climate"]["windhager_climate"]["state_attributes"]["preset_mode"]["state"]["5"] == "mdi:weather-night"
