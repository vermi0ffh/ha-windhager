"""The diagnostics: the entry, the coordinator's data and a full scan of the API."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.windhager import diagnostics
from custom_components.windhager.client import WindhagerHttpClient

# The API's lookup tree: devices, their functions, a function's sensors, a sensor's readings
API = {
    "/1": [
        {
            "nodeId": 15,
            "name": "BioWIN",
            "functions": [
                {"fctId": 0, "fctType": 9, "name": "Kessel"},
                {"fctId": 1, "fctType": -1, "name": "Unused"},
            ],
        },
        {"nodeId": 16, "name": "No function"},
    ],
    "/1/15/0": [{"id": 0, "count": 2}, {"id": 2, "count": 1}],
    "/1/15/0/0": [{"OID": "/1/15/0/0/45/0", "name": "00-045", "value": "612.3"}],
}


async def answer(url: str) -> list:
    """The heater: the lookup tree, an error for any other URL."""
    if url not in API:
        raise TimeoutError
    return API[url]


async def test_the_scan_walks_every_device_function_and_sensor() -> None:
    client = WindhagerHttpClient("192.0.2.1", "secret")

    with patch.object(client, "fetch", AsyncMock(side_effect=answer)) as fetch:
        scan = await client.scan()

    [biowin, no_function] = scan["devices"]
    [heater, unused] = biowin["functions"]
    assert heater["sensors"][0]["readings"] == API["/1/15/0/0"]
    assert "sensors" not in unused
    assert "functions" not in no_function
    # The failed request is recorded, the scan went on
    assert heater["sensors"][1]["readings"] == []
    assert scan["errors"] == {"/1/15/0/2": "TimeoutError()"}
    assert "/1/15/1" not in [call.args[0] for call in fetch.await_args_list]


async def test_the_first_download_starts_the_scan_the_next_one_holds_it(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.fetch_all.return_value = {"devices": [], "oids": {"/1/15/0/0/45/0": "612.3"}}
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # The scan lasts until the first download is served, as a real one (about 100 s on 2026-10-28)
    first_served = asyncio.Event()

    async def scan() -> dict:
        await first_served.wait()
        return {"devices": [{"nodeId": 15}], "errors": {}}

    with patch.object(diagnostics, "WindhagerHttpClient") as scan_client_class:
        scan_client = scan_client_class.return_value
        scan_client.scan = AsyncMock(side_effect=scan)
        scan_client.close = AsyncMock()
        first = await get_diagnostics_for_config_entry(hass, hass_client, entry)
        first_served.set()
        await hass.async_block_till_done(wait_background_tasks=True)
        second = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert first["entry"] == second["entry"] == {"host": "**REDACTED**", "password": "**REDACTED**"}
    assert first["coordinator_data"] == {"devices": [], "oids": {"/1/15/0/0/45/0": "612.3"}}
    assert first["scan"]["status"] == "running"
    assert second["scan"]["status"] == "done"
    assert second["scan"]["devices"] == [{"nodeId": 15}]
    assert second["scan"]["errors"] == {}
    # One scan, with the entry's credentials, its client closed
    scan_client_class.assert_called_once_with("192.0.2.1", "secret")
    scan_client.scan.assert_awaited_once()
    scan_client.close.assert_awaited_once()


async def test_the_heater_mac_address_is_redacted(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, client: MagicMock
) -> None:
    # An entry found by discovery holds the InfoWIN Touch's MAC address (a fake one here):
    # it identifies the heater, as its host does
    entry = MockConfigEntry(
        domain="windhager", data={"host": "192.0.2.1", "password": "secret", "mac": "00:23:43:00:00:01"}
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch.object(diagnostics, "WindhagerHttpClient") as scan_client_class:
        scan_client = scan_client_class.return_value
        scan_client.scan = AsyncMock(return_value={"devices": [], "errors": {}})
        scan_client.close = AsyncMock()
        result = await get_diagnostics_for_config_entry(hass, hass_client, entry)
        await hass.async_block_till_done(wait_background_tasks=True)

    assert result["entry"] == {"host": "**REDACTED**", "password": "**REDACTED**", "mac": "**REDACTED**"}


async def test_the_modules_chip_ids_are_redacted_everywhere(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, entry: MockConfigEntry, client: MagicMock
) -> None:
    # Two modules (fake chip IDs): the heater's ID starts every unique id, each module's is
    # its device's serial number, and the scan lists both
    heater, circuit = "0a0000000060", "0a0000000015"
    client.fetch_all.return_value = {
        "heater_id": heater,
        "devices": [
            {
                "id": f"{heater}-1-60-0-0-7-0",
                "key": "heater_temperature",
                "type": "temperature",
                "oid": "/1/60/0/0/7/0",
                "device_id": f"{heater}60",
                "device_name": "BioWIN",
                "device_serial_number": heater,
            },
            {
                "id": f"{heater}-1-15-0-0-1-0",
                "key": "current_temperature_real",
                "type": "temperature",
                "oid": "/1/15/0/0/1/0",
                "device_id": f"{heater}15",
                "device_name": "Circuit",
                "device_serial_number": circuit,
            },
        ],
        "oids": {"/1/60/0/0/7/0": "40.5", "/1/15/0/0/1/0": "22.0"},
    }
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch.object(diagnostics, "WindhagerHttpClient") as scan_client_class:
        scan_client = scan_client_class.return_value
        scan_client.scan = AsyncMock(
            return_value={
                "devices": [{"nodeId": 60, "neuronId": heater}, {"nodeId": 15, "neuronId": circuit}],
                # A mapping keyed by an id holding a chip ID: its keys are redacted too
                "errors": {f"{heater}-1-60": "TimeoutError()"},
            }
        )
        scan_client.close = AsyncMock()
        await get_diagnostics_for_config_entry(hass, hass_client, entry)
        await hass.async_block_till_done(wait_background_tasks=True)
        result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert heater not in str(result)
    assert circuit not in str(result)
    # Each chip ID has a placeholder of its own: which entity belongs to which module stays readable
    data = result["coordinator_data"]
    assert data["heater_id"] == "**REDACTED_1**"
    assert [device["device_serial_number"] for device in data["devices"]] == ["**REDACTED_1**", "**REDACTED_2**"]
    assert data["devices"][1]["id"] == "**REDACTED_1**-1-15-0-0-1-0"
    assert [device["neuronId"] for device in result["scan"]["devices"]] == ["**REDACTED_1**", "**REDACTED_2**"]
    assert result["scan"]["errors"] == {"**REDACTED_1**-1-60": "TimeoutError()"}
    # Only the diagnostics are redacted: the entities keep their unique ids, and their values
    assert er.async_get(hass).async_get("sensor.biowin_heater_temperature").unique_id == f"{heater}-1-60-0-0-7-0"
    assert hass.states.get("sensor.biowin_heater_temperature").state == "40.5"


async def test_a_scan_that_fails_is_reported_done_with_its_error(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, entry: MockConfigEntry, client: MagicMock
) -> None:
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch.object(diagnostics, "WindhagerHttpClient") as scan_client_class:
        scan_client = scan_client_class.return_value
        scan_client.scan = AsyncMock(side_effect=ValueError("unexpected answer"))
        scan_client.close = AsyncMock()
        await get_diagnostics_for_config_entry(hass, hass_client, entry)
        await hass.async_block_till_done(wait_background_tasks=True)
        result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert result["scan"]["status"] == "done"
    assert result["scan"]["error"] == "ValueError('unexpected answer')"
    scan_client.close.assert_awaited_once()


async def test_the_scan_is_labelled_in_the_instance_language(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, entry: MockConfigEntry, client: MagicMock
) -> None:
    hass.config.language = "fr"
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch.object(diagnostics, "WindhagerHttpClient") as scan_client_class:
        scan_client = scan_client_class.return_value
        scan_client.scan = AsyncMock(return_value={"devices": [], "errors": {}})
        scan_client.close = AsyncMock()
        await get_diagnostics_for_config_entry(hass, hass_client, entry)
        await hass.async_block_till_done(wait_background_tasks=True)

    # The heater's texts are read by the scan, at the download: not at setup
    scan_client.scan.assert_awaited_once_with("fr")
