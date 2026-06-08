"""Sensors for LG Soundbars Health."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HealthState, ha_safe_text
from .const import DATA_COORDINATOR, DOMAIN
from .entity import LGSoundbarHealthEntity


class HealthSensorKey(StrEnum):
    """Health sensor keys."""

    RESPONSE_TIME = "response_time"
    LAST_SEEN = "last_seen"
    OFFLINE_DURATION = "offline_duration"
    FAILURE_COUNT = "failure_count"
    LAST_ERROR = "last_error"
    INITIAL_IP = "initial_ip"
    RESOLVED_IP = "resolved_ip"
    LAST_PARENT_RELOAD = "last_parent_reload"
    PARENT_RELOAD_COUNT = "parent_reload_count"
    PARENT_RELOAD_LAST_ERROR = "parent_reload_last_error"
    PARENT_RELOAD_LAST_REASON = "parent_reload_last_reason"


@dataclass(frozen=True, kw_only=True)
class HealthSensorDescription(SensorEntityDescription):
    """Description for an LG Soundbar health sensor."""

    value_fn: Callable[[HealthState], Any]


SENSOR_DESCRIPTIONS: tuple[HealthSensorDescription, ...] = (
    HealthSensorDescription(
        key=HealthSensorKey.RESPONSE_TIME,
        name="Response time",
        icon="mdi:timer-outline",
        native_unit_of_measurement="ms",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.response_time_ms,
    ),
    HealthSensorDescription(
        key=HealthSensorKey.LAST_SEEN,
        name="Last seen",
        icon="mdi:clock-check-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda state: state.last_success,
    ),
    HealthSensorDescription(
        key=HealthSensorKey.OFFLINE_DURATION,
        name="Offline duration",
        icon="mdi:timer-off-outline",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda state: state.offline_duration_seconds,
    ),
    HealthSensorDescription(
        key=HealthSensorKey.FAILURE_COUNT,
        name="Failure count",
        icon="mdi:counter",
        value_fn=lambda state: state.failure_count,
    ),
    HealthSensorDescription(
        key=HealthSensorKey.LAST_ERROR,
        name="Last error",
        icon="mdi:alert-circle-outline",
        value_fn=lambda state: state.last_error,
    ),
    HealthSensorDescription(
        key=HealthSensorKey.INITIAL_IP,
        name="Initial IP",
        icon="mdi:ip-network",
        value_fn=lambda state: state.initial_ip,
    ),
    HealthSensorDescription(
        key=HealthSensorKey.RESOLVED_IP,
        name="Resolved IP",
        icon="mdi:ip-network-outline",
        value_fn=lambda state: state.resolved_ip,
    ),
    HealthSensorDescription(
        key=HealthSensorKey.LAST_PARENT_RELOAD,
        name="Last LG Soundbar reload",
        icon="mdi:restart-alert",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda state: state.last_parent_reload,
    ),
    HealthSensorDescription(
        key=HealthSensorKey.PARENT_RELOAD_COUNT,
        name="LG Soundbar reload count",
        icon="mdi:counter",
        value_fn=lambda state: state.parent_reload_count,
    ),
    HealthSensorDescription(
        key=HealthSensorKey.PARENT_RELOAD_LAST_ERROR,
        name="LG Soundbar reload last error",
        icon="mdi:alert-circle-outline",
        value_fn=lambda state: state.parent_reload_last_error,
    ),
    HealthSensorDescription(
        key=HealthSensorKey.PARENT_RELOAD_LAST_REASON,
        name="LG Soundbar reload last reason",
        icon="mdi:message-alert-outline",
        value_fn=lambda state: state.parent_reload_last_reason,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up LG Soundbars Health sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    known_ids: set[str] = set()

    def add_new_entities() -> None:
        new_ids = set(coordinator.data) - known_ids
        if not new_ids:
            return
        known_ids.update(new_ids)
        async_add_entities(
            LGSoundbarHealthSensor(coordinator, source_entry_id, description)
            for source_entry_id in sorted(new_ids)
            for description in SENSOR_DESCRIPTIONS
        )

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class LGSoundbarHealthSensor(LGSoundbarHealthEntity, SensorEntity):
    """Diagnostic sensor for LG Soundbars Health."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    entity_description: HealthSensorDescription

    def __init__(self, coordinator, source_entry_id: str, description: HealthSensorDescription) -> None:
        super().__init__(coordinator, source_entry_id)
        self.entity_description = description
        self._attr_unique_id = f"lg_soundbar_health_{source_entry_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return sensor native value."""
        state = self.health_state
        if state is None:
            return None
        value = self.entity_description.value_fn(state)
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) or callable(value):
            return ha_safe_text(value)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value
        # Do not let accidental objects/functions leak into HA state as repr(...).
        return None
