"""Constants for LG Soundbars Health."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "lg_soundbar_health"
SOURCE_DOMAIN = "lg_soundbar"

DEFAULT_PORT = 9741
DEFAULT_TIMEOUT = 2.0
DEFAULT_SCAN_INTERVAL_SECONDS = 15
DEFAULT_SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS)
MIN_SCAN_INTERVAL_SECONDS = 5
MAX_SCAN_INTERVAL_SECONDS = 3600
CONF_SCAN_INTERVAL_SECONDS = "scan_interval_seconds"
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_auto_reload"
STORAGE_AUTO_RELOAD_ENABLED = "auto_reload_enabled"
DEFAULT_PARENT_RELOAD_COOLDOWN = timedelta(minutes=10)
DEFAULT_AUTO_RELOAD_INITIAL_FAILURES = 3

DATA_COORDINATOR = "coordinator"
