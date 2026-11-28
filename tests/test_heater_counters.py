"""The heater's target temperature, operating hours, burner starts and time until maintenance."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.client import SLOW_VALUES_POLLS, WindhagerHttpClient

# The heater, as /1 listed a BioWIN Hybrid on 2026-10-31 (fake Neuron ID)
MODULES = [
    {
        "nodeId": 60,
        "name": "BioWIN Hybrid",
        "neuronId": "0a0000000060",
        "functions": [{"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN"}],
    },
]
# What the heater's app showed on 2026-10-31
READINGS = {"/1/60/0/1/7/0": "0.0", "/1/60/0/20/63/0": "6005", "/1/60/0/2/81/0": "1707", "/1/60/0/2/80/0": "482"}


async def set_up(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> WindhagerHttpClient:
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    heater.fetch = AsyncMock(side_effect=lambda url: MODULES if url == "/1" else {"value": READINGS.get(url, "1")})
    client.fetch_all.return_value = await heater.fetch_all()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return heater


async def test_the_heater_shows_its_target_hours_starts_and_time_until_maintenance(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    target = hass.states.get("sensor.biowin_heater_target_temperature")
    hours = hass.states.get("sensor.biowin_operating_hours")
    starts = hass.states.get("sensor.biowin_burner_starts")
    maintenance = hass.states.get("sensor.biowin_running_time_until_maintenance")

    assert (target.state, target.attributes["unit_of_measurement"]) == ("0.0", "°C")
    assert (hours.state, hours.attributes["unit_of_measurement"]) == ("1707.0", "h")
    assert hours.attributes["state_class"] == "total_increasing"
    assert (starts.state, starts.attributes["state_class"]) == ("482.0", "total_increasing")
    assert (maintenance.state, maintenance.attributes["unit_of_measurement"]) == ("6005.0", "h")


async def test_the_heater_counters_are_read_every_ten_polls(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    heater = await set_up(hass, entry, client)

    for _ in range(SLOW_VALUES_POLLS):
        await heater.fetch_all()

    requested = [call.args[0] for call in heater.fetch.await_args_list]
    # Read with the first poll and the eleventh; the target temperature with every poll
    assert requested.count("/1/60/0/2/80/0") == requested.count("/1/60/0/20/63/0") == 2
    assert requested.count("/1/60/0/1/7/0") == SLOW_VALUES_POLLS + 1
