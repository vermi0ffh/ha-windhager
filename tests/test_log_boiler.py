"""A log boiler (LogWIN): its temperatures, status, error and the buffer tank it reads."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.client import WindhagerHttpClient

# A BioWIN and a LogWIN on the same bus, as /1 listed them on 2026-11-06 (fake Neuron IDs)
BIOWIN = {"nodeId": 60, "neuronId": "0a0000000060", "functions": [{"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN 2"}]}
LOGWIN = {
    "nodeId": 65,
    "name": "LogWIN",
    "neuronId": "0a0000000065",
    "functions": [
        {"fctId": 0, "fctType": 10, "lock": False, "name": "LogWIN"},
        {"fctId": 32, "fctType": -1, "lock": False, "name": "NV's"},
    ],
}

# The LogWIN's values read on 2026-11-06, the boiler out and the buffer half charged
VALUES = {
    "/1/65/0/0/7/0": "30.36",
    "/1/65/0/0/11/0": "29.6",
    "/1/65/0/0/45/0": "31.0",
    "/1/65/0/0/15/0": "75.3",
    "/1/65/0/0/16/0": "40.8",
    "/1/65/0/23/87/0": "51",
    "/1/65/0/2/1/0": "3",
    "/1/65/0/2/59/0": "5",
    "/1/65/0/2/0/0": "-",
    "/1/65/0/20/112/0": "110",
    "/1/65/0/2/81/0": "1592",
}


async def set_up(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    client: MagicMock,
    modules: list[dict] | None = None,
    values: dict[str, str] | None = None,
) -> list[str]:
    """Set the entry up with the heater listing `modules`; the URLs the client requested."""
    modules = [BIOWIN, LOGWIN] if modules is None else modules
    values = {**VALUES, **(values or {})}
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    requested: list[str] = []

    async def fetch(url: str) -> object:
        requested.append(url)
        return modules if url == "/1" else {"value": values.get(url, "1")}

    heater.fetch = AsyncMock(side_effect=fetch)
    client.fetch_all.return_value = await heater.fetch_all()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return requested


async def test_the_log_boiler_reports_its_temperatures(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    for entity_id, value in (
        ("sensor.logwin_heater_temperature", "30.36"),
        ("sensor.logwin_fumes_temperature", "29.6"),
        ("sensor.logwin_combustion_chamber_temperature", "31.0"),
        ("sensor.logwin_buffer_temperature_top", "75.3"),
        ("sensor.logwin_buffer_temperature_bottom", "40.8"),
    ):
        state = hass.states.get(entity_id)
        assert state.state == value, entity_id
        assert state.attributes["unit_of_measurement"] == "°C"
        assert state.attributes["device_class"] == "temperature"


async def test_the_buffer_charge_level_is_a_percentage_with_statistics(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    state = hass.states.get("sensor.logwin_buffer_charge_level")

    assert state.state == "51.0"
    assert state.attributes["unit_of_measurement"] == "%"
    assert state.attributes["state_class"] == "measurement"


async def test_the_counters_only_increase(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    await set_up(hass, entry, client)

    firings = hass.states.get("sensor.logwin_number_of_firings")
    hours = hass.states.get("sensor.logwin_operating_hours")

    assert firings.state == "110.0"
    assert firings.attributes["state_class"] == "total_increasing"
    assert hours.state == "1592.0"
    assert hours.attributes["unit_of_measurement"] == "h"
    assert hours.attributes["device_class"] == "duration"
    assert hours.attributes["state_class"] == "total_increasing"


# The LogWIN's codes are the BioWIN's (2026-11-06: 3 "Standby", 5 "Ein")
async def test_the_status_and_operating_mode_use_the_heaters_codes(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    status = hass.states.get("sensor.logwin_heater_status")
    mode = hass.states.get("sensor.logwin_operating_mode")

    assert status.state == "3"
    assert "17" in status.attributes["options"]
    assert mode.state == "5"


async def test_the_log_boiler_has_no_error_until_it_reports_one(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    assert hass.states.get("sensor.logwin_heater_error").state == "none"
    assert hass.states.get("binary_sensor.logwin_heater_problem").state == "off"


async def test_an_error_of_the_log_boiler_is_a_problem(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client, values={"/1/65/0/2/0/0": "42"})

    assert hass.states.get("sensor.logwin_heater_error").state == "42"
    assert hass.states.get("binary_sensor.logwin_heater_problem").state == "on"


async def test_the_log_boiler_is_a_device_of_its_own(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    devices = {device.name: device for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)}

    assert devices["LogWIN"].model == "LogWIN"
    assert devices["LogWIN"].serial_number == "0a0000000065"
    assert devices["LogWIN"].id != devices["BioWIN 2"].id


async def test_only_the_log_boilers_datapoints_are_read(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    requested = await set_up(hass, entry, client)

    # Every LogWIN request is one of its known datapoints: nothing of its operator or service levels
    log_boiler = {url for url in requested if url.startswith("/1/65/")}
    assert log_boiler == set(VALUES)


async def test_a_locked_log_boiler_has_no_entities(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    locked = {**LOGWIN, "functions": [{"fctId": 0, "fctType": 10, "lock": True, "name": "LogWIN"}]}

    requested = await set_up(hass, entry, client, modules=[BIOWIN, locked])

    assert not [url for url in requested if url.startswith("/1/65/")]
    assert hass.states.get("sensor.logwin_heater_temperature") is None


async def test_a_log_boiler_without_a_biowin_has_its_entities(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client, modules=[LOGWIN])

    assert hass.states.get("sensor.logwin_buffer_temperature_top").state == "75.3"


@pytest.mark.parametrize(
    ("language", "names"),
    [
        ("en", ("Buffer temperature top", "Buffer charge level", "Number of firings", "Operating hours")),
        ("fr", ("Température haute du ballon tampon", "Niveau de charge du ballon tampon", "Nombre d'allumages", "Heures de fonctionnement")),
        ("de", ("Puffertemperatur oben", "Puffer-Beladegrad", "Anzahl Anheizvorgänge", "Betriebsstunden")),
    ],
)
async def test_the_log_boilers_sensors_are_translated(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str, names: tuple[str, ...]
) -> None:
    await set_up(hass, entry, client)

    translations = await async_get_translations(hass, language, "entity", ["windhager"])

    keys = ("buffer_temperature_top", "buffer_charge_level", "firing_count", "operating_hours")
    for key, name in zip(keys, names, strict=True):
        assert translations[f"component.windhager.entity.sensor.{key}.name"] == name
