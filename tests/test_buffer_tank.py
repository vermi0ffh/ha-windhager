"""A buffer tank: its temperatures, on a device of its own."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.client import SLOW_VALUES_POLLS, WindhagerHttpClient

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


# The buffer's info view on the heater's screen, beyond TPE and TPA, on a BioWIN 2 on 2026-11-05
INFO_VIEW = {
    **READINGS,
    "/1/16/1/1/15/0": "55.6",
    "/1/16/1/0/8/0": "67.0",
    "/1/16/1/1/22/0": "30",
}


async def set_up_with(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, readings: dict[str, str]
) -> WindhagerHttpClient:
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    heater.fetch = AsyncMock(side_effect=lambda url: MODULES if url == "/1" else {"value": readings.get(url, "0")})
    client.fetch_all.return_value = await heater.fetch_all()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return heater


async def test_a_buffer_shows_its_target_its_return_and_its_charging_pump(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_with(hass, entry, client, INFO_VIEW)

    target = hass.states.get("sensor.puffer_buffer_target_temperature")
    back = hass.states.get("sensor.puffer_return_temperature")
    pump = hass.states.get("sensor.puffer_heat_generator_pump")

    assert (target.state, target.attributes["unit_of_measurement"]) == ("55.6", "°C")
    assert (back.state, back.attributes["unit_of_measurement"]) == ("67.0", "°C")
    assert (pump.state, pump.attributes["unit_of_measurement"]) == ("30.0", "%")


async def test_a_buffer_without_a_return_sensor_has_no_return_temperature(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    # A BioWIN Hybrid's buffer answered it "-.-" on 2026-11-02
    await set_up_with(hass, entry, client, {**INFO_VIEW, "/1/16/1/0/8/0": "-.-"})

    assert hass.states.get("sensor.puffer_return_temperature") is None
    assert hass.states.get("sensor.puffer_heat_generator_pump") is not None


async def test_the_buffer_target_is_read_every_ten_polls(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    heater = await set_up_with(hass, entry, client, INFO_VIEW)

    for _ in range(SLOW_VALUES_POLLS):
        await heater.fetch_all()

    requested = [call.args[0] for call in heater.fetch.await_args_list]
    assert requested.count("/1/16/1/1/15/0") == 2
    assert requested.count("/1/16/1/1/22/0") == SLOW_VALUES_POLLS + 1
