"""Buttons for LG Soundbars Health."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Awaitable, Callable

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LGSoundbarHealthCoordinator
from .const import DATA_COORDINATOR, DOMAIN
from .entity import LGSoundbarHealthEntity


class HealthButtonKey(StrEnum):
    """Health button keys."""

    CHECK_NOW = "check_now"
    RESET_INITIAL_IP = "reset_initial_ip"
    RELOAD_PARENT = "reload_lg_soundbar"


@dataclass(frozen=True, kw_only=True)
class HealthButtonDescription(ButtonEntityDescription):
    """Description for an LG Soundbar health button."""

    press_fn: Callable[[LGSoundbarHealthCoordinator, str], Awaitable[None]]


async def _check_now(coordinator: LGSoundbarHealthCoordinator, source_entry_id: str) -> None:
    """Force a health refresh."""
    await coordinator.async_request_refresh()


async def _reset_initial_ip(coordinator: LGSoundbarHealthCoordinator, source_entry_id: str) -> None:
    """Reset the initial IP snapshot and refresh health data."""
    await coordinator.async_reset_initial_endpoint(source_entry_id)


async def _reload_parent(coordinator: LGSoundbarHealthCoordinator, source_entry_id: str) -> None:
    """Reload the source LG Soundbar config entry."""
    await coordinator.async_reload_parent(source_entry_id, reason="manual")


BUTTON_DESCRIPTIONS: tuple[HealthButtonDescription, ...] = (
    HealthButtonDescription(
        key=HealthButtonKey.CHECK_NOW,
        name="Check now",
        icon="mdi:refresh-circle",
        press_fn=_check_now,
    ),
    HealthButtonDescription(
        key=HealthButtonKey.RESET_INITIAL_IP,
        name="Reset initial IP",
        icon="mdi:backup-restore",
        press_fn=_reset_initial_ip,
    ),
    HealthButtonDescription(
        key=HealthButtonKey.RELOAD_PARENT,
        name="Reload LG Soundbar",
        icon="mdi:restart",
        press_fn=_reload_parent,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up LG Soundbars Health buttons."""
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    known_ids: set[str] = set()

    def add_new_entities() -> None:
        new_ids = set(coordinator.data) - known_ids
        if not new_ids:
            return
        known_ids.update(new_ids)
        async_add_entities(
            LGSoundbarHealthButton(coordinator, source_entry_id, description)
            for source_entry_id in sorted(new_ids)
            for description in BUTTON_DESCRIPTIONS
        )

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class LGSoundbarHealthButton(LGSoundbarHealthEntity, ButtonEntity):
    """Button for LG Soundbars Health."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    entity_description: HealthButtonDescription

    def __init__(
        self,
        coordinator: LGSoundbarHealthCoordinator,
        source_entry_id: str,
        description: HealthButtonDescription,
    ) -> None:
        super().__init__(coordinator, source_entry_id)
        self.entity_description = description
        self._attr_unique_id = f"lg_soundbar_health_{source_entry_id}_{description.key}"

    async def async_press(self) -> None:
        """Run the button action."""
        await self.entity_description.press_fn(self.coordinator, self._source_entry_id)
