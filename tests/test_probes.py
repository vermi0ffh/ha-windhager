"""The heater's suction probes: each one's state, and how many are empty."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.windhager.client import PROBES, SLOW_VALUES_POLLS, WindhagerHttpClient

# A heater module (fake Neuron ID)
MODULES = [
    {
        "nodeId": 60,
        "name": "BioWIN 2",
        "neuronId": "0a0000000060",
        "functions": [{"fctId": 0, "fctType": 9, "lock": False, "name": "BioWIN"}],
    },
]
HEATER = "/1/60/0"
# A BioWIN 2 with eight probes on 2026-11-02: probe 6 empty, the others on
EIGHT_PROBES = {f"{HEATER}{path}": "2" if number == 6 else "1" for number, path in enumerate(PROBES, 1)}


def answering(probes: dict[str, object]):
    """The heater: its modules, the probes' answers (an exception is raised), "1" for the rest."""

    async def fetch(url: str) -> object:
        if url == "/1":
            return MODULES
        answer = probes.get(url, {"value": "1"})
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, dict) else {"value": answer}

    return fetch


async def set_up(hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, probes: dict) -> WindhagerHttpClient:
    heater = WindhagerHttpClient("192.0.2.1", "secret")
    heater.fetch = AsyncMock(side_effect=answering(probes))
    client.fetch_all.return_value = await heater.fetch_all()
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return heater


async def test_each_probe_shows_its_state_and_the_empty_ones_are_counted(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    await set_up(hass, entry, client, EIGHT_PROBES)

    assert hass.states.get("sensor.biowin_probe_1").state == "1"
    sixth = hass.states.get("sensor.biowin_probe_6")
    assert (sixth.state, sixth.attributes["device_class"]) == ("2", "enum")
    assert sixth.attributes["options"] == ["0", "1", "2"]
    empty = hass.states.get("sensor.biowin_empty_probes")
    assert (empty.state, empty.attributes["state_class"]) == ("1", "measurement")
    # Diagnostics: the count is the entity to watch
    registry = er.async_get(hass)
    assert registry.async_get("sensor.biowin_probe_6").entity_category == "diagnostic"
    assert registry.async_get("sensor.biowin_empty_probes").entity_category is None


async def test_a_probe_switched_off_is_not_empty(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    # 2026-11-02: probes 7 and 8 switched off on the heater's screen read 0 at once
    probes = {**EIGHT_PROBES, f"{HEATER}{PROBES[6]}": "0", f"{HEATER}{PROBES[7]}": "0"}

    await set_up(hass, entry, client, probes)

    assert hass.states.get("sensor.biowin_probe_7").state == "0"
    assert hass.states.get("sensor.biowin_empty_probes").state == "1"


async def test_only_the_probes_the_heater_has_get_entities(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    # Three probes; the others answer without a value, or with a 409's JSON body
    probes = {f"{HEATER}{path}": "1" for path in PROBES[:3]}
    probes |= {f"{HEATER}{path}": "-.-" for path in PROBES[3:6]}
    probes |= {f"{HEATER}{path}": {"code": 409, "message": "Conflict"} for path in PROBES[6:]}

    await set_up(hass, entry, client, probes)

    assert hass.states.get("sensor.biowin_probe_3") is not None
    assert hass.states.get("sensor.biowin_probe_4") is None
    assert hass.states.get("sensor.biowin_probe_7") is None
    assert hass.states.get("sensor.biowin_empty_probes").state == "0"


async def test_a_heater_without_probes_has_no_probe_entities(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    # A hand-filled container: the probes are not listed (2026-10-31)
    await set_up(hass, entry, client, {f"{HEATER}{path}": {"code": 409} for path in PROBES})

    assert not [state for state in hass.states.async_all("sensor") if "probe" in state.entity_id]


async def test_a_probe_whose_request_failed_is_kept(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    # A timeout at discovery must not take a store's probe away
    probes = {**EIGHT_PROBES, f"{HEATER}{PROBES[1]}": TimeoutError()}

    heater = await set_up(hass, entry, client, probes)

    assert f"{HEATER}{PROBES[1]}" in heater.slow_oids


async def test_the_probes_are_read_every_ten_polls(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    heater = await set_up(hass, entry, client, EIGHT_PROBES)

    for _ in range(SLOW_VALUES_POLLS):
        await heater.fetch_all()

    requested = [call.args[0] for call in heater.fetch.await_args_list]
    # Once at discovery, then with the first poll and the eleventh
    assert requested.count(f"{HEATER}{PROBES[5]}") == 3


@pytest.mark.parametrize(
    ("language", "name", "empty", "count"),
    [("en", "Probe {number}", "Empty", "Empty probes"), ("de", "Sonde {number}", "Leer", "Leere Sonden"), ("fr", "Sonde {number}", "Vide", "Sondes vides")],
)
async def test_the_probes_are_translated(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, language: str, name: str, empty: str, count: str
) -> None:
    await set_up(hass, entry, client, EIGHT_PROBES)

    translations = await async_get_translations(hass, language, "entity", ["windhager"])

    assert translations["component.windhager.entity.sensor.probe.name"] == name
    assert translations["component.windhager.entity.sensor.probe.state.2"] == empty
    assert translations["component.windhager.entity.sensor.empty_probes.name"] == count
