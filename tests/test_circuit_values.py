"""A heating circuit's hot water, flow and boiler temperatures, pumps and operating mode."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.client import WindhagerHttpClient
from custom_components.windhager.exceptions import CannotConnect

# An UMUMLZ with a circuit doing floor heating and hot water, and one doing radiators only,
# as /1 listed one on 2026-10-31 (fake Neuron IDs)
MODULES = [
    {
        "nodeId": 15,
        "name": "UMUMLZ",
        "neuronId": "0a0000000015",
        "functions": [
            {"fctId": 0, "fctType": 14, "lock": False, "name": "BOILER/FBH"},
            {"fctId": 1, "fctType": 14, "lock": False, "name": "RADIATOREN"},
        ],
    },
]
# What the heater's app showed on each circuit's Info screen on 2026-10-31; RADIATOREN has
# no hot water and answers those datapoints without a value
READINGS = {
    "/1/15/0/0/4/0": "52.7",
    "/1/15/0/1/4/0": "45.0",
    "/1/15/0/0/2/0": "28.4",
    "/1/15/0/1/2/0": "0.0",
    "/1/15/0/0/7/0": "40.7",
    "/1/15/0/1/7/0": "61.0",
    "/1/15/0/2/9/0": "8",
    "/1/15/0/1/20/0": "0",
    "/1/15/0/1/66/0": "0",
    "/1/15/1/0/2/0": "38.2",
    "/1/15/1/1/2/0": "50.0",
    "/1/15/1/2/9/0": "1",
    "/1/15/1/1/20/0": "100",
}
WITHOUT_VALUE = {"/1/15/1/0/4/0", "/1/15/1/1/4/0", "/1/15/1/1/66/0"}


def answer(url: str) -> list | dict:
    if url == "/1":
        return MODULES
    if url in WITHOUT_VALUE:
        return {"OID": url}
    return {"value": READINGS.get(url, "0")}


async def set_up(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> WindhagerHttpClient:
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    heater.fetch = AsyncMock(side_effect=answer)
    client.fetch_all.return_value = await heater.fetch_all()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return heater


async def test_a_circuit_shows_its_hot_water_flow_and_boiler_temperatures(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    states = {
        entity_id: hass.states.get(entity_id).state
        for entity_id in (
            "sensor.boiler_fbh_hot_water_temperature",
            "sensor.boiler_fbh_hot_water_target_temperature",
            "sensor.boiler_fbh_flow_temperature",
            "sensor.boiler_fbh_flow_target_temperature",
            "sensor.boiler_fbh_boiler_temperature",
            "sensor.boiler_fbh_boiler_target_temperature",
            "sensor.radiatoren_flow_temperature",
            "sensor.radiatoren_flow_target_temperature",
        )
    }

    assert states == {
        "sensor.boiler_fbh_hot_water_temperature": "52.7",
        "sensor.boiler_fbh_hot_water_target_temperature": "45.0",
        "sensor.boiler_fbh_flow_temperature": "28.4",
        "sensor.boiler_fbh_flow_target_temperature": "0.0",
        "sensor.boiler_fbh_boiler_temperature": "40.7",
        "sensor.boiler_fbh_boiler_target_temperature": "61.0",
        "sensor.radiatoren_flow_temperature": "38.2",
        "sensor.radiatoren_flow_target_temperature": "50.0",
    }
    assert hass.states.get("sensor.boiler_fbh_hot_water_temperature").attributes["unit_of_measurement"] == "°C"


async def test_a_circuit_without_hot_water_has_no_hot_water_entities(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    heater = await set_up(hass, entry, client)
    entity_ids = {entity.entity_id for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}

    assert "sensor.boiler_fbh_hot_water_temperature" in entity_ids
    assert "binary_sensor.boiler_fbh_hot_water_charging_pump" in entity_ids
    assert not any(entity_id.startswith("sensor.radiatoren_hot_water") for entity_id in entity_ids)
    assert "binary_sensor.radiatoren_hot_water_charging_pump" not in entity_ids
    # Its hot water datapoints are no longer requested
    heater.fetch.reset_mock()
    await heater.fetch_all()
    requested = {call.args[0] for call in heater.fetch.await_args_list}
    assert not requested & WITHOUT_VALUE
    assert "/1/15/0/0/4/0" in requested


async def test_a_circuit_pump_runs_while_the_heater_reads_it_above_zero(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    assert hass.states.get("binary_sensor.boiler_fbh_circuit_pump").state == "off"
    assert hass.states.get("binary_sensor.radiatoren_circuit_pump").state == "on"
    assert hass.states.get("binary_sensor.radiatoren_circuit_pump").attributes["device_class"] == "running"


async def test_a_circuit_operating_mode_is_named_by_the_heater_texts(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)
    translations = await async_get_translations(hass, "de", "entity", {"windhager"})
    key = "component.windhager.entity.sensor.circuit_operating_mode.state"

    standby = hass.states.get("sensor.boiler_fbh_operating_mode")
    heating = hass.states.get("sensor.radiatoren_operating_mode")

    assert (standby.state, heating.state) == ("8", "1")
    assert len(standby.attributes["options"]) == 17
    # The InfoWIN Touch's own texts, as the heater's app shows them
    assert translations[f"{key}.8"] == "Standby Heizgrenze"
    assert translations[f"{key}.1"] == "Heizbetrieb"


async def test_a_hot_water_request_failing_on_the_first_poll_keeps_its_entities(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    failures = iter([TimeoutError()])

    def flaky(url: str) -> list | dict:
        # The first request of BOILER/FBH's hot water temperature times out
        if url == "/1/15/0/0/4/0" and (failure := next(failures, None)):
            raise failure
        return answer(url)

    heater.fetch = AsyncMock(side_effect=flaky)
    first = await heater.fetch_all()
    second = await heater.fetch_all()
    client.fetch_all.return_value = second
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert any(device.get("oid") == "/1/15/0/0/4/0" for device in first["devices"])
    assert hass.states.get("sensor.boiler_fbh_hot_water_temperature").state == "52.7"
    # RADIATOREN answered without a value: it has no hot water, as before
    assert hass.states.get("sensor.radiatoren_hot_water_temperature") is None


# A BioWIN 2 with three UMUMLZ, read on 2026-11-01: a module's first function answers its
# configured hot water ("WW-Kreis", 5/76) with 0 when it has none, and its charging pump with
# 0 all the same; its second function does not list 5/76 (fake Neuron IDs)
CONFIGURED_MODULES = [
    {
        "nodeId": 16,
        "name": "UMUMLZ",
        "neuronId": "0a0000000016",
        "functions": [
            {"fctId": 0, "fctType": 14, "lock": False, "name": "RADIATORS"},
            {"fctId": 1, "fctType": 14, "lock": False, "name": "FLOOR"},
        ],
    },
    {
        "nodeId": 17,
        "name": "UMUMLZ",
        "neuronId": "0a0000000017",
        "functions": [{"fctId": 0, "fctType": 14, "lock": False, "name": "HOT WATER"}],
    },
]
CONFIGURATIONS = {
    "/1/16/0/103": [{"OID": "/1/16/0/7/76/0", "value": "1"}, {"OID": "/1/16/0/5/76/0", "value": "0"}],
    "/1/16/1/103": [{"OID": "/1/16/1/7/76/0", "value": "2"}],
    "/1/17/0/103": [{"OID": "/1/17/0/7/76/0", "value": "0"}, {"OID": "/1/17/0/5/76/0", "value": "1"}],
}


def configured(url: str) -> list | dict:
    if url == "/1":
        return CONFIGURED_MODULES
    if url in CONFIGURATIONS:
        return CONFIGURATIONS[url]
    # Every datapoint answers, the hot water ones of the circuits without hot water too
    return {"value": "0"}


async def test_only_a_circuit_configured_with_hot_water_has_hot_water_entities(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    heater.fetch = AsyncMock(side_effect=configured)
    client.fetch_all.return_value = await heater.fetch_all()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for circuit in ("radiators", "floor"):
        assert hass.states.get(f"binary_sensor.{circuit}_hot_water_charging_pump") is None
        assert hass.states.get(f"sensor.{circuit}_hot_water_temperature") is None
        assert hass.states.get(f"sensor.{circuit}_hot_water_target_temperature") is None
    assert hass.states.get("binary_sensor.hot_water_hot_water_charging_pump").state == "off"
    assert hass.states.get("sensor.hot_water_hot_water_temperature").state == "0.0"
    # The other values of the circuits without hot water are kept
    assert hass.states.get("sensor.radiators_flow_temperature") is not None


async def test_a_circuit_configuration_is_read_once_at_discovery(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    heater.fetch = AsyncMock(side_effect=configured)

    for _ in range(3):
        await heater.fetch_all()

    requested = [call.args[0] for call in heater.fetch.await_args_list]
    assert sorted(url for url in requested if url.endswith("/103")) == sorted(CONFIGURATIONS)


async def test_a_circuit_whose_configuration_cannot_be_read_keeps_the_hot_water_that_answers(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    heater = WindhagerHttpClient("192.0.2.1", "secret")

    def unreadable(url: str) -> list | dict:
        # The configuration times out; a level the module does not have answers a 409
        if url == "/1/15/0/103":
            raise TimeoutError()
        if url == "/1/15/1/103":
            return {"code": 409, "message": "Conflict"}
        return answer(url)

    heater.fetch = AsyncMock(side_effect=unreadable)
    client.fetch_all.return_value = await heater.fetch_all()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.boiler_fbh_hot_water_temperature").state == "52.7"
    assert hass.states.get("sensor.radiatoren_hot_water_temperature") is None


async def test_a_heater_lost_while_reading_a_circuit_configuration_fails_the_poll() -> None:
    heater = WindhagerHttpClient("192.0.2.1", "secret")

    def lost(url: str) -> list | dict:
        if url.endswith("/103"):
            raise CannotConnect("gone")
        return configured(url)

    heater.fetch = AsyncMock(side_effect=lost)

    # As a datapoint's request would: the coordinator makes the entities unavailable
    with pytest.raises(CannotConnect):
        await heater.fetch_all()
