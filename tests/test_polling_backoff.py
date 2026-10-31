"""A heater that does not answer is polled less often, and as usual again once it answers."""

from datetime import timedelta
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.windhager.exceptions import CannotConnect

STATUS_OID = "/1/15/0/2/1/0"
DATA = {
    "devices": [
        {
            "id": "heater_status",
            "key": "heater_status",
            "type": "select",
            "oid": STATUS_OID,
            "device_id": "biowin",
            "device_name": "BioWIN",
        }
    ],
    "oids": {STATUS_OID: "3"},
}


async def set_up(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock):
    client.fetch_all.return_value = DATA
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_each_failed_poll_doubles_the_wait_up_to_five_minutes(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    coordinator = await set_up(hass, entry, client)

    client.fetch_all.side_effect = CannotConnect("no answer")
    waits = []
    for _ in range(4):
        await coordinator.async_refresh()
        waits.append(coordinator.update_interval.total_seconds())

    assert waits == [120, 240, 300, 300]


async def test_the_usual_interval_comes_back_once_the_heater_answers(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    coordinator = await set_up(hass, entry, client)
    client.fetch_all.side_effect = CannotConnect("no answer")
    await coordinator.async_refresh()
    await coordinator.async_refresh()

    client.fetch_all.side_effect = None
    await coordinator.async_refresh()

    assert coordinator.update_interval == timedelta(seconds=60)
    assert hass.states.get("sensor.biowin_heater_status").state == "3"


async def test_a_timeout_that_keeps_the_values_also_waits_longer(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    coordinator = await set_up(hass, entry, client)

    client.fetch_all.side_effect = TimeoutError
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.update_interval == timedelta(seconds=120)
    assert hass.states.get("sensor.biowin_heater_status").state == "3"


async def test_no_request_reaches_the_heater_before_the_longer_wait(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    coordinator = await set_up(hass, entry, client)
    client.fetch_all.side_effect = CannotConnect("no answer")
    await coordinator.async_refresh()
    start = dt_util.utcnow()
    polls = client.fetch_all.await_count

    async_fire_time_changed(hass, start + timedelta(seconds=90))
    await hass.async_block_till_done()
    assert client.fetch_all.await_count == polls

    async_fire_time_changed(hass, start + timedelta(seconds=125))
    await hass.async_block_till_done()
    assert client.fetch_all.await_count == polls + 1
