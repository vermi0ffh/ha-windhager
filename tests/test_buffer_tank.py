"""A buffer tank: its temperatures, on a device of its own."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.client import WindhagerHttpClient

HEATER_ID = "0a0000000060"
# A WFBPK module with its buffer function, and the heater with a locked one, as /1 listed
# them on 2026-10-31 (fake Neuron IDs)
MODULES = [
    {
        "nodeId": 16,
        "name": "WFBPK",
        "neuronId": "0a0000000016",
        "functions": [
            {"fctId": 0, "fctType": 15, "lock": True, "name": "WVF"},
            {"fctId": 1, "fctType": 16, "lock": False, "name": "PUFFER"},
        ],
    },
    {
        "nodeId": 60,
        "name": "BioWIN Hybrid",
        "neuronId": HEATER_ID,
        "functions": [
            {"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN"},
            {"fctId": 3, "fctType": 16, "lock": True},
        ],
    },
]
# The buffer's sensors as the heater's app showed them on 2026-10-31
READINGS = {"/1/16/1/21/65/0": "40.9", "/1/16/1/21/66/0": "34.8"}


async def set_up(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> WindhagerHttpClient:
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    heater.fetch = AsyncMock(side_effect=lambda url: MODULES if url == "/1" else {"value": READINGS.get(url, "0")})
    client.fetch_all.return_value = await heater.fetch_all()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return heater


async def test_a_buffer_tank_shows_its_temperatures(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    top = hass.states.get("sensor.puffer_buffer_temperature_tpe")
    bottom = hass.states.get("sensor.puffer_buffer_temperature_tpa")

    assert (top.state, bottom.state) == ("40.9", "34.8")
    assert top.attributes["unit_of_measurement"] == "°C"
    assert er.async_get(hass).async_get("sensor.puffer_buffer_temperature_tpe").unique_id == f"{HEATER_ID}-1-16-1-21-65-0"


async def test_a_buffer_tank_is_a_device_of_its_own(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)
    entities = er.async_get(hass)

    buffer = dr.async_get(hass).async_get(entities.async_get("sensor.puffer_buffer_temperature_tpe").device_id)
    heater = dr.async_get(hass).async_get(entities.async_get("sensor.biowin_heater_temperature").device_id)

    assert (buffer.name, buffer.model) == ("PUFFER", "WFBPK")
    assert buffer.id != heater.id


async def test_a_locked_buffer_function_is_not_read(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    heater = await set_up(hass, entry, client)

    requested = {call.args[0] for call in heater.fetch.await_args_list}

    assert "/1/16/1/21/65/0" in requested
    assert not any(url.startswith("/1/60/3/") for url in requested)
