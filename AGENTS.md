# AGENTS.md

Guidance for anyone — human or coding agent (Claude Code, Codex, …) — changing this repository. It holds the rules
every change respects; [README.md](README.md) is the user documentation. `CLAUDE.md` only points here.

## Overview

**Windhager Heater** is a [HACS](https://hacs.xyz/) custom integration that connects Home Assistant to Windhager
heaters (BioWIN 2, …) through the local HTTP API of their InfoWIN Touch. It polls the heater's values and offers
climates for the heating circuits; some of its users drive their heating with it.

## Layout

| Path | Content |
|------|---------|
| `custom_components/windhager/client.py` | The HTTP client of the heater's API (aiohttp, digest authentication): discovery of the devices, reads, writes (`update`), the diagnostics' scan |
| `custom_components/windhager/coordinator.py` | The coordinator polling the heater for every entity; `WindhagerConfigEntry`, the entry typed with it |
| `custom_components/windhager/entity.py` | `WindhagerEntity`, the base of the climates and sensors (unique id, name, device) |
| `custom_components/windhager/__init__.py` | Setting up and unloading an entry; the services, registered once in `async_setup` |
| `custom_components/windhager/climate.py`, `sensor.py` | The platforms |
| `custom_components/windhager/config_flow.py` | Adding an entry: host and password, checked against the heater |
| `custom_components/windhager/diagnostics.py` | The diagnostics: the entry (redacted), the coordinator's data, the API scan in the background |
| `custom_components/windhager/quality_scale.yaml` | Each rule of the quality scale: done, exempt (with the reason) or to do |
| `custom_components/windhager/strings.json`, `translations/` | The texts, in English, French and German |
| `tests/` | pytest-homeassistant-custom-component; `conftest.py` mocks the client |
| `hacs.json` | HACS metadata, among them the minimum Home Assistant version |

## Commands

```bash
pip install -r requirements_test.txt   # the pinned Home Assistant of the tests (Python 3.14)
pytest                                 # the tests
pytest --cov=custom_components/windhager --cov-fail-under=95   # the coverage the CI requires (Gold)
ruff check custom_components tests     # what the CI checks
```

The CI (`.github/workflows/validate.yml`) also runs hassfest and the HACS validation.

## Rules

A change that must break one of these rules says so explicitly in its commit message and pull request, with the
reason.

### Home Assistant

1. **Target: Gold** of the [integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
   A change never loses a rule already met; a rule that does not apply is exempted with its reason.
   `quality_scale.yaml` holds each rule's status: a change that meets, loses or exempts one updates it.
2. **Home Assistant's conventions**: nothing blocking in the event loop (the heater is reached only through the
   asynchronous `client.py`); the entities read the coordinator's data, they do not request the heater themselves;
   services are registered in `async_setup`; user-facing texts go in `strings.json` and every file of
   `translations/`.
3. **Minimum Home Assistant version**: `hacs.json` says it. Use only what that version offers; raising it is the
   point of a change or announced in its pull request, and in the next release's notes.

### The heater

4. **No write to a real heater without its owner's explicit approval**, planned with them: no datapoint `PUT`
   (`client.update`), no service call, setpoint, preset or compensation. Reading a heater is fine. A heater may be
   heating a house: a wrong write can leave it off in winter or heating for nothing.
5. **A change that writes to the heater** (a new write, or a change to what or when it writes) is tested against
   the mocked client, then on a real heater only as rule 4 says. Its pull request lists the datapoints written and
   their values, the risk, and how to set them back.
6. **The heater's API is slow** and answers one request at a time (a full scan took 44 to 100 s on 2026-10-28 and 29
   for 63 requests): no parallel requests to it, and a new request on every poll is measured on a real heater
   before it is merged.

### Code and tests

7. **English** for identifiers, comments, log messages, commits and pull requests. **Ruff** passes with the CI's
   selection. Type hints on every new function.
8. **Comments explain why**; a value taken from an observation cites it (date and measure, e.g. "about 100 s for
   63 requests on 2026-10-28").
9. **Every behavior change comes with a test**; a bug fix comes with a test that fails without the fix.
10. **Tests never reach a heater**: the client is mocked (the `client` fixture) or talks to a local server on
    127.0.0.1. Test data uses documentation addresses (`192.0.2.x`) and fake passwords.
11. **Tests check observable behavior** through Home Assistant (states, services, flows, diagnostics), not private
    members. A changed or removed test is justified in the commit message and pull request: never weaken or delete
    a test just to make it pass. A refactoring commit does not touch the tests: unchanged tests passing are what
    proves the behavior is kept.

### Compatibility

12. **What users rely on keeps working**: an entity keeps its unique id (or its history is lost), its states'
    meaning and its unit; an entry created by an older version still loads (a change to its data comes with a
    version bump and `async_migrate_entry`). A breaking change is the point of its pull request, says so in its
    title and description, and is announced in the release notes.

### Git, privacy and security

13. **No secret or personal data in the repository**: no password, token, real heater address or unredacted
    diagnostics file. The diagnostics redact the host and the password.
14. **One topic per pull request** (they are squash-merged): the title and the commit messages are an English
    `Summary` with no prefix, the body explains why and what with the measured facts. The README changes in the
    same pull request as the behavior it describes.
15. **Agents**: commit only when asked, push only when asked, never change the git configuration, never rewrite
    published history, no tool attribution in commits or pull requests (no `Co-Authored-By:` for the agent, no
    "Generated with …", no session link). A person who co-wrote a change is credited with `Co-authored-by:`.
