"""Config flow for LG Soundbars Health."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST

from .const import (
    CONF_SCAN_INTERVAL_SECONDS,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
    SOURCE_DOMAIN,
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LG Soundbars Health."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Create one helper entry for existing LG Soundbar entries."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        soundbar_entries = [
            entry
            for entry in self.hass.config_entries.async_entries(SOURCE_DOMAIN)
            if str(entry.data.get(CONF_HOST, "")).strip()
        ]

        if not soundbar_entries:
            return self.async_abort(reason="no_lg_soundbar_entries")

        return self.async_create_entry(
            title="LG Soundbars Health",
            data={},
            options={CONF_SCAN_INTERVAL_SECONDS: DEFAULT_SCAN_INTERVAL_SECONDS},
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlow):
    """Handle options for LG Soundbars Health."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = _parse_scan_interval_option(
            self._config_entry.options.get(CONF_SCAN_INTERVAL_SECONDS),
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL_SECONDS,
                    default=current_interval,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=MIN_SCAN_INTERVAL_SECONDS,
                        max=MAX_SCAN_INTERVAL_SECONDS,
                    ),
                )
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)


def _parse_scan_interval_option(raw_value: Any) -> int:
    """Return a safe scan interval for the options form default."""
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_SCAN_INTERVAL_SECONDS
    return min(MAX_SCAN_INTERVAL_SECONDS, max(MIN_SCAN_INTERVAL_SECONDS, value))
