import asyncio
import aiohttp
import logging
# The InfoWIN Touch's own text files, on the local network: Python's expat refuses
# external entities and limits entity expansion
import xml.etree.ElementTree as ET
from .const import BUFFER_FUNCTION_TYPE, CLIMATE_FUNCTION_TYPE, DEFAULT_USERNAME, HEATER_FUNCTION_TYPE
from .exceptions import CannotConnect, InvalidAuth, WriteFailed

_LOGGER = logging.getLogger(__name__)

# Each request of a scan: the coordinator's timeout
SCAN_REQUEST_TIMEOUT_S = 20
# A write: the same, so that a heater gone silent fails the action instead of holding it
WRITE_TIMEOUT_S = 20
# The modules are listed again every so many polls (ten minutes), to find a module added to
# the heater: /1 took 0.05 to 0.18 s on 2026-10-30, against 4.6 s for a poll
MODULES_CHECK_POLLS = 10
# The datapoints that change over hours or days (consumption totals, running times) are read
# every so many polls (ten minutes), keeping their last value in between: each datapoint is
# a request of its own, 0.16 to 0.18 s on 2026-10-31 (19 datapoints in 3.0 to 3.4 s a poll),
# and a poll must end within the coordinator's 20 s
SLOW_VALUES_POLLS = 10
# A heating circuit's datapoints beyond its climate's: (path, key, English name, entity type,
# hot water only), named by the InfoWIN Touch's res/xml/VarIdentTexte_<language>.xml
CIRCUIT_DATAPOINTS = (
    # Vorlauftemperatur: the flow to the circuit, and its target (0 while it does not heat)
    ("/0/2/0", "flow_temperature", "Flow temperature", "temperature", False),
    ("/1/2/0", "flow_target_temperature", "Flow target temperature", "temperature", False),
    # Kesseltemperatur: the water the circuit draws from (boiler or buffer), and its target
    ("/0/7/0", "boiler_temperature", "Boiler temperature", "temperature", False),
    ("/1/7/0", "boiler_target_temperature", "Boiler target temperature", "temperature", False),
    # Betriebsart: heating, setback, standby at the heating limit...
    ("/2/9/0", "circuit_operating_mode", "Operating mode", "circuit_operating_mode", False),
    # Heizkreispumpe: 0 or 100
    ("/1/20/0", "circuit_pump", "Circuit pump", "running", False),
    # Warmwasser: the tank's temperature and target, and its charging pump
    ("/0/4/0", "hot_water_temperature", "Hot water temperature", "temperature", True),
    ("/1/4/0", "hot_water_target_temperature", "Hot water target temperature", "temperature", True),
    ("/1/66/0", "hot_water_charging_pump", "Hot water charging pump", "running", True),
)
# The datapoints of the functions read beyond the heater and the circuits, by function type:
# (path, key, English name, the entity's description, slow), each compared with the heater's
# mobile app on 2026-10-31
FUNCTION_DATAPOINTS: dict[int, tuple[tuple[str, str, str, dict, bool], ...]] = {
    # A buffer tank (PUFFER of a WFBPK module): its sensors as the app and the InfoWIN's
    # res/xml/VarIdentTexte_<language>.xml name them, 40.9 and 34.8 °C; its third one, TPT,
    # was not connected
    BUFFER_FUNCTION_TYPE: (
        ("/21/65/0", "buffer_temperature_tpe", "Buffer temperature TPE", {"type": "temperature"}, False),
        ("/21/66/0", "buffer_temperature_tpa", "Buffer temperature TPA", {"type": "temperature"}, False),
    ),
}
# The error texts' file: about 7 kB, once at setup
ERROR_TEXTS_TIMEOUT_S = 20
# The languages of the InfoWIN Touch's error texts tried after the instance's: English, then
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


class WindhagerHttpClient:
    """Raw API HTTP requests"""

    def __init__(self, host, password) -> None:
        self.host = host
        self.password = password
        self.oids = None
        # Read every SLOW_VALUES_POLLS polls only
        self.slow_oids: set[str] = set()
        self.devices = []
        self.heater_id = None
        self._session = None
        self._modules_signature: tuple | None = None
        self._polls_since_modules_check = 0
        # The polls left before the slow datapoints are read again: 0 reads them now
        self._polls_before_slow_read = 0
        self._slow_values: dict[str, str | None] = {}
        self._check_required_values = False
        # The slow datapoints whose request failed: read again with the next poll
        self._slow_retry: set[str] = set()

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
        languages = [language.split("-")[0].lower()]
        languages += [other for other in ERROR_TEXTS_FALLBACK_LANGUAGES if other not in languages]
        await self._ensure_session()
        for lang in languages:
            url = f"http://{self.host}/res/xml/ErrorTexte_{lang}.xml"
            try:
                async with (
                    asyncio.timeout(ERROR_TEXTS_TIMEOUT_S),
                    self._session.get(url) as ret,
                ):
                    if not ret.ok:
                        _LOGGER.debug("No error texts at %s: %s", url, ret.status)
                        continue
                    root = ET.fromstring(await ret.text())
            except (aiohttp.ClientError, TimeoutError, ET.ParseError) as err:
                _LOGGER.debug("Cannot read the error texts at %s: %s", url, err)
                continue
            return {
                error.get("code"): " ".join(error.get("text", "").split())
                for error in root.iter("error")
                if error.get("code")
            }
        return {}

    slugify = staticmethod(slugify)

    def _discover(self, json_devices: list[dict]) -> None:
        """The entities and datapoints of the modules /1 lists."""
        self.oids = set()
        self.slow_oids = set()
        self.devices = []
        self.heater_id = heater_id(json_devices)
        self._modules_signature = modules_signature(json_devices)
        # The modules' slow datapoints are read with the next poll
        self._polls_before_slow_read = 0
        self._slow_values = {}
        # The entities that need a value are checked against the next poll
        self._check_required_values = True
        self._slow_retry = set()

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

            for index, function in enumerate(functions):
                fct_id = f"/{str(function['fctId'])}"
                # The module's first circuit keeps the ids and device it always had; another
                # circuit of the module (RADIATOREN, function 1 of an UMUMLZ on 2026-10-31)
                # is a device of its own, named after it
                climate_id = f"{self.id_base}{device_id}" if index == 0 else f"{self.id_base}{device_id}{fct_id}"
                circuit_device_id = (
                    f"{self.id_base}{str(device['nodeId'])}"
                    if index == 0
                    else f"{self.id_base}{str(device['nodeId'])}{fct_id}"
                )

                # Climate control
                self.devices.append(
                    {
                        "id": self.slugify(climate_id),
                        "name": function["name"],
                        "type": "climate",
                        "prefix": device_id,
                        "function": fct_id,
                        "oids": [
                            f"{fct_id}/0/1/0",
                            f"{fct_id}/1/1/0",
                            f"{fct_id}/3/50/0",
                            f"{fct_id}/2/10/0",
                            f"{fct_id}/3/58/0",
                        ],
                        # The module's device, as its sensors' (it was a device of
                        # its own, without them, before 2026-10-29)
                        "device_id": self.slugify(circuit_device_id),
                        "device_name": function["name"],
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
                        "name": f"{function['name']} Current Temperature",
                        "type": "temperature",
                        "correction_oid": f"{device_id}{fct_id}/3/58/0",
                        "oid": f"{device_id}{fct_id}/0/1/0",
                        "device_id": self.slugify(circuit_device_id),
                        "device_name": function["name"],
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
                        "name": f"{function['name']} Current Temperature real",
                        "type": "temperature",
                        "entity_category": "diagnostic",
                        "oid": f"{device_id}{fct_id}/0/1/0",
                        "device_id": self.slugify(circuit_device_id),
                        "device_name": function["name"],
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
                        "name": f"{function['name']} Comfort Temperature Correction",
                        "type": "sensor",
                        "device_class": None,
                        "state_class": "measurement",
                        # A setting of the circuit, rarely watched
                        "entity_category": "diagnostic",
                        "enabled_default": False,
                        "unit": "K",
                        "oid": f"{device_id}{fct_id}/3/58/0",
                        "device_id": self.slugify(circuit_device_id),
                        "device_name": function["name"],
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
                        "name": f"{function['name']} Current Temperature Correction",
                        "type": "sensor",
                        "device_class": None,
                        "state_class": "measurement",
                        # A setting of the circuit, rarely watched
                        "entity_category": "diagnostic",
                        "enabled_default": False,
                        "unit": "K",
                        "oid": f"{device_id}{fct_id}/3/7/0",
                        "device_id": self.slugify(circuit_device_id),
                        "device_name": function["name"],
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
                        "name": f"{function['name']} Target Temperature",
                        "type": "temperature",
                        "correction_oid": f"{device_id}{fct_id}/3/58/0",
                        "oid": f"{device_id}{fct_id}/1/1/0",
                        "device_id": self.slugify(circuit_device_id),
                        "device_name": function["name"],
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
                        "name": f"{function['name']} Outside Temperature",
                        "type": "temperature",
                        "oid": f"{device_id}{fct_id}/0/0/0",
                        "device_id": self.slugify(circuit_device_id),
                        "device_name": function["name"],
                        **module,
                    }
                )

                # What the heater's mobile app shows on the circuit's Info screen, each
                # checked against it on 2026-10-31. A circuit without hot water (RADIATOREN)
                # answers its hot water datapoints without a value, and its lookups do not
                # list them: those entities are kept only for a circuit that answers them
                for path, key, name, entity_type, hot_water in CIRCUIT_DATAPOINTS:
                    oid = f"{device_id}{fct_id}{path}"
                    self.oids.add(oid)
                    self.devices.append(
                        {
                            "id": self.slugify(f"{self.id_base}{oid}"),
                            "key": key,
                            "name": f"{function['name']} {name}",
                            "type": entity_type,
                            "oid": oid,
                            "requires_value": hot_water,
                            "device_id": self.slugify(circuit_device_id),
                            "device_name": function["name"],
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
                    ]
                )
                self.slow_oids.update(
                    [
                        # Pellet consumption, in tonnes to two decimals
                        f"{device_id}{fct_id}/23/100/0",
                        f"{device_id}{fct_id}/23/103/0",
                        # Running hours until each cleaning
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

            # The functions the integration reads through FUNCTION_DATAPOINTS: each one a
            # device of its own, named after it, with its module as the model
            for function in device["functions"]:
                datapoints = FUNCTION_DATAPOINTS.get(function.get("fctType"))
                if not datapoints or function.get("lock") is not False:
                    continue
                fct_id = f"/{str(function['fctId'])}"
                function_device_id = self.slugify(f"{self.id_base}{str(device['nodeId'])}{fct_id}")
                for path, key, name, entity, slow in datapoints:
                    oid = f"{device_id}{fct_id}{path}"
                    (self.slow_oids if slow else self.oids).add(oid)
                    self.devices.append(
                        {
                            "id": self.slugify(f"{self.id_base}{oid}"),
                            "key": key,
                            "name": f"{function['name']} {name}",
                            "oid": oid,
                            "device_id": function_device_id,
                            "device_name": function["name"],
                            **module,
                            **entity,
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

        failed: set[str] = set()
        ret = {
            "devices": self.devices,
            "heater_id": self.heater_id,
            "oids": await self._read(self.oids, failed),
        }

        if self._check_required_values:
            self._drop_entities_without_value(ret["oids"], failed)
            ret["devices"] = self.devices

        if self._polls_before_slow_read <= 0:
            self._slow_retry = set()
            self._slow_values = await self._read(self.slow_oids, self._slow_retry)
            self._polls_before_slow_read = SLOW_VALUES_POLLS
        elif self._slow_retry:
            # A failed request (a timeout) is not left unknown for ten minutes; a datapoint
            # answered without a value is
            retry, self._slow_retry = self._slow_retry, set()
            self._slow_values.update(await self._read(retry, self._slow_retry))
        self._polls_before_slow_read -= 1
        ret["oids"].update(self._slow_values)

        return ret

    def _drop_entities_without_value(self, values: dict[str, str | None], failed: set[str]) -> None:
        """Drop the entities of datapoints the module does not have.

        Such a datapoint answers without a value (a circuit's hot water, on a circuit
        without one, answered with no "value" on 2026-10-31): it is no longer read, until
        the modules are discovered again. A datapoint whose request failed (a timeout)
        tells nothing: it is checked again with the next poll.
        """
        missing = {
            device["oid"]
            for device in self.devices
            if device.get("requires_value") and values.get(device["oid"]) is None and device["oid"] not in failed
        }
        if missing:
            _LOGGER.info("No value for %s: their entities are not created", ", ".join(sorted(missing)))
        self.devices = [device for device in self.devices if device.get("oid") not in missing]
        self.oids -= missing
        for oid in missing:
            values.pop(oid, None)
        self._check_required_values = any(
            device.get("requires_value") and device["oid"] in failed for device in self.devices
        )

    async def _read(self, oids: set[str], failed: set[str] | None = None) -> dict[str, str | None]:
        """The values of `oids`, one request each: None for a datapoint without a value.

        The datapoints whose request failed, rather than answering without a value, are
        added to `failed`.
        """
        values: dict[str, str | None] = {}
        for oid in oids:
            try:
                json = await self.fetch(oid)
                if "value" in json and json["value"] != "-.-":
                    values[oid] = json["value"]
                else:
                    values[oid] = None
                    _LOGGER.debug("Invalid or missing value for OID %s: %s", oid, json)
            except (InvalidAuth, CannotConnect):
                # The heater as a whole, not this datapoint: the coordinator asks for
                # the password, or makes the entities unavailable
                raise
            except Exception as e:
                # On every poll while it lasts: debug, the entity reads unknown
                values[oid] = None
                if failed is not None:
                    failed.add(oid)
                _LOGGER.debug("Error while fetching OID %s: %s", oid, str(e))
        return values

    async def scan(self):
        """Everything the API exposes: each device, its functions, their sensors and readings.

        For the diagnostics: what a heater offers beyond the entities created. A request
        that fails is recorded under "errors" and the scan goes on, so that one
        unreadable function does not hide the rest.
        """
        errors = {}

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

        return {"devices": devices, "errors": errors}
