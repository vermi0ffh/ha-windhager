"""The entities are named "<device> <entity>", the entity's part translated."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.client import WindhagerHttpClient

# A heater module and a heating circuit module, as /1 lists them (fake Neuron IDs)
MODULES = [
    {"nodeId": 15, "neuronId": "0a0000000015", "functions": [{"fctId": 0, "fctType": 14, "lock": False, "name": "Circuit"}]},
    {"nodeId": 60, "neuronId": "0a0000000060", "functions": [{"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN"}]},
]


async def heater_data() -> dict:
    """What the client returns for these modules, every datapoint reading 1."""
    client = WindhagerHttpClient("192.0.2.1", "secret")
    client.fetch = AsyncMock(side_effect=lambda url: MODULES if url == "/1" else {"value": "1"})
    return await client.fetch_all()


async def set_up(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str) -> dict:
    hass.config.language = language
    data = await heater_data()
    client.fetch_all.return_value = data
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return data


async def test_a_new_english_installation_gets_the_entity_ids_of_the_former_names(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    data = await set_up(hass, entry, client, "en")

    # The names the client gave the entities before they were translated made these ids
    expected = {
        f"{'climate' if device['type'] == 'climate' else 'sensor'}.{slugify(device['name'])}"
        for device in data["devices"]
    } | {"climate.circuit_without_bias"}

    # The registry: an entity disabled by default has no state
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert {entity.entity_id for entity in entities} == expected


async def test_the_names_are_translated_after_their_device(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client, "fr")

    names = {state.entity_id: state.name for state in hass.states.async_all()}

    # Home Assistant makes a new entity's id from its name in the instance's language
    assert names["sensor.biowin_etat_de_la_chaudiere"] == "BioWIN État de la chaudière"
    assert names["sensor.circuit_temperature_exterieure"] == "Circuit Température extérieure"
    assert names["climate.circuit"] == "Circuit"
    assert names["climate.circuit_sans_biais"] == "Circuit Sans biais"


@pytest.mark.parametrize("language", ["en", "fr", "de"])
async def test_every_entity_has_a_name_of_its_own(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str
) -> None:
    await set_up(hass, entry, client, language)

    names = [state.name for state in hass.states.async_all() if state.entity_id != "climate.circuit"]

    assert len(set(names)) == len(names)
    assert all(name not in ("BioWIN", "Circuit") for name in names)
