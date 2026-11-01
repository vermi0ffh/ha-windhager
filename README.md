# Windhager Heater

A custom integration for [Home Assistant](https://www.home-assistant.io/) that reads Windhager pellet heaters through
their InfoWIN Touch on your local network. It shows the heater's temperatures, status and pellet consumption, and gives
each heating circuit a thermostat to follow it and change its target temperature or program.

The integration talks only to the InfoWIN Touch, with no cloud. It polls the heater's readings every minute.

## Use cases

- Follow the heater in Home Assistant: room, outside, boiler and fumes temperatures; what the burner is doing; the
  pellets burnt; the hours left until the next cleaning.
- Change a circuit's target temperature or program from a dashboard, a voice assistant or an automation, for example
  holidays while you are away.
- Get notified when the heater stops on a fault (burner or boiler blocked), when the pellets burnt reach a threshold,
  or when a cleaning is due.

## Supported devices

| Device                                                                                  | Status | Notes                              |
| --------------------------------------------------------------------------------------- | :----: | ---------------------------------- |
| [BioWIN2](https://www.windhager.com/en/products/pellet-heating-systems/biowin2-3-33kw/) |   ✅   | Infowin Touch (1.0.2), API (1.0.0) |

The integration reads the modules that the InfoWIN Touch lists: a heater module (BioWIN) and the heating circuits (a
UMUMLZ module, for instance). Other Windhager heaters behind an InfoWIN Touch may work if their modules expose the
same functions. The diagnostics (see [Troubleshooting](#troubleshooting)) show what yours exposes.

## Installation using HACS

The integration requires Home Assistant 2025.10 or later.

1. Install [HACS](https://hacs.xyz/)
2. Add this repository as a custom repository in HACS by clicking on the three dots in the top right corner and selecting "Custom repository".
3. Enter the following as the repository URL and select "Integration" as the type:

```
https://github.com/vermi0ffh/ha-windhager
```

4. Search for "Windhager Heater" and download it.
5. Restart Home Assistant.

## Installation using manual method

1. Download the repository as a zip file from [here](https://github.com/vermi0ffh/ha-windhager/archive/refs/heads/main.zip).
2. Extract the zip file.
3. Copy the `custom_components/windhager` folder from the extracted files to the `custom_components` folder in your Home Assistant configuration directory.
4. Restart Home Assistant.

## Configuration

Add the integration from *Settings → Devices & services → Add integration → Windhager Heater* and fill in:

| Parameter | Description |
| --------- | ----------- |
| Host      | The address of the heater's InfoWIN Touch on your network: its IP address, or its host name (`mb6620` if your router resolves it). |
| Password  | The password of the InfoWIN Touch's web access, not the one of your Windhager Connect account or the mobile app. The integration logs in as `USER`. |

The integration has no other options.

Home Assistant can also find the InfoWIN Touch on the network by zeroconf or DHCP, under the name `mb6620`. Accept
the discovered *Windhager Heater* and enter its password.

- An entry created from a discovery follows its heater by MAC address: if the heater gets a new address, the entry
  updates itself.
- An entry added by hand learns the heater's MAC the first time the heater is discovered at the entry's address.

If the heater's password changes, Home Assistant stops polling it and shows a *Re-authentication required* notice.
Enter the new password there.

If the heater gets a new address and the entry did not update itself, open the entry's menu, choose *Reconfigure* and
enter the new address. As long as it is the same heater, its entities and their history are kept.

## Data updates

The integration polls the heater every 60 seconds. The InfoWIN Touch answers slowly and handles one request at a
time, so the integration sends its requests one after the other. A change made on the heater shows in Home Assistant
at the next poll. A change made from Home Assistant triggers a poll right after it.

While the heater does not answer, the integration polls it less often, so that an InfoWIN Touch that restarts or is
busy gets time to recover: it waits twice as long after each failed poll, up to five minutes, and polls every minute
again as soon as the heater answers.

The readings that change over hours or days are read every ten minutes instead, which keeps each poll short: the
pellet consumption and the running times until cleaning. They keep their last value in between.
A reading whose request failed (a timeout, a connection error) is read again with the next poll, until it answers.

When the integration starts, it also reads the heater's texts for its error codes once, from the InfoWIN Touch's web
page.

Every ten minutes, the integration also lists the heater's modules again. A module added to the heater, such as a new
heating circuit, gets its device and entities within ten minutes, without a reload.

## Devices and entities

Each module of the heater is a device: the heater itself, and each heating circuit. A module that holds two heating
circuits (an UMUMLZ, for example) gives each its own device, named after the circuit. A device shows its model, its
chip ID as the serial number, and a link to the InfoWIN Touch's web page.

A module removed from the heater keeps its device and entities, which become unavailable: the integration cannot tell
a removed module from one that did not answer. To remove them, open the device and choose *Delete* in its menu. Only
the device of a module the heater no longer lists can be deleted.

The entities are named after their device, for example "BioWIN Heater status". The names follow Home Assistant's
language: English, French or German. A new installation also gets its entity ids in that language (for example
`sensor.biowin_etat_de_la_chaudiere` in French). Entity ids that already exist are kept.

Each heating circuit has these entities:

| Entity | Description |
| ------ | ----------- |
| Climate (named after the circuit) | The circuit's thermostat. It shows the room and target temperatures minus the comfort temperature correction, and the circuit's program as its preset. |
| Climate *Without bias* | The same thermostat, showing the temperatures as the heater reads them, without the correction. |
| Current temperature, Current temperature real | The room temperature, with and without the comfort temperature correction. |
| Target temperature | The temperature the circuit is heating to. |
| Outside temperature | The outside sensor's temperature. |
| Comfort temperature correction, Current temperature correction | The corrections set on the heater, in K. |
| Flow temperature, Flow target temperature | The water sent to the circuit, and its target (0 °C while the circuit does not heat). |
| Boiler temperature, Boiler target temperature | The water the circuit draws from, the heater's or the buffer's, and its target. |
| Operating mode | What the circuit does, in the heater's own words: heating, setback, hot water charging, standby at the heating limit, frost protection… |
| Circuit pump | On while the circuit's pump runs. |
| Hot water temperature, Hot water target temperature | The hot water tank's temperature and target, for a circuit that also heats the hot water. |
| Hot water charging pump | On while the pump charging the hot water tank runs. |

A circuit has hot water entities only if it is configured with hot water on the heater: its *DHW circuit* setting,
read when the integration starts and when the modules change. If that setting cannot be read, they are kept only if
the heater gives them a value.

The heater has these entities:

| Entity | Description |
| ------ | ----------- |
| Heater status | What the burner is doing: standby, ignition phase, modulating mode, burner blocked… |
| Operating mode | Whether the heater is on or switched off on its screen, or in manual mode, chimney sweep function or actuator test. Home Assistant cannot change it: the heater is switched on and off on its own screen. |
| Power factor | The burner's output, in %. |
| Heater temperature, Fumes temperature, Combustion chamber temperature | The heater's temperatures. |
| Hopper level | The pellets left in the heater's hopper, in %: the level the heater's mobile app shows. |
| Pellet consumption, Total pellet consumption | The pellets burnt, in tonnes: since the last reset, and in total. |
| Running time until stage 1 cleaning, Running time until stage 2 cleaning | The burner hours left until each cleaning. |
| Heater error | The heater's current error: its code and the heater's own text for it (for example "42: Suction turbine relay defective"), or *No error*. The text is in Home Assistant's language when the heater has it, else in English or German. The code alone is in the `code` attribute. |
| Heater problem | On while the heater reports an error. |

These entities are diagnostics: the two temperature corrections, Current temperature real, the two running times
until cleaning, Heater error and Heater problem. The two corrections are disabled on a new installation. To follow them, enable them in the entity's
settings.

### Thermostat

The presets are the circuit's programs:

- *Standby*;
- *Heating program 1*, *2* and *3*;
- *Day mode* and *Night mode*;
- *Holidays*;
- *Manual*, shown while a temporary target temperature is running.

Setting a target temperature makes it a temporary target for 400 minutes (6 h 40). After that, the circuit goes back
to its program. Choosing a preset ends a temporary target.

The thermostat shows *Off* while the heater is switched off on its screen (its *Operating mode* is *Switched off* or
*Shutting down*), and *Heat* otherwise. Home Assistant cannot switch the heater on or off: the heater is switched on
and off on its own screen, so the thermostat offers no other mode. To stop a circuit, choose its *Standby* preset.

## Actions

### `windhager.set_current_temp_compensation`

Sets a circuit's comfort temperature correction: the difference between the room temperature the heater reads and the
temperature the main climate shows.

| Field | Description |
| ----- | ----------- |
| `compensation` | Required. The correction in K, from -3.5 to 3.5, in steps of 0.1. |

The action targets either of the circuit's climates: both write the circuit's correction.

## Examples

Switch to holidays when the house has been empty for a day, and back to the circuit's program when someone comes
home:

```yaml
automation:
  - alias: "Heating on holidays while away"
    triggers:
      - trigger: state
        entity_id: zone.home
        to: "0"
        for: "24:00:00"
    actions:
      - action: climate.set_preset_mode
        target:
          entity_id: climate.circuit
        data:
          preset_mode: "6"  # Holidays
  - alias: "Heating back to its program"
    triggers:
      - trigger: numeric_state
        entity_id: zone.home
        above: 0
    actions:
      - action: climate.set_preset_mode
        target:
          entity_id: climate.circuit
        data:
          preset_mode: "1"  # Heating program 1
```

Send a notification when the heater reports an error, with the heater's text for it:

```yaml
automation:
  - alias: "Heater error"
    triggers:
      - trigger: state
        entity_id: binary_sensor.biowin_heater_problem
        to: "on"
    actions:
      - action: notify.notify
        data:
          message: "Heater error {{ states('sensor.biowin_heater_error') }}"
```

Or when it stops on a fault, from its status:

```yaml
automation:
  - alias: "Heater blocked"
    triggers:
      - trigger: state
        entity_id: sensor.biowin_heater_status
        to:
          - "0"  # Burner blocked
          - "9"  # Boiler blocked
    actions:
      - action: notify.notify
        data:
          message: "The heater is blocked (status {{ states('sensor.biowin_heater_status') }})"
```

Or when it is switched off on its screen, from its operating mode:

```yaml
automation:
  - alias: "Heater switched off"
    triggers:
      - trigger: state
        entity_id: sensor.biowin_operating_mode
        to: "0"  # Switched off
    actions:
      - action: notify.notify
        data:
          message: "The heater was switched off on its screen"
```

In automations, the presets, the heater status and the operating mode are codes; Home Assistant shows them by name. The entity ids above
are those of an English installation: find yours in each entity's settings.

## Known limitations

- Only the heater and heating circuit functions are read, with the hot water of a circuit that heats it. Buffers and
  solar modules are not supported yet.
- The readings are polled every minute, so a change on the heater can take up to a minute to show (up to ten
  minutes for the pellet consumption and the running times until cleaning).
- Discovery works over IPv4 only. A heater found only at an IPv6 address must be added by hand.
- A heater status the integration does not know (beyond code 17) shows as unknown, and so does an operating mode
  beyond code 11.
- The heater reports one error at a time, the current one: an earlier error, or a second one, does not show.

## Troubleshooting

To debug the integration, add the following to your `configuration.yaml` file:

```yaml
logger:
  default: warning
  logs:
    custom_components.windhager: debug
```

This enables debug logging for the Windhager integration. If any values are shown as "Unknown", check the logs for
more information.

When the heater cannot be reached, or does not answer three polls in a row, its entities become *unavailable*. The
log says so once, then once more when the heater answers again. The details of each failed request are in the debug
log.

- **Cannot connect** when adding the heater: check that the InfoWIN Touch's web page opens at `http://<host>`, and
  that Home Assistant can reach that address.
- **Invalid authentication**: the password was refused. Log in to the InfoWIN Touch's web page with it to check it: the
  password of a Windhager Connect account or of the mobile app does not work here.
- **Entities unavailable**: the heater did not answer, and the log says why. They come back by themselves once the
  heater answers again, for example after it was switched off at the mains or the InfoWIN Touch restarted. After a
  long outage this can take up to five minutes, the longest wait between two polls.
- **A changed setting fails with an error**: the heater refused the change or did not answer. The message says which.

To see everything your heater exposes (to add a sensor, or for a model that is not supported yet), download the
diagnostics:

1. Go to *Settings → Devices & services → Windhager Heater*, and choose *Download diagnostics* in the entry's menu.
   This first download starts a full scan of the heater's API in the background. The scan takes about two minutes,
   because every reading is requested one after the other.
2. Once the log says the scan has finished, download the diagnostics again: the file now holds the scan.

The host, password and MAC address are redacted in the file, and so are the modules' chip IDs, replaced by
`**REDACTED_1**` (the heater's), `**REDACTED_2**`… even inside the entities' ids.

Please report issues on the [GitHub repository](https://github.com/vermi0ffh/ha-windhager/issues). Include the logs,
the diagnostics, and the device you are trying to integrate.

## Removal

1. Go to *Settings → Devices & services → Windhager Heater*, and choose *Delete* in the entry's menu. Its devices and
   entities are removed with it. Nothing changes on the heater.
2. To also remove the integration's files, remove it in HACS (or delete the `custom_components/windhager` folder),
   then restart Home Assistant.

## Contributing

If you want to contribute to this project, please feel free to fork the repository and submit a pull request,
following the rules of [AGENTS.md](AGENTS.md) (for people and coding agents alike). Please lint and format the code using [Ruff](https://docs.astral.sh/ruff/) as recommended by the [Home Assistant development guidelines](https://developers.home-assistant.io/docs/development_guidelines).

The tests run against a pinned Home Assistant (Python 3.14):

```bash
pip install -r requirements_test.txt
pytest
```

## License

[Apache 2.0](LICENSE).
