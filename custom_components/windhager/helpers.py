"""Helper functions for Windhager integration."""

from __future__ import annotations
import logging
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)


def parse_value(
    value: Any, as_type: type = float, oid: str | None = None
) -> Any | None:
    """Safely parse a value with error handling."""
    try:
        if value is None:
            return None
        return as_type(value)
    except (ValueError, TypeError):
        _LOGGER.warning("Invalid value for sensor %s, setting as None", oid)
        return None


def get_oid_value(
    coordinator: Any, oid: str, prefix: str = "", default: str = "0"
) -> Optional[float]:
    """Get OID value with error handling."""
    full_path = f"{prefix}{oid}"
    value = coordinator.data.get("oids", {}).get(full_path, default)
    # parse_value turns a value that is not a number into None
    return parse_value(value, float, full_path)
