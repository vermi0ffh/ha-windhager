"""The diagnostics: the entry, the coordinator's data and a full scan of the API."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
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


async def test_the_diagnostics_hold_the_data_and_the_scan_without_the_credentials(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.fetch_all.return_value = {"devices": [], "oids": {"/1/15/0/0/45/0": "612.3"}}
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    with patch.object(diagnostics, "WindhagerHttpClient") as scan_client_class:
        scan_client = scan_client_class.return_value
        scan_client.scan = AsyncMock(return_value={"devices": [{"nodeId": 15}], "errors": {}})
        scan_client.close = AsyncMock()
        result = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert result == {
        "entry": {"host": "**REDACTED**", "password": "**REDACTED**"},
        "coordinator_data": {"devices": [], "oids": {"/1/15/0/0/45/0": "612.3"}},
        "scan": {"devices": [{"nodeId": 15}], "errors": {}},
    }
    scan_client_class.assert_called_once_with("192.0.2.1", "secret")
    scan_client.close.assert_awaited_once()
