import asyncio
import aiohttp
import logging
from .const import DEFAULT_USERNAME, CLIMATE_FUNCTION_TYPE, HEATER_FUNCTION_TYPE
from .exceptions import CannotConnect, InvalidAuth, WriteFailed

_LOGGER = logging.getLogger(__name__)

# Each request of a scan: the coordinator's timeout
SCAN_REQUEST_TIMEOUT_S = 20
# A write: the same, so that a heater gone silent fails the action instead of holding it
WRITE_TIMEOUT_S = 20


def slugify(identifier_str: str) -> str:
    """An identifier as the unique ids of the entities and devices hold it."""
    return identifier_str.replace(".", "-").replace("/", "-")


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
        self.devices = []
        self.heater_id = None
        self._session = None

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
        except Exception as e:
            _LOGGER.error("Failed to fetch data for %s: %s", url, str(e))
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

    slugify = staticmethod(slugify)

    async def fetch_all(self):
        if self.oids is None:
            self.oids = set()
            # Fetch all devices on the network
            json_devices = await self.fetch("/1")
            self.heater_id = heater_id(json_devices)

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
                            "device_id": self.slugify(f"{self.id_base}{device_id}"),
                            "device_name": functions[0]["name"],
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
                        }
                    )

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
            except Exception as e:
                ret["oids"][oid] = None
                _LOGGER.error("Error while fetching OID %s: %s", oid, str(e))

        return ret

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
