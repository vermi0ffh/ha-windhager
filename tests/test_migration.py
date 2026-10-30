"""Entities and devices named after the host before are renamed after the heater, keeping their entity ids."""

from unittest.mock import MagicMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

HEATER_ID = "0a0000000060"
STATUS_OID = "/1/60/0/2/1/0"


def status(id_base: str) -> dict:
    """The heater status sensor as the client describes it, its ids starting with `id_base`."""
    return {
        "id": f"{id_base}-1-60-0-2-1-0",
        "name": "BioWIN Heater status",
        "type": "select",
        "oid": STATUS_OID,
        "device_id": f"{id_base}60",
        "device_name": "BioWIN",
    }


async def test_an_entity_named_after_the_host_keeps_its_entity_id_under_the_heater_id(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("windhager", "192-0-2-160")}, name="BioWIN"
    )
    old = entity_registry.async_get_or_create(
        "sensor",
        "windhager",
        "192-0-2-1-1-60-0-2-1-0",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="my_heater_status",
    )
    client.fetch_all.return_value = {"devices": [status(HEATER_ID)], "heater_id": HEATER_ID, "oids": {STATUS_OID: "3"}}

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    renamed = entity_registry.async_get(old.entity_id)
    assert renamed is not None and renamed.unique_id == f"{HEATER_ID}-1-60-0-2-1-0"
    assert hass.states.get(old.entity_id).state == "3"
    assert [entity.entity_id for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id)] == [
        old.entity_id
    ]
    assert device_registry.async_get(device.id).identifiers == {("windhager", f"{HEATER_ID}60")}


async def test_without_a_heater_id_the_entities_keep_the_host(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    entity_registry = er.async_get(hass)
    old = entity_registry.async_get_or_create("sensor", "windhager", "192-0-2-1-1-60-0-2-1-0", config_entry=entry)
    client.fetch_all.return_value = {"devices": [status("192-0-2-1")], "heater_id": None, "oids": {STATUS_OID: "3"}}

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(old.entity_id).unique_id == "192-0-2-1-1-60-0-2-1-0"


async def test_an_entity_id_another_entry_of_the_same_heater_took_first_stays_named_after_the_host(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    # The same heater added twice, before the entries were one per heater: the other
    # entry's entity was renamed first
    other = MockConfigEntry(domain="windhager", data={"host": "192.0.2.9", "password": "secret"})
    other.add_to_hass(hass)
    entity_registry = er.async_get(hass)
    entity_registry.async_get_or_create("sensor", "windhager", f"{HEATER_ID}-1-60-0-2-1-0", config_entry=other)
    old = entity_registry.async_get_or_create("sensor", "windhager", "192-0-2-1-1-60-0-2-1-0", config_entry=entry)
    client.fetch_all.return_value = {"devices": [status(HEATER_ID)], "heater_id": HEATER_ID, "oids": {STATUS_OID: "3"}}

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(old.entity_id).unique_id == "192-0-2-1-1-60-0-2-1-0"


async def test_a_device_whose_new_id_is_taken_leaves_its_entities_to_the_device_holding_it(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    taken = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("windhager", f"{HEATER_ID}60")}
    )
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("windhager", "192-0-2-160")}, name="BioWIN"
    )
    old = entity_registry.async_get_or_create(
        "sensor", "windhager", "192-0-2-1-1-60-0-2-1-0", config_entry=entry, device_id=device.id
    )
    client.fetch_all.return_value = {"devices": [status(HEATER_ID)], "heater_id": HEATER_ID, "oids": {STATUS_OID: "3"}}

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    renamed = entity_registry.async_get(old.entity_id)
    assert (renamed.unique_id, renamed.device_id) == (f"{HEATER_ID}-1-60-0-2-1-0", taken.id)
    assert hass.states.get(old.entity_id).state == "3"
    # Left without its entity, the device named after the host is removed
    assert device_registry.async_get(device.id) is None
