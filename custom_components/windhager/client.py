import asyncio
import aiohttp
import logging
# The InfoWIN Touch's own text files, on the local network: Python's expat refuses
# external entities and limits entity expansion
import xml.etree.ElementTree as ET
from .const import DEFAULT_USERNAME, CLIMATE_FUNCTION_TYPE, HEATER_FUNCTION_TYPE
from .exceptions import CannotConnect, InvalidAuth, WriteFailed

_LOGGER = logging.getLogger(__name__)

# Each request of a scan: the coordinator's timeout
SCAN_REQUEST_TIMEOUT_S = 20
# A write: the same, so that a heater gone silent fails the action instead of holding it
WRITE_TIMEOUT_S = 20
# The modules are listed again every so many polls (ten minutes), to find a module added to
# the heater: /1 took 0.05 to 0.18 s on 2026-10-30, against 4.6 s for a poll
MODULES_CHECK_POLLS = 10
# A text file of the InfoWIN Touch: about 7 kB for the error texts, once at setup
ERROR_TEXTS_TIMEOUT_S = 20
# The languages of the InfoWIN Touch's text files tried after the instance's: English, then
# German, the manufacturer's
ERROR_TEXTS_FALLBACK_LANGUAGES = ("en", "de")


def slugify(identifier_str: str) -> str:
    """An identifier as the unique ids of the entities and devices hold it."""
    return identifier_str.replace(".", "-").replace("/", "-")


def modules_signature(json_devices: list[dict]) -> tuple:
    """What the entities depend on in /1's list: the modules and their functions."""
    return tuple(
        sorted(
            (
                str(device.get("nodeId")),
                tuple(
                    sorted(
                        (str(function.get("fctId")), str(function.get("fctType")), str(function.get("lock")))
                        for function in device.get("functions", [])
                    )
                ),
            )
            for device in json_devices
        )
    )


def heater_id(json_devices: list[dict]) -> str | None:
    """The heater's identity: the Neuron ID of the module holding its heater function.

    A Neuron ID is the module's chip ID, unique and fixed, unlike the host. Without a
    heater function, the first module's; without any module, None.
    """
    modules = [device for device in json_devices if "neuronId" in device]
    for device in modules:
        if any(
            function.get("fctType") == HEATER_FUNCTION_TYPE
            for function in device.get("functions", [])
        ):
            return device["neuronId"]
    return modules[0]["neuronId"] if modules else None


def label_level(texts: dict[str, dict], function_type: int, level: dict) -> None:
    """A scanned level and its readings, labelled with the heater's names (scan_texts).

    A level is named by its function type and id ("14/103": "Modulfunktionen"), a reading
    by the group and member of its OID (/subnet/node/function/group/member/instance:
    "7/76": "Heizkreis"), and an enumerated value by those and its code ("2": "Mischer
    Fussboden"). Names the heater does not have are left out.
    """
    if label := texts["levels"].get(f"{function_type}/{level.get('id')}"):
        level["label"] = label
    for reading in level.get("readings", []):
        key = "/".join(str(reading.get("OID", "")).strip("/").split("/")[3:5])
        if label := texts["datapoints"].get(key):
            reading["label"] = label
        if value_label := texts["enums"].get(key, {}).get(str(reading.get("value"))):
            reading["value_label"] = value_label


class WindhagerHttpClient:
    """Raw API HTTP requests"""

    def __init__(self, host, password) -> None:
        self.host = host
        self.password = password
        self.oids = None
        self.devices = []
        self.heater_id = None
        self._session = None
        self._modules_signature: tuple | None = None
        self._polls_since_modules_check = 0

    @property
    def id_base(self) -> str:
        """What the unique ids of the entities and devices start with: the heater's Neuron
        ID, which a new host does not change, else (no module listed) the host."""
        return self.heater_id or self.host

    async def _ensure_session(self):
        """Ensure that we have an active client session"""
        if self._session is None:
            # aiohttp answers the heater's digest challenge, and reuses it for the next requests
            self._session = aiohttp.ClientSession(
                middlewares=(aiohttp.DigestAuthMiddleware(DEFAULT_USERNAME, self.password),)
            )

    async def close(self):
        """Close the client session"""
        if self._session:
            await self._session.close()
            self._session = None

    async def fetch(self, url):
        try:
            await self._ensure_session()
            ret = await self._session.get(f"http://{self.host}/api/1.0/lookup{url}")
            # The heater refuses the password with a 401 and an HTML page (2026-10-29),
            # which reading as JSON would turn into a mere connection error
            if ret.status == 401:
                raise InvalidAuth(f"The heater refused the password for {url}")
            json = await ret.json()
            _LOGGER.debug("Fetched data for %s: %s", url, json)
            return json
        except aiohttp.ClientConnectionError as err:
            raise CannotConnect(f"Cannot reach the heater for {url}: {err}") from err
        except Exception as e:
            # The caller decides: the coordinator logs once when the heater is lost
            _LOGGER.debug("Failed to fetch data for %s: %s", url, str(e))
            raise

    async def update(self, oid: str, value: str) -> None:
        """Write a datapoint; raise if the heater did not take it."""
        await self._ensure_session()
        try:
            async with (
                asyncio.timeout(WRITE_TIMEOUT_S),
                self._session.put(
                    f"http://{self.host}/api/1.0/datapoint",
                    data=bytes(f'{{"OID":"{oid}","value":"{value}"}}', "utf-8"),
                ) as ret,
            ):
                # Refused like a lookup, with a 401 (2026-10-29): nothing is written
                if ret.status == 401:
                    raise InvalidAuth(f"The heater refused the password writing {oid}")
                if not ret.ok:
                    raise WriteFailed(oid, ret.status)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CannotConnect(f"Cannot reach the heater writing {oid}: {err}") from err

    async def fetch_error_texts(self, language: str) -> dict[str, str]:
        """The heater's own texts of its error codes, by code, in `language` if it has them.

        The InfoWIN Touch's web page names the error codes from its files
        (res/xml/ErrorTexte_<language>.xml, 2026-10-30), which follow its firmware: the
        integration does not keep a copy of them. Empty if no file could be read: the
        error then shows as its code.
        """
        root = await self._fetch_texts("ErrorTexte", language)
        if root is None:
            return {}
        return {
            error.get("code"): " ".join(error.get("text", "").split())
            for error in root.iter("error")
            if error.get("code")
        }

    async def fetch_enum_texts(self, language: str) -> dict[str, dict[str, str]]:
        """The heater's own texts of its enumerated values, by "group/member", then by code.

        The InfoWIN Touch's web page names a datapoint's codes from its file
        (res/xml/AufzaehlTexte_<language>.xml, 2026-11-01: 50 enumerations, among them the
        heater status 2/1 and the operating mode 2/59), which follows its firmware. Empty
        if no file could be read: the enum sensors then know only the translated codes.
        """
        root = await self._fetch_texts("AufzaehlTexte", language)
        if root is None:
            return {}
        return {
            f"{group.get('id')}/{member.get('id')}": {
                enum.get("id"): " ".join((enum.text or "").split())
                for enum in member.iter("enum")
                if enum.get("id")
            }
            for group in root.iter("gn")
            for member in group.iter("mn")
        }

    async def _fetch_texts(self, name: str, language: str) -> ET.Element | None:
        """One of the InfoWIN Touch's text files (res/xml/<name>_<language>.xml), parsed.

        In `language` if the heater has it, else in English, then German. None if no file
        could be read.
        """
        languages = [language.split("-")[0].lower()]
        languages += [other for other in ERROR_TEXTS_FALLBACK_LANGUAGES if other not in languages]
        await self._ensure_session()
        for lang in languages:
            url = f"http://{self.host}/res/xml/{name}_{lang}.xml"
            try:
                async with (
                    asyncio.timeout(ERROR_TEXTS_TIMEOUT_S),
                    self._session.get(url) as ret,
                ):
                    if not ret.ok:
                        _LOGGER.debug("No texts at %s: %s", url, ret.status)
                        continue
                    return ET.fromstring(await ret.text())
            except (aiohttp.ClientError, TimeoutError, ET.ParseError) as err:
                _LOGGER.debug("Cannot read the texts at %s: %s", url, err)
        return None

    slugify = staticmethod(slugify)

    def _discover(self, json_devices: list[dict]) -> None:
        """The entities and datapoints of the modules /1 lists."""
        self.oids = set()
        self.devices = []
        self.heater_id = heater_id(json_devices)
        self._modules_signature = modules_signature(json_devices)

        # Add devices
        for device in json_devices:
            device_id = f"/1/{str(device['nodeId'])}"

            if "functions" not in device:
                _LOGGER.debug("Device %s has no functions, skipping.", device_id)
                continue

            # Filter climate controls
            functions = list(
                filter(
                    lambda f: (
                        f["fctType"] == CLIMATE_FUNCTION_TYPE and f["lock"] is False
                    ),
                    device["functions"],
                )
            )
            # What the module's device shows: its model and chip ID
            module = {
                "device_model": device.get("name"),
                "device_serial_number": device.get("neuronId"),
            }

            if len(functions) > 0:
                fct_id = f"/{str(functions[0]['fctId'])}"

                # Climate control
                self.devices.append(
                    {
                        "id": self.slugify(f"{self.id_base}{device_id}"),
                        "name": functions[0]["name"],
                        "type": "climate",
                        "prefix": device_id,
                        "oids": [
                            f"{fct_id}/0/1/0",
                            f"{fct_id}/1/1/0",
                            f"{fct_id}/3/50/0",
                            f"{fct_id}/2/10/0",
                            f"{fct_id}/3/58/0",
                        ],
                        # The module's device, as its sensors' (it was a device of
                        # its own, without them, before 2026-10-29)
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )
                self.oids.update(
                    [
                        # Current temperature
                        f"{device_id}{fct_id}/0/1/0",
                        # Target temperature
                        f"{device_id}{fct_id}/1/1/0",
                        # Current selected mode
                        f"{device_id}{fct_id}/3/50/0",
                        # Duration of custom temperature (in minutes)
                        f"{device_id}{fct_id}/2/10/0",
                        # Outside temperature
                        f"{device_id}{fct_id}/0/0/0",
                        # Temp comfort correction
                        f"{device_id}{fct_id}/3/58/0",
                        # Tempe correction
                        f"{device_id}{fct_id}/3/7/0",
                    ]
                )

                # Current temperature
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/0/1/0/3/58/0"
                        ),
                        "key": "current_temperature",
                        "name": f"{functions[0]['name']} Current Temperature",
                        "type": "temperature",
                        "correction_oid": f"{device_id}{fct_id}/3/58/0",
                        "oid": f"{device_id}{fct_id}/0/1/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )

                # Current temperature (real)
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/0/1/0"
                        ),
                        "key": "current_temperature_real",
                        "name": f"{functions[0]['name']} Current Temperature real",
                        "type": "temperature",
                        "entity_category": "diagnostic",
                        "oid": f"{device_id}{fct_id}/0/1/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )

                # Comfort Temperature correction
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/3/58/0"
                        ),
                        "key": "comfort_temperature_correction",
                        "name": f"{functions[0]['name']} Comfort Temperature Correction",
                        "type": "sensor",
                        "device_class": None,
                        "state_class": "measurement",
                        # A setting of the circuit, rarely watched
                        "entity_category": "diagnostic",
                        "enabled_default": False,
                        "unit": "K",
                        "oid": f"{device_id}{fct_id}/3/58/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )
                # Current Temperature correction
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/3/7/0"
                        ),
                        "key": "current_temperature_correction",
                        "name": f"{functions[0]['name']} Current Temperature Correction",
                        "type": "sensor",
                        "device_class": None,
                        "state_class": "measurement",
                        # A setting of the circuit, rarely watched
                        "entity_category": "diagnostic",
                        "enabled_default": False,
                        "unit": "K",
                        "oid": f"{device_id}{fct_id}/3/7/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )
                # Target temperature
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/1/1/0"
                        ),
                        "key": "target_temperature",
                        "name": f"{functions[0]['name']} Target Temperature",
                        "type": "temperature",
                        "correction_oid": f"{device_id}{fct_id}/3/58/0",
                        "oid": f"{device_id}{fct_id}/1/1/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )
                # Outside temperature
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/0/0/0"
                        ),
                        "key": "outside_temperature",
                        "name": f"{functions[0]['name']} Outside Temperature",
                        "type": "temperature",
                        "oid": f"{device_id}{fct_id}/0/0/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )

            # Filter heaters
            functions = list(
                filter(
                    lambda f: (
                        f["fctType"] == HEATER_FUNCTION_TYPE and f["lock"] is False
                    ),
                    device["functions"],
                )
            )
            if len(functions) > 0:
                fct_id = f"/{str(functions[0]['fctId'])}"

                self.oids.update(
                    [
                        # Heater power (percent)
                        f"{device_id}{fct_id}/0/9/0",
                        # Fumes temperature
                        f"{device_id}{fct_id}/0/11/0",
                        # Heater temperature
                        f"{device_id}{fct_id}/0/7/0",
                        # Combustion chamber temperature
                        f"{device_id}{fct_id}/0/45/0",
                        # Heater status
                        f"{device_id}{fct_id}/2/1/0",
                        # Operating mode: on, or switched off on the heater's screen
                        f"{device_id}{fct_id}/2/59/0",
                        # Error code: "-" without an error
                        f"{device_id}{fct_id}/2/0/0",
                        # Hopper level, not listed by the heater's lookups
                        f"{device_id}{fct_id}/43/42/0",
                        # Pellet consumption
                        f"{device_id}{fct_id}/23/100/0",
                        f"{device_id}{fct_id}/23/103/0",
                        # Cleaning
                        f"{device_id}{fct_id}/20/61/0",
                        f"{device_id}{fct_id}/20/62/0",
                    ]
                )

                # Heater current power factor
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/0/9/0"
                        ),
                        "key": "power_factor",
                        "name": f"{functions[0]['name']} Power factor",
                        "type": "sensor",
                        "device_class": "power_factor",
                        "state_class": "measurement",
                        "unit": "%",
                        "oid": f"{device_id}{fct_id}/0/9/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )
                # Fumes temperature
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/0/11/0"
                        ),
                        "key": "fumes_temperature",
                        "name": f"{functions[0]['name']} Fumes Temperature",
                        "type": "temperature",
                        "oid": f"{device_id}{fct_id}/0/11/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )
                # Heater temperature
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/0/7/0"
                        ),
                        "key": "heater_temperature",
                        "name": f"{functions[0]['name']} Heater Temperature",
                        "type": "temperature",
                        "oid": f"{device_id}{fct_id}/0/7/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )
                # Combustion chamber temperature
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/0/45/0"
                        ),
                        "key": "combustion_chamber_temperature",
                        "name": f"{functions[0]['name']} Combustion chamber Temperature",
                        "type": "temperature",
                        "oid": f"{device_id}{fct_id}/0/45/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )
                # Heater status
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/2/1/0"
                        ),
                        "key": "heater_status",
                        "name": f"{functions[0]['name']} Heater status",
                        "type": "select",
                        "oid": f"{device_id}{fct_id}/2/1/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )
                # Operating mode
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/2/59/0"
                        ),
                        "key": "operating_mode",
                        "name": f"{functions[0]['name']} Operating mode",
                        "type": "operating_mode",
                        "oid": f"{device_id}{fct_id}/2/59/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )
                # The heater's error, and whether it has one
                for key, name, entity_type, suffix in (
                    ("heater_error", "Heater error", "error", ""),
                    ("heater_problem", "Heater problem", "problem", "/problem"),
                ):
                    self.devices.append(
                        {
                            "id": self.slugify(
                                f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/2/0/0{suffix}"
                            ),
                            "key": key,
                            "name": f"{functions[0]['name']} {name}",
                            "type": entity_type,
                            "entity_category": "diagnostic",
                            "oid": f"{device_id}{fct_id}/2/0/0",
                            "device_id": self.slugify(
                                f"{self.id_base}{str(device['nodeId'])}"
                            ),
                            "device_name": functions[0]["name"],
                            **module,
                        }
                    )
                # Hopper level (%): the level the heater's mobile app shows (79 % on 2026-10-31)
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/43/42/0"
                        ),
                        "key": "hopper_level",
                        "name": f"{functions[0]['name']} Hopper level",
                        "type": "sensor",
                        "state_class": "measurement",
                        "unit": "%",
                        "oid": f"{device_id}{fct_id}/43/42/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )
                # Pellet consumption
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/23/100/0"
                        ),
                        "key": "pellet_consumption",
                        "name": f"{functions[0]['name']} Pellet consumption",
                        "type": "total",
                        "oid": f"{device_id}{fct_id}/23/100/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )
                # Total pellet consumption
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/23/103/0"
                        ),
                        "key": "total_pellet_consumption",
                        "name": f"{functions[0]['name']} Total Pellet consumption",
                        "type": "total_increasing",
                        "oid": f"{device_id}{fct_id}/23/103/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )

                # Running time until stage 1 cleaning
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/20/61/0"
                        ),
                        "key": "time_until_stage_1_cleaning",
                        "name": f"{functions[0]['name']} Running time until stage 1 cleaning",
                        "type": "sensor",
                        "device_class": "duration",
                        "state_class": "measurement",
                        "entity_category": "diagnostic",
                        "unit": "h",
                        "oid": f"{device_id}{fct_id}/20/61/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )

                # Running time until stage 2 cleaning
                self.devices.append(
                    {
                        "id": self.slugify(
                            f"{self.id_base}/1/{str(device['nodeId'])}{fct_id}/20/62/0"
                        ),
                        "key": "time_until_stage_2_cleaning",
                        "name": f"{functions[0]['name']} Running time until stage 2 cleaning",
                        "type": "sensor",
                        "device_class": "duration",
                        "state_class": "measurement",
                        "entity_category": "diagnostic",
                        "unit": "h",
                        "oid": f"{device_id}{fct_id}/20/62/0",
                        "device_id": self.slugify(
                            f"{self.id_base}{str(device['nodeId'])}"
                        ),
                        "device_name": functions[0]["name"],
                        **module,
                    }
                )

    async def _check_modules(self) -> None:
        """Every MODULES_CHECK_POLLS polls, discover the modules again if /1 lists others."""
        self._polls_since_modules_check += 1
        if self._polls_since_modules_check < MODULES_CHECK_POLLS:
            return
        self._polls_since_modules_check = 0
        try:
            json_devices = await self.fetch("/1")
            signature = modules_signature(json_devices)
        except (InvalidAuth, CannotConnect):
            # The heater as a whole: as a datapoint's request would
            raise
        except Exception as err:
            # The modules stay as they were until the next check
            _LOGGER.debug("Cannot list the modules again: %s", err)
            return
        if signature != self._modules_signature:
            _LOGGER.info("The heater's modules changed: discovering them again")
            self._discover(json_devices)

    async def fetch_all(self):
        if self.oids is None:
            # Fetch all devices on the network
            self._discover(await self.fetch("/1"))
        else:
            await self._check_modules()

        ret = {
            "devices": self.devices,
            "heater_id": self.heater_id,
            "oids": {},
        }

        # Read all found OIDs
        for oid in self.oids:
            try:
                json = await self.fetch(oid)
                if "value" in json and json["value"] != "-.-":
                    ret["oids"][oid] = json["value"]
                else:
                    ret["oids"][oid] = None
                    _LOGGER.debug("Invalid or missing value for OID %s: %s", oid, json)
            except (InvalidAuth, CannotConnect):
                # The heater as a whole, not this datapoint: the coordinator asks for
                # the password, or makes the entities unavailable
                raise
            except Exception as e:
                # On every poll while it lasts: debug, the entity reads unknown
                ret["oids"][oid] = None
                _LOGGER.debug("Error while fetching OID %s: %s", oid, str(e))

        return ret

    async def scan(self, language: str | None = None):
        """Everything the API exposes: each device, its functions, their sensors and readings.

        For the diagnostics: what a heater offers beyond the entities created. A request
        that fails is recorded under "errors" and the scan goes on, so that one
        unreadable function does not hide the rest.

        With a `language`, the levels and readings also get the heater's own names for
        them in a "label", and an enumerated reading the text of its value in a
        "value_label" (scan_texts): the scan then tells what "00-045" is.
        """
        errors = {}
        texts = await self.scan_texts(language) if language else None

        async def fetch_or_record(url):
            try:
                async with asyncio.timeout(SCAN_REQUEST_TIMEOUT_S):
                    return await self.fetch(url)
            # aiohttp, JSON, authentication or timeout: all recorded alike
            except Exception as err:
                errors[url] = repr(err)
                return []

        devices = await fetch_or_record("/1")
        for device in devices:
            for function in device.get("functions", []):
                # Skipped as by the first scan (#23), written against a real heater
                if function["fctType"] < 0:
                    continue
                function_url = f"/1/{device['nodeId']}/{function['fctId']}"
                function["sensors"] = await fetch_or_record(function_url)
                for sensor in function["sensors"]:
                    sensor["readings"] = await fetch_or_record(f"{function_url}/{sensor['id']}")
                    if texts:
                        label_level(texts, function["fctType"], sensor)

        return {"devices": devices, "errors": errors}

    async def scan_texts(self, language: str) -> dict[str, dict]:
        """The heater's own names of its levels and datapoints, and its enums' texts.

        The InfoWIN Touch's web page names them from its files, which follow its firmware
        (2026-11-01, on a BioWIN 2: res/xml/EbenenTexte_<language>.xml, about 4 kB, the
        levels of each function type; VarIdentTexte, about 90 kB, 1858 names by
        group/member; AufzaehlTexte, about 10 kB). Read only for the diagnostics' scan: they
        are not kept. A file that cannot be read leaves its names out.
        """
        levels = await self._fetch_texts("EbenenTexte", language)
        datapoints = await self._fetch_texts("VarIdentTexte", language)
        return {
            "levels": {} if levels is None else {
                f"{function_type.get('id')}/{level.get('id')}": text
                for function_type in levels.iter("fcttyp")
                for level in function_type.iter("ebene")
                if (text := " ".join((level.text or "").split()))
            },
            "datapoints": {} if datapoints is None else {
                f"{group.get('id')}/{member.get('id')}": text
                for group in datapoints.iter("gn")
                for member in group.iter("mn")
                if (text := " ".join((member.text or "").split()))
            },
            "enums": await self.fetch_enum_texts(language),
        }
