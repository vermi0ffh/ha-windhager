"""Constants for the Windhager Heater integration."""

CLIMATE_FUNCTION_TYPE = 14
DEFAULT_USERNAME = "USER"
DOMAIN = "windhager"
HEATER_FUNCTION_TYPE = 9
# A log boiler (LogWIN): its own function type, beside a BioWIN on the same bus (2026-11-06)
LOG_BOILER_FUNCTION_TYPE = 10
UPDATE_INTERVAL = 60
# The longest wait between two polls while the heater does not answer
MAX_UPDATE_INTERVAL = 300
