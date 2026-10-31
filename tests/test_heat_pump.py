"""A BioWIN Hybrid's heat pump and hybrid manager: their sensors, each a device of its own."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.client import SLOW_VALUES_POLLS, WindhagerHttpClient

# A BioWIN Hybrid, as /1 listed one on 2026-10-31 (fake Neuron ID)
MODULES = [
    {
        "nodeId": 60,
        "name": "BioWIN Hybrid",
        "neuronId": "0a0000000060",
        "functions": [
            {"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN"},
            {"fctId": 1, "fctType": 7, "lock": False, "name": "AeroWIN"},
            {"fctId": 2, "fctType": 26, "lock": False, "name": "Hybrid"},
        ],
    },
]
# What the heater's app showed on 2026-10-31, the heat pump running
READINGS = {
    "/1/60/1/52/59/0": "50.22",
    "/1/60/1/52/60/0": "60.8",
    "/1/60/1/52/61/0": "9.50",
    "/1/60/1/52/62/0": "25.1",
    "/1/60/1/52/50/0": "5046",
    "/1/60/1/52/51/0": "5.5",
    "/1/60/1/52/52/0": "893",
    "/1/60/1/52/53/0": "1.9",
    "/1/60/1/52/56/0": "13787",
    "/1/60/1/52/87/0": "3.8",
    "/1/60/1/52/89/0": "3.9",
    "/1/60/1/50/26/0": "100.0",
    "/1/60/1/50/6/0": "4",
    "/1/60/2/52/10/0": "7.9",
    "/1/60/2/54/49/0": "2",
}


async def set_up(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> WindhagerHttpClient:
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    heater.fetch = AsyncMock(side_effect=lambda url: MODULES if url == "/1" else {"value": READINGS.get(url, "1")})
    client.fetch_all.return_value = await heater.fetch_all()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return heater


def state(hass: HomeAssistant, entity_id: str) -> tuple[str, str | None]:
    entity = hass.states.get(entity_id)
    return entity.state, entity.attributes.get("unit_of_measurement")


async def test_the_heat_pump_shows_its_heat_quantities_for_the_energy_dashboard(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    assert state(hass, "sensor.aerowin_heat_quantity_heating") == ("50.22", "MWh")
    assert state(hass, "sensor.aerowin_heat_quantity_heating_today") == ("60.8", "kWh")
    assert state(hass, "sensor.aerowin_heat_quantity_hot_water") == ("9.5", "MWh")
    assert state(hass, "sensor.aerowin_heat_quantity_hot_water_today") == ("25.1", "kWh")
    heating = hass.states.get("sensor.aerowin_heat_quantity_heating").attributes
    assert (heating["device_class"], heating["state_class"]) == ("energy", "total_increasing")


async def test_the_heat_pump_shows_its_hours_starts_cop_and_output(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    assert state(hass, "sensor.aerowin_operating_hours_heating") == ("5046.0", "h")
    assert state(hass, "sensor.aerowin_operating_hours_heating_today") == ("5.5", "h")
    assert state(hass, "sensor.aerowin_operating_hours_hot_water") == ("893.0", "h")
    assert state(hass, "sensor.aerowin_operating_hours_hot_water_today") == ("1.9", "h")
    assert state(hass, "sensor.aerowin_starts") == ("13787.0", None)
    assert state(hass, "sensor.aerowin_average_cop_heating_today") == ("3.8", None)
    assert state(hass, "sensor.aerowin_average_cop_hot_water_today") == ("3.9", None)
    assert state(hass, "sensor.aerowin_output") == ("100.0", "%")


async def test_the_heat_pump_phase_is_named_when_known_and_its_code_otherwise(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)
    translations = await async_get_translations(hass, "de", "entity", {"windhager"})
    key = "component.windhager.entity.sensor.heat_pump_phase.state"

    phase = hass.states.get("sensor.aerowin_operating_phase")

    assert phase.state == "4"
    assert phase.attributes["options"] == [str(code) for code in range(16)]
    assert (translations[f"{key}.3"], translations[f"{key}.4"]) == ("Standby", "Heizen")
    # A phase not seen yet shows as its code
    assert f"{key}.5" not in translations


async def test_the_hybrid_manager_shows_its_outdoor_temperature_and_sg_ready_state(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    assert state(hass, "sensor.hybrid_outdoor_temperature_control") == ("7.9", "°C")
    assert state(hass, "sensor.hybrid_sg_ready_state") == ("2", None)
    translations = await async_get_translations(hass, "de", "entity", {"windhager"})
    # As the heater's app shows it
    assert translations["component.windhager.entity.sensor.sg_ready_state.state.2"] == "Zustand 2"


async def test_the_heat_pump_and_the_hybrid_manager_are_devices_of_their_own(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)
    entities = er.async_get(hass)
    devices = dr.async_get(hass)

    def device_of(entity_id: str) -> dr.DeviceEntry:
        return devices.async_get(entities.async_get(entity_id).device_id)

    heat_pump = device_of("sensor.aerowin_output")
    hybrid = device_of("sensor.hybrid_sg_ready_state")
    heater = device_of("sensor.biowin_heater_temperature")

    assert (heat_pump.name, hybrid.name) == ("AeroWIN", "Hybrid")
    assert heat_pump.model == hybrid.model == "BioWIN Hybrid"
    assert len({heat_pump.id, hybrid.id, heater.id}) == 3


async def test_the_heat_pump_totals_are_read_every_ten_polls_its_output_every_poll(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    heater = await set_up(hass, entry, client)

    for _ in range(SLOW_VALUES_POLLS):
        await heater.fetch_all()

    requested = [call.args[0] for call in heater.fetch.await_args_list]
    assert requested.count("/1/60/1/52/59/0") == requested.count("/1/60/1/52/87/0") == 2
    assert requested.count("/1/60/1/50/26/0") == requested.count("/1/60/2/52/10/0") == SLOW_VALUES_POLLS + 1
