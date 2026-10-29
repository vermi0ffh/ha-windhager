"""Adding an entry, and giving a new password when the heater refuses the old one."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager import config_flow
from custom_components.windhager.exceptions import InvalidAuth

HEATER_MODULE = {"nodeId": 60, "neuronId": "0a0000000060", "functions": [{"fctId": 0, "fctType": 9}]}


@pytest.fixture
def flow_client() -> Iterator[MagicMock]:
    """The client the flow checks the heater with: it answers."""
    with patch.object(config_flow, "WindhagerHttpClient") as client_class:
        client = client_class.return_value
        client.fetch = AsyncMock(return_value=[])
        client.close = AsyncMock()
        yield client


async def add_heater(hass: HomeAssistant, password: str) -> dict:
    result = await hass.config_entries.flow.async_init("windhager", context={"source": SOURCE_USER})
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "http://192.0.2.1/", "password": password}
    )


async def test_a_heater_answering_is_added_with_its_cleaned_host(
    hass: HomeAssistant, flow_client: MagicMock, client: MagicMock
) -> None:
    result = await add_heater(hass, "secret")

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"host": "192.0.2.1", "password": "secret"}


async def test_a_heater_is_added_once_whatever_its_host(
    hass: HomeAssistant, flow_client: MagicMock, client: MagicMock
) -> None:
    flow_client.fetch.return_value = [HEATER_MODULE]
    MockConfigEntry(domain="windhager", unique_id="0a0000000060", data={"host": "192.0.2.9"}).add_to_hass(hass)

    result = await add_heater(hass, "secret")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_a_new_heater_is_added_with_its_neuron_id(
    hass: HomeAssistant, flow_client: MagicMock, client: MagicMock
) -> None:
    flow_client.fetch.return_value = [HEATER_MODULE]

    result = await add_heater(hass, "secret")

    assert result["result"].unique_id == "0a0000000060"


@pytest.mark.parametrize(
    ("error", "expected"), [(InvalidAuth("refused"), "invalid_auth"), (TimeoutError(), "cannot_connect")]
)
async def test_a_heater_failing_the_check_is_not_added(
    hass: HomeAssistant, flow_client: MagicMock, error: Exception, expected: str
) -> None:
    flow_client.fetch.side_effect = error

    result = await add_heater(hass, "wrong")

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    flow_client.close.assert_awaited_once()


async def test_a_refused_password_asks_for_the_new_one_and_reloads_with_it(
    hass: HomeAssistant, entry: MockConfigEntry, flow_client: MagicMock, client: MagicMock
) -> None:
    client.fetch_all.side_effect = InvalidAuth("refused")
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    [flow] = hass.config_entries.flow.async_progress_by_handler("windhager")
    assert flow["context"]["source"] == "reauth"

    client.fetch_all.side_effect = None
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"password": "new-secret"})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {"host": "192.0.2.1", "password": "new-secret"}
    assert entry.state is ConfigEntryState.LOADED


async def test_a_new_password_also_refused_keeps_asking(
    hass: HomeAssistant, entry: MockConfigEntry, flow_client: MagicMock
) -> None:
    flow_client.fetch.side_effect = InvalidAuth("refused")
    result = await entry.start_reauth_flow(hass)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"password": "still-wrong"})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data["password"] == "secret"


async def reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    result = await entry.start_reconfigure_flow(hass)
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.0.2.2", "password": "new-secret"}
    )


async def test_the_heater_at_a_new_host_is_reconfigured_in_place(
    hass: HomeAssistant, flow_client: MagicMock, client: MagicMock
) -> None:
    entry = MockConfigEntry(domain="windhager", unique_id="0a0000000060", data={"host": "192.0.2.1", "password": "secret"})
    entry.add_to_hass(hass)
    flow_client.fetch.return_value = [HEATER_MODULE]

    result = await reconfigure(hass, entry)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {"host": "192.0.2.2", "password": "new-secret"}
    assert entry.title == "Windhager Heater (192.0.2.2)"


async def test_another_heater_at_the_new_host_is_refused(
    hass: HomeAssistant, flow_client: MagicMock, client: MagicMock
) -> None:
    entry = MockConfigEntry(domain="windhager", unique_id="0a0000000061", data={"host": "192.0.2.1", "password": "secret"})
    entry.add_to_hass(hass)
    flow_client.fetch.return_value = [HEATER_MODULE]

    result = await reconfigure(hass, entry)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_heater"
    assert entry.data == {"host": "192.0.2.1", "password": "secret"}
