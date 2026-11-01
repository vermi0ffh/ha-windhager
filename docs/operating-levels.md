# The heater's operating levels

What Home Assistant may change follows the InfoWIN Touch's own operating concept ([AGENTS.md](../AGENTS.md), rule 16;
#92). This page maps the API's levels to the heater's, per function type, as they are checked on a real heater.

## The levels

From Windhager's manual for operation via the InfoWIN Touch (Infinity PLUS, 11/2025,
[PDF](https://www.windhager.com/fileadmin/user_upload/Bedienungsanleitung_Infinity_PLUS_Wall.pdf)):

| Level | How it is reached | Who may change it | In Home Assistant |
|-------|-------------------|-------------------|-------------------|
| **Operation** (the detail view's quick buttons) | one tap | any user | may be written |
| **Info level** | "Werte" | nobody: read only | sensors |
| **Operator level** (Betreiberebene) | Settings → Operator level | "für alle zugänglich" (p. 20) | sensors only; one exception below |
| **Service level** (Serviceebene) | operator level, then hold "OK" for 5 s | "nur durch geschultes Servicepersonal" (p. 52) | diagnostic sensors at most, disabled by default; never written |
| **Actuator test** (Aktorentest) | Settings | "nur dem geschulten Servicepersonal vorbehalten" | never written |

The API does not protect these levels: almost every datapoint of the operator and service levels is writable
(`writeProt: false`). The integration has to.

**The exception:** the comfort correction (`3/58`, operator level) stays writable through the
`windhager.set_current_temp_compensation` action, which existed before this rule. It cannot be changed from an
entity, only by calling the action on purpose (#92).

## Heating circuit (function type 14)

Measured on a BioWIN 2 with UMUMLZ modules on 2026-11-01, read-only. The API levels are the menu items, in the
menu's order; their names come from the heater's `EbenenTexte`, the datapoints' from its `VarIdentTexte`.

| API level | Menu item | Datapoints | Heater level |
|-----------|-----------|------------|--------------|
| 96 | Betriebswahl | `3/50` | operation |
| 97 | Behaglichkeit | `3/58` Korrekturwert | operator (the exception) |
| 98 | WW-Ladefreigabe | `2/16` start, `5/51` temperature | operation (hot water charge) |
| 99 | Eco / Party | `2/10` duration, `3/4` temperature | operation |
| 100 | Ferienprogramm | `3/78` until date | operation (via Betriebswahl) |
| 101 | Raumtemperatur-Sollwerte | `3/51` heating, `3/53` setback | operator |
| 102 | Uhrzeit / Datum | `2/72`, `2/70` | read only |
| 103 | Modulfunktionen | `7/76` heating circuit, `5/76` hot water circuit | service |
| 104 | Auslegungstemperaturen | `3/13`, `3/29`, `3/12`, `3/1` | service |
| 105 | Raumtemperatureinfluss | `3/7` Kompensation, `3/30` | service |
| 106 | Heizgrenzen | `7/8`, `7/2`, `3/21`, `3/2` | service |
| 107 | Warmwasserladung | `5/8` | service |
| 108 | Kesseltemp-Überhöhung | `7/1` | service |
| 109 | Startoptimierung | `3/6` | service |
| 110 | LON-Systemdaten | `4/13`, `4/12`, `4/14` | service |
| 111 | Estrichausheizprogramm | `4/60`, `4/63`–`4/67` | service |
| 112 | Modulinfo | `4/5`, `4/92`, `4/93` | info |
| 113–117 | Raumtemperatur, Warmwassertemperatur, Aussentemperatur, Vorlauftemperatur, Kesseltemperatur | `1/1`, `0/4`, `1/4`, `0/0`, `0/2`, `1/2`, `0/7`, `1/7` | info |
| 119 | Frostschutzgrenzen | `3/0`, `3/23`, `7/45`, `5/58` | service |
| 120 | Heizkreis | `7/13`, `7/3` | service |
| 121 | WW-Ladung | `5/0`, `5/1`, `5/3`, `5/80` | service |
| 122 | (not named by the heater) | `1/20` circuit pump, `1/21` mixer, `1/66` charging pump, read only | info |
| 126 | (not named by the heater) | `5/6` circulation pump, writable | unsure: counts as service |

A level a module does not have is missing from its lookup: the hot water circuit of this heater has level 114, the
heating circuits do not.

## Other function types

Not mapped yet. The heater (type 9), a buffer (16), a heat pump or a hybrid manager have their own level ids: a
datapoint of theirs counts as service level until its menu level is checked against the manual and a real heater,
and added here.
