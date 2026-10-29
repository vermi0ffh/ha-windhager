"""The climates and their temperature compensation service."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

# A heating circuit as the client describes it: its function's values under its prefix
CIRCUIT = {
    "id": "circuit",
    "name": "Heating circuit",
    "type": "climate",
    "prefix": "/1/15/0",
    "device_id": "circuit",
    "device_name": "Heating circuit",
}
OIDS = {
    "/1/15/0/0/0/1/0": "20.5",
    "/1/15/0/0/1/1/0": "21.0",
    "/1/15/0/0/3/50/0": "1",
    "/1/15/0/0/2/10/0": "0",
    "/1/15/0/0/3/58/0": "0.5",
}


async def set_up_circuit(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock) -> None:
    client.fetch_all.return_value = {"devices": [CIRCUIT], "oids": OIDS}
    client.update = AsyncMock()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_a_circuit_has_a_climate_with_its_bias_removed_and_one_without(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_circuit(hass, entry, client)

    temperatures = {
        state.entity_id: state.attributes["current_temperature"] for state in hass.states.async_all("climate")
    }

    assert temperatures == {"climate.heating_circuit": 20.0, "climate.heating_circuit_without_bias": 20.5}


async def test_the_compensation_service_writes_the_circuit_bias(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up_circuit(hass, entry, client)

    await hass.services.async_call(
        "windhager",
        "set_current_temp_compensation",
        {"entity_id": "climate.heating_circuit", "compensation": -1.5},
        blocking=True,
    )

    client.update.assert_awaited_once_with("/1/15/0/0/3/58/0", "-1.5")
