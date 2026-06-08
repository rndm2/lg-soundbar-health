"""Switches for LG Soundbars Health."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HealthState, LGSoundbarHealthCoordinator
from .const import DATA_COORDINATOR, DOMAIN
from .entity import LGSoundbarHealthEntity


class HealthSwitchKey(StrEnum):
    """Health switch keys."""

    AUTO_RELOAD_PARENT = "auto_reload_lg_soundbar"


@dataclass(frozen=True, kw_only=True)
class HealthSwitchDescription(SwitchEntityDescription):
    """Description for an LG Soundbar health switch."""

    value_fn: Callable[[HealthState], bool]


SWITCH_DESCRIPTIONS: tuple[HealthSwitchDescription, ...] = (
    HealthSwitchDescription(
        key=HealthSwitchKey.AUTO_RELOAD_PARENT,
        name="Auto reload LG Soundbar",
        icon="mdi:auto-fix",
        value_fn=lambda state: state.auto_reload_enabled,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up LG Soundbars Health switches."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    known_ids: set[str] = set()

    def add_new_entities() -> None:
        new_ids = set(coordinator.data) - known_ids
        if not new_ids:
            return
        known_ids.update(new_ids)
        async_add_entities(
            LGSoundbarHealthSwitch(coordinator, source_entry_id, description)
            for source_entry_id in sorted(new_ids)
            for description in SWITCH_DESCRIPTIONS
        )

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class LGSoundbarHealthSwitch(LGSoundbarHealthEntity, SwitchEntity):
    """Switch for LG Soundbars Health."""

    _attr_entity_category = EntityCategory.CONFIG

    entity_description: HealthSwitchDescription

    def __init__(
        self,
        coordinator: LGSoundbarHealthCoordinator,
        source_entry_id: str,
        description: HealthSwitchDescription,
    ) -> None:
        super().__init__(coordinator, source_entry_id)
        self.entity_description = description
        self._attr_unique_id = f"lg_soundbar_health_{source_entry_id}_{description.key}"

    @property
    def is_on(self) -> bool | None:
        """Return switch state."""
        state = self.health_state
        if state is None:
            return None
        return self.entity_description.value_fn(state)

    async def async_turn_on(self, **kwargs) -> None:
        """Enable automatic parent reload."""
        await self.coordinator.async_set_auto_reload(self._source_entry_id, True)

    async def async_turn_off(self, **kwargs) -> None:
        """Disable automatic parent reload."""
        await self.coordinator.async_set_auto_reload(self._source_entry_id, False)
