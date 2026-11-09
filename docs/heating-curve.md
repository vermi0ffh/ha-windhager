# Checking a circuit's heating curve

The heater sets a circuit's flow temperature from the outdoor temperature, along the circuit's heating curve. Without
a Windhager room unit (Fernsteller) it does not know how warm the rooms are. Room thermostats from another system
(Homematic, Zigbee, radiator thermostats…) do, and their valves show whether the curve fits: a valve open most of the
time in the neediest room means the flow is barely warm enough, valves rarely open everywhere mean it is warmer than
needed (#95).

This integration does not judge that itself: it reads the heater, and stays read only for its settings (rule 16). The
separate [Heating Circuit Advisor](https://github.com/Martin4us3/ha-heating-circuit-advisor) does, from the valves'
time open, for any heater whose circuit is a climate entity. This page says how to use it with a Windhager heater and
what to change on the heater when it gives a verdict.

## Setting it up with this integration

Per heating circuit, add the advisor with:

| Advisor field | Entity of this integration |
|---------------|----------------------------|
| Heating circuit | The circuit's climate (named after the circuit) |
| Outdoor temperature | The circuit's *Outside temperature* sensor |

The circuit's comfort phase, which the advisor evaluates, is the heater's: the circuit's program (Heizprogramm) or
its operating mode (Betriebswahl, `3/50`). If the thermostats keep their own schedules, the two run side by side;
the advisor counts only the heater's comfort phase.

## What to change on the heater

From the smallest change to the largest, as the heater's levels allow it ([operating-levels.md](operating-levels.md)):

| Advice | Setting | Heater level | Where |
|--------|---------|--------------|-------|
| Room setpoint hint: lower or raise | `3/51` Raumtemperatur-Sollwert, heating | operator | the heater's screen, the circuit's *Raumtemperatur-Sollwerte* |
| Curve too low or too high, by about 1 K | `3/58` Korrekturwert | operator | the heater's screen, *Behaglichkeit*, or the `windhager.set_current_temp_compensation` action |
| Still too low or too high after a few K | `3/13`, `3/29`, `3/12`, `3/1` design temperatures (the curve itself) | service | the installer |

The flow temperature follows the circuit's room setpoint too: a circuit set to 23 °C heats for more than rooms set to
21 °C ask for. That is why the advisor checks the setpoint first. One step at a time, then two days at similar outdoor
temperatures before the next.

**Heating surface insufficient** is not a curve problem: a loop open all the time while its room stays below its
setpoint needs a warmer flow than the other rooms of its circuit, more flow (hydraulic balance), or more heating
surface.

## What it showed on one heater

A BioWIN 2 with four circuits (floor heating and radiators), Homematic IP thermostats and actuators, the verdicts on
2026-11-09 at about 7 °C outside:

- One circuit's room setpoint was 2 K below its rooms': the hint said raise it before touching the curve.
- In a floor circuit, one room's loop was open 96 % of the comfort phase without reaching its setpoint, the other
  rooms' below 10 %: heating surface insufficient for that room, not a curve too low for the circuit.
- A circuit with radiators and a small floor loop had every valve open less than 10 %: curve too high.
