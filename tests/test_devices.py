"""One device per module of the heater, with its model and chip ID; the empty devices of before removed."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.client import WindhagerHttpClient

CIRCUIT_ID = "0a0000000015"
HEATER_ID = "0a0000000060"
# The modules as /1 lists them (fake Neuron IDs): a circuit module, the heater
MODULES = [
    {
        "nodeId": 15,
        "name": "UMUMLZ",
        "neuronId": CIRCUIT_ID,
        "functions": [{"fctId": 0, "fctType": 14, "lock": False, "name": "Circuit"}],
    },
    {
        "nodeId": 60,
        "name": "BioWIN 2",
        "neuronId": HEATER_ID,
        "functions": [{"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN"}],
    },
]


async def set_up(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    heater.fetch = AsyncMock(side_effect=lambda url: MODULES if url == "/1" else {"value": "1"})
    client.fetch_all.return_value = await heater.fetch_all()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def device_of(hass: HomeAssistant, entity_id: str) -> dr.DeviceEntry:
    entity = er.async_get(hass).async_get(entity_id)
    return dr.async_get(hass).async_get(entity.device_id)


async def test_a_circuit_climates_and_sensors_share_their_module_device(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    circuit = device_of(hass, "climate.circuit")

    assert device_of(hass, "climate.circuit_without_bias") == circuit
    assert device_of(hass, "sensor.circuit_outside_temperature") == circuit
    assert len(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)) == 2


async def test_a_device_shows_its_module_model_and_chip_id(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client)

    heater = device_of(hass, "sensor.biowin_heater_status")

    assert (heater.name, heater.manufacturer, heater.model) == ("BioWIN", "Windhager", "BioWIN 2")
    assert heater.serial_number == HEATER_ID
    assert heater.configuration_url == "http://192.0.2.1"
    assert device_of(hass, "climate.circuit").model == "UMUMLZ"


async def test_the_climates_device_of_before_is_removed_keeping_their_entity_ids(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    # The climate's own device, as a version before 2026-10-29 made it
    old_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("windhager", f"{HEATER_ID}-1-15")}, name="Circuit"
    )
    climate = entity_registry.async_get_or_create(
        "climate",
        "windhager",
        f"{HEATER_ID}-1-15",
        config_entry=entry,
        device_id=old_device.id,
        suggested_object_id="circuit",
    )

    await set_up(hass, entry, client)

    assert entity_registry.async_get(climate.entity_id).device_id == device_of(
        hass, "sensor.circuit_outside_temperature"
    ).id
    assert device_registry.async_get(old_device.id) is None


async def test_a_device_with_entities_stays_though_its_module_did_not_answer(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    absent = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("windhager", f"{HEATER_ID}90")}, name="Other module"
    )
    entity_registry.async_get_or_create(
        "sensor", "windhager", f"{HEATER_ID}-1-90-0-0-1-0", config_entry=entry, device_id=absent.id
    )

    await set_up(hass, entry, client)

    assert device_registry.async_get(absent.id) is not None
