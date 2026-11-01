"""A module holding two heating circuits: each has its climate, sensors and device."""

from unittest.mock import AsyncMock, MagicMock, call

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.client import WindhagerHttpClient

HEATER_ID = "0a0000000060"
# An UMUMLZ with two circuits, as /1 listed one on 2026-10-31 (fake Neuron IDs), and the heater
MODULES = [
    {
        "nodeId": 15,
        "name": "UMUMLZ",
        "neuronId": "0a0000000015",
        "functions": [
            {"fctId": 0, "fctType": 14, "lock": False, "name": "BOILER/FBH"},
            {"fctId": 1, "fctType": 14, "lock": False, "name": "RADIATOREN"},
            {"fctId": 32, "fctType": -1, "lock": False, "name": "NV's"},
        ],
    },
    {
        "nodeId": 60,
        "name": "BioWIN Hybrid",
        "neuronId": HEATER_ID,
        "functions": [{"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN"}],
    },
]
# Each circuit's room and target temperatures, as read on 2026-10-31
READINGS = {
    "/1/15/0/0/1/0": "23.1",
    "/1/15/0/1/1/0": "22.5",
    "/1/15/1/0/1/0": "22.0",
    "/1/15/1/1/1/0": "25.0",
}


async def set_up(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    heater.fetch = AsyncMock(side_effect=lambda url: MODULES if url == "/1" else {"value": READINGS.get(url, "0")})
    client.fetch_all.return_value = await heater.fetch_all()
    client.update = AsyncMock()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_the_second_circuit_of_a_module_has_its_own_climate_reading_its_own_values(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    first = hass.states.get("climate.boiler_fbh_without_bias")
    second = hass.states.get("climate.radiatoren_without_bias")

    assert (first.attributes["current_temperature"], first.attributes["temperature"]) == (23.1, 22.5)
    assert (second.attributes["current_temperature"], second.attributes["temperature"]) == (22.0, 25.0)
    assert hass.states.get("sensor.radiatoren_current_temperature_real").state == "22.0"


async def test_the_second_circuit_is_a_device_of_its_own_on_the_same_module(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)
    entities = er.async_get(hass)
    devices = dr.async_get(hass)

    first = devices.async_get(entities.async_get("climate.boiler_fbh").device_id)
    second = devices.async_get(entities.async_get("climate.radiatoren").device_id)

    assert first.id != second.id
    assert (first.name, second.name) == ("BOILER/FBH", "RADIATOREN")
    assert first.model == second.model == "UMUMLZ"
    assert devices.async_get(entities.async_get("sensor.radiatoren_outside_temperature").device_id) == second


async def test_the_first_circuit_keeps_its_unique_ids_and_the_second_has_its_own(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)
    entities = er.async_get(hass)

    # The ids the first circuit always had: its history is kept
    assert entities.async_get("climate.boiler_fbh").unique_id == f"{HEATER_ID}-1-15"
    assert entities.async_get("sensor.boiler_fbh_target_temperature").unique_id == f"{HEATER_ID}-1-15-0-1-1-0"
    assert entities.async_get("climate.radiatoren").unique_id == f"{HEATER_ID}-1-15-1"
    assert entities.async_get("sensor.radiatoren_target_temperature").unique_id == f"{HEATER_ID}-1-15-1-1-1-0"


async def test_the_second_circuit_writes_its_own_datapoints(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": "climate.radiatoren", "temperature": 21.5}, blocking=True
    )

    assert client.update.await_args_list == [call("/1/15/1/3/4/0", "21.5"), call("/1/15/1/2/10/0", "400")]
