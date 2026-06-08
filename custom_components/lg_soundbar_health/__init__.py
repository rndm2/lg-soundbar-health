"""LG Soundbars Health custom integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
import socket
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.storage import Store

from .const import (
    DATA_COORDINATOR,
    DEFAULT_AUTO_RELOAD_INITIAL_FAILURES,
    DEFAULT_PARENT_RELOAD_COOLDOWN,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    CONF_SCAN_INTERVAL_SECONDS,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT,
    DOMAIN,
    SOURCE_DOMAIN,
    STORAGE_AUTO_RELOAD_ENABLED,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

MAX_STATE_LENGTH = 255


def ha_safe_text(value: Any, *, fallback: str | None = None) -> str | None:
    """Return a Home Assistant state-safe text value.

    Sensors states must be short scalar values. If a callable/function or other
    accidental object reaches a text field, expose unknown instead of its repr.
    """
    if value is None:
        return fallback
    if callable(value):
        return fallback
    if not isinstance(value, str):
        return fallback
    if value == "":
        return fallback
    if len(value) <= MAX_STATE_LENGTH:
        return value
    return f"{value[: MAX_STATE_LENGTH - 1]}…"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.SWITCH,
]

LGSoundbarHealthConfigEntry = ConfigEntry


@dataclass(frozen=True, slots=True)
class SoundbarTarget:
    """A target discovered from an existing LG Soundbar config entry."""

    source_entry_id: str
    name: str
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class ResolvedEndpoint:
    """Resolved network endpoint used for a TCP health check."""

    ip_address: str
    family: socket.AddressFamily


@dataclass(slots=True)
class InitialEndpoint:
    """Frozen IP snapshot for one source LG Soundbar config entry."""

    host: str
    port: int
    ip_address: str | None = None
    family: socket.AddressFamily | None = None
    captured_at: datetime | None = None
    error: str | None = None


@dataclass(slots=True)
class HealthState:
    """Runtime health state for one soundbar."""

    target: SoundbarTarget
    connected: bool = False
    response_time_ms: float | None = None
    checked_at: datetime | None = None
    last_success: datetime | None = None
    last_failure: datetime | None = None
    offline_since: datetime | None = None
    failure_count: int = 0
    last_error: str | None = None
    resolved_ip: str | None = None
    initial_ip: str | None = None
    initial_ip_captured_at: datetime | None = None
    initial_ip_error: str | None = None
    initial_ip_connected: bool | None = None
    initial_ip_response_time_ms: float | None = None
    initial_ip_last_error: str | None = None
    initial_ip_failure_count: int = 0
    auto_reload_enabled: bool = False
    last_parent_reload: datetime | None = None
    parent_reload_count: int = 0
    parent_reload_last_error: str | None = None
    parent_reload_in_progress: bool = False
    parent_reload_last_reason: str | None = None

    @property
    def offline_duration_seconds(self) -> int:
        """Return current offline duration in seconds."""
        if self.connected or self.offline_since is None:
            return 0
        return max(0, int((datetime.now(UTC) - self.offline_since).total_seconds()))

    @property
    def ip_changed(self) -> bool | None:
        """Return whether current DNS resolution differs from the initial IP."""
        if self.initial_ip is None or self.resolved_ip is None:
            return None
        return self.initial_ip != self.resolved_ip

    @property
    def auto_reload_ready(self) -> bool:
        """Return whether the current state satisfies the auto-reload condition."""
        return (
            self.auto_reload_enabled
            and self.ip_changed is True
            and self.connected is True
            and self.initial_ip_connected is False
            and self.initial_ip_failure_count >= DEFAULT_AUTO_RELOAD_INITIAL_FAILURES
            and not self.parent_reload_in_progress
        )


class LGSoundbarHealthCoordinator(DataUpdateCoordinator[dict[str, HealthState]]):
    """Coordinator that checks TCP reachability for existing LG soundbars."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        scan_interval_seconds = _parse_scan_interval_seconds(
            config_entry.options.get(CONF_SCAN_INTERVAL_SECONDS),
            DEFAULT_SCAN_INTERVAL_SECONDS,
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval_seconds),
        )
        self._config_entry = config_entry
        self._states: dict[str, HealthState] = {}
        self._initial_endpoints: dict[str, InitialEndpoint] = {}
        self._source_state_unsub: dict[str, Any] = {}
        self._parent_reload_tasks: set[asyncio.Task[Any]] = set()
        self._store: Store[dict[str, dict[str, bool]]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._auto_reload_enabled: dict[str, bool] = {}

    async def async_load_storage(self) -> None:
        """Load persisted per-source switch state."""
        stored = await self._store.async_load()
        raw_values = (stored or {}).get(STORAGE_AUTO_RELOAD_ENABLED, {})
        if not isinstance(raw_values, dict):
            self._auto_reload_enabled = {}
            return

        self._auto_reload_enabled = {
            str(source_entry_id): bool(enabled)
            for source_entry_id, enabled in raw_values.items()
            if source_entry_id
        }

    async def _async_save_storage(self) -> None:
        """Persist per-source switch state."""
        await self._store.async_save(
            {STORAGE_AUTO_RELOAD_ENABLED: dict(self._auto_reload_enabled)}
        )

    def discover_targets(self) -> list[SoundbarTarget]:
        """Discover LG Soundbar config entries and turn them into health targets."""
        targets: list[SoundbarTarget] = []

        for source_entry in self.hass.config_entries.async_entries(SOURCE_DOMAIN):
            host = str(source_entry.data.get(CONF_HOST, "")).strip()
            if not host:
                _LOGGER.debug(
                    "Skipping LG Soundbar entry %s because it has no host",
                    source_entry.entry_id,
                )
                continue

            self._ensure_source_state_listener(source_entry)

            port = _parse_port(source_entry.data.get(CONF_PORT), DEFAULT_PORT)
            name = str(source_entry.title or source_entry.data.get(CONF_NAME) or host)

            targets.append(
                SoundbarTarget(
                    source_entry_id=source_entry.entry_id,
                    name=name,
                    host=host,
                    port=port,
                )
            )

        return targets

    @callback
    def _ensure_source_state_listener(self, source_entry: ConfigEntry) -> None:
        """Track source entry reloads so the frozen initial IP can be refreshed."""
        if source_entry.entry_id in self._source_state_unsub:
            return

        @callback
        def _source_state_changed(*_: Any) -> None:
            if source_entry.state is ConfigEntryState.LOADED:
                _LOGGER.debug(
                    "LG Soundbar source entry %s loaded; refreshing initial IP snapshot",
                    source_entry.entry_id,
                )
                self._initial_endpoints.pop(source_entry.entry_id, None)
                self.hass.async_create_task(self.async_request_refresh())

        self._source_state_unsub[source_entry.entry_id] = source_entry.async_on_state_change(
            _source_state_changed
        )

    async def _async_update_data(self) -> dict[str, HealthState]:
        """Check all discovered soundbars."""
        targets = self.discover_targets()
        current_ids = {target.source_entry_id for target in targets}

        for stale_id in set(self._states) - current_ids:
            self._states.pop(stale_id, None)
            self._initial_endpoints.pop(stale_id, None)
            if unsub := self._source_state_unsub.pop(stale_id, None):
                unsub()

        if targets:
            await asyncio.gather(*(self._check_target(target) for target in targets))

        return dict(self._states)

    async def _check_target(self, target: SoundbarTarget) -> None:
        """Check one target by resolving its host and opening TCP connections."""
        state = self._states.setdefault(target.source_entry_id, HealthState(target=target))
        state.target = target
        state.auto_reload_enabled = self._auto_reload_enabled.get(target.source_entry_id, False)

        checked_at = datetime.now(UTC)
        current_endpoint: ResolvedEndpoint | None = None

        try:
            state.resolved_ip = None
            started = time.perf_counter()
            current_endpoint = await asyncio.wait_for(
                self._resolve_host(target.host, target.port), timeout=DEFAULT_TIMEOUT
            )
            state.resolved_ip = current_endpoint.ip_address
            await self._open_tcp_connection(current_endpoint.ip_address, target.port, current_endpoint.family)
        except Exception as err:  # noqa: BLE001 - a health check must not break polling
            _mark_failure(state, checked_at, err)
        else:
            state.connected = True
            state.response_time_ms = round((time.perf_counter() - started) * 1000, 1)
            state.checked_at = checked_at
            state.last_success = checked_at
            state.last_error = None
            state.failure_count = 0
            state.offline_since = None

        initial_endpoint = await self._async_get_initial_endpoint(target, current_endpoint, checked_at)
        state.initial_ip = initial_endpoint.ip_address
        state.initial_ip_captured_at = initial_endpoint.captured_at
        state.initial_ip_error = initial_endpoint.error

        if initial_endpoint.ip_address is None or initial_endpoint.family is None:
            state.initial_ip_connected = None
            state.initial_ip_response_time_ms = None
            state.initial_ip_last_error = initial_endpoint.error
            state.initial_ip_failure_count = 0
            return

        try:
            started = time.perf_counter()
            await self._open_tcp_connection(
                initial_endpoint.ip_address,
                initial_endpoint.port,
                initial_endpoint.family,
            )
        except Exception as err:  # noqa: BLE001 - diagnostic only
            state.initial_ip_connected = False
            state.initial_ip_response_time_ms = None
            state.initial_ip_last_error = _format_error(err)
            state.initial_ip_failure_count += 1
        else:
            state.initial_ip_connected = True
            state.initial_ip_response_time_ms = round((time.perf_counter() - started) * 1000, 1)
            state.initial_ip_last_error = None
            state.initial_ip_failure_count = 0

        self._maybe_schedule_auto_reload(state)

    async def _async_get_initial_endpoint(
        self,
        target: SoundbarTarget,
        current_endpoint: ResolvedEndpoint | None,
        checked_at: datetime,
    ) -> InitialEndpoint:
        """Return or create the frozen initial IP snapshot for a target."""
        existing = self._initial_endpoints.get(target.source_entry_id)
        if existing is not None and existing.host == target.host and existing.port == target.port:
            if existing.ip_address is not None:
                return existing
            # Retry after a failed initial resolution, but do not overwrite a
            # successful snapshot until the source entry is reloaded or host/port changes.

        if current_endpoint is not None:
            endpoint = InitialEndpoint(
                host=target.host,
                port=target.port,
                ip_address=current_endpoint.ip_address,
                family=current_endpoint.family,
                captured_at=checked_at,
                error=None,
            )
            self._initial_endpoints[target.source_entry_id] = endpoint
            return endpoint

        try:
            resolved = await asyncio.wait_for(
                self._resolve_host(target.host, target.port), timeout=DEFAULT_TIMEOUT
            )
        except Exception as err:  # noqa: BLE001 - diagnostic only
            endpoint = InitialEndpoint(
                host=target.host,
                port=target.port,
                ip_address=None,
                family=None,
                captured_at=checked_at,
                error=_format_error(err),
            )
            self._initial_endpoints[target.source_entry_id] = endpoint
            return endpoint

        endpoint = InitialEndpoint(
            host=target.host,
            port=target.port,
            ip_address=resolved.ip_address,
            family=resolved.family,
            captured_at=checked_at,
            error=None,
        )
        self._initial_endpoints[target.source_entry_id] = endpoint
        return endpoint

    async def async_reset_initial_endpoint(self, source_entry_id: str) -> None:
        """Reset the frozen initial IP snapshot for one source entry."""
        self._initial_endpoints.pop(source_entry_id, None)
        await self.async_request_refresh()

    async def async_set_auto_reload(self, source_entry_id: str, enabled: bool) -> None:
        """Enable or disable automatic parent integration reload for one source entry."""
        self._auto_reload_enabled[source_entry_id] = enabled
        state = self._states.get(source_entry_id)
        if state is not None:
            state.auto_reload_enabled = enabled
            self.async_set_updated_data(dict(self._states))
        await self._async_save_storage()

    async def async_reload_parent(self, source_entry_id: str, reason: str = "manual") -> None:
        """Reload the parent LG Soundbar config entry."""
        state = self._states.get(source_entry_id)
        if state is None:
            return

        if state.parent_reload_in_progress:
            _LOGGER.debug(
                "Skipping LG Soundbar parent reload for %s because a reload is already in progress",
                source_entry_id,
            )
            return

        source_entry = self._get_source_entry(source_entry_id)
        if source_entry is None:
            state.parent_reload_last_error = "Source LG Soundbar config entry not found"
            self.async_set_updated_data(dict(self._states))
            return

        state.parent_reload_in_progress = True
        state.parent_reload_last_reason = ha_safe_text(reason, fallback="unknown") or "unknown"
        state.parent_reload_last_error = None
        state.last_parent_reload = datetime.now(UTC)
        state.parent_reload_count += 1
        self.async_set_updated_data(dict(self._states))

        try:
            reload_result = await self.hass.config_entries.async_reload(source_entry.entry_id)
        except Exception as err:  # noqa: BLE001 - reload failures must stay diagnostic
            state.parent_reload_last_error = _format_error(err)
            _LOGGER.warning(
                "Failed to reload LG Soundbar source entry %s: %s",
                source_entry.entry_id,
                err,
            )
        else:
            if reload_result is False:
                state.parent_reload_last_error = "Home Assistant returned false while reloading source config entry"
            else:
                state.parent_reload_last_error = None
                self._initial_endpoints.pop(source_entry.entry_id, None)
        finally:
            state.parent_reload_in_progress = False
            self.async_set_updated_data(dict(self._states))
            await self.async_request_refresh()

    def _maybe_schedule_auto_reload(self, state: HealthState) -> None:
        """Schedule a parent reload if the guarded auto-reload condition is met."""
        if not state.auto_reload_ready:
            return

        now = datetime.now(UTC)
        if state.last_parent_reload is not None:
            elapsed = now - state.last_parent_reload
            if elapsed < DEFAULT_PARENT_RELOAD_COOLDOWN:
                return

        task = self.hass.async_create_task(
            self.async_reload_parent(state.target.source_entry_id, reason="auto_ip_changed")
        )
        self._parent_reload_tasks.add(task)
        task.add_done_callback(self._parent_reload_tasks.discard)

    def _get_source_entry(self, source_entry_id: str) -> ConfigEntry | None:
        """Return a source LG Soundbar config entry by entry id."""
        for source_entry in self.hass.config_entries.async_entries(SOURCE_DOMAIN):
            if source_entry.entry_id == source_entry_id:
                return source_entry
        return None

    async def _open_tcp_connection(
        self,
        ip_address: str,
        port: int,
        family: socket.AddressFamily,
    ) -> None:
        """Open and immediately close a TCP connection to an endpoint."""
        writer: asyncio.StreamWriter | None = None
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host=ip_address, port=port, family=family),
                timeout=DEFAULT_TIMEOUT,
            )
        finally:
            if writer is not None:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), timeout=DEFAULT_TIMEOUT)
                except Exception as err:  # noqa: BLE001 - close errors are diagnostic only
                    _LOGGER.debug(
                        "Error while closing LG Soundbars Health socket for %s:%s: %s",
                        ip_address,
                        port,
                        err,
                    )

    async def _resolve_host(self, host: str, port: int) -> ResolvedEndpoint:
        """Resolve host to an IP address.

        Current resolution is done on every health check so DHCP/DNS changes are visible.
        IPv4 is preferred because LG soundbars on home LANs normally expose control
        ports on IPv4. IPv6 is still supported when no IPv4 address is returned.
        """
        addr_info = await self.hass.async_add_executor_job(
            socket.getaddrinfo,
            host,
            port,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
        if not addr_info:
            raise OSError(f"Could not resolve host: {host}")

        for family, _type, _proto, _canonname, sockaddr in addr_info:
            if family == socket.AF_INET:
                return ResolvedEndpoint(ip_address=str(sockaddr[0]), family=family)

        family, _type, _proto, _canonname, sockaddr = addr_info[0]
        return ResolvedEndpoint(ip_address=str(sockaddr[0]), family=family)

    def async_shutdown(self) -> None:
        """Unsubscribe from source entry listeners."""
        for unsub in self._source_state_unsub.values():
            unsub()
        self._source_state_unsub.clear()
        for task in self._parent_reload_tasks:
            task.cancel()
        self._parent_reload_tasks.clear()


async def async_setup_entry(hass: HomeAssistant, entry: LGSoundbarHealthConfigEntry) -> bool:
    """Set up LG Soundbars Health from a config entry."""
    coordinator = LGSoundbarHealthCoordinator(hass, entry)
    await coordinator.async_load_storage()
    await coordinator.async_config_entry_first_refresh()

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {DATA_COORDINATOR: coordinator}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: LGSoundbarHealthConfigEntry) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: LGSoundbarHealthConfigEntry) -> bool:
    """Unload LG Soundbars Health."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if data and (coordinator := data.get(DATA_COORDINATOR)):
            coordinator.async_shutdown()
    return unload_ok


def _parse_scan_interval_seconds(raw_value: Any, fallback: int) -> int:
    """Parse and clamp the health check interval in seconds."""
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return fallback

    return min(MAX_SCAN_INTERVAL_SECONDS, max(MIN_SCAN_INTERVAL_SECONDS, value))


def _parse_port(raw_port: Any, fallback: int) -> int:
    """Parse and validate a TCP port."""
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        return fallback

    if 1 <= port <= 65535:
        return port
    return fallback


def _mark_failure(state: HealthState, checked_at: datetime, err: Exception) -> None:
    """Update state after a failed current-DNS health check."""
    state.connected = False
    state.response_time_ms = None
    state.checked_at = checked_at
    state.last_failure = checked_at
    state.failure_count += 1
    state.last_error = _format_error(err)
    if state.offline_since is None:
        state.offline_since = checked_at


def _format_error(err: Exception) -> str:
    """Return an HA-safe error string for use as a sensor state."""
    message = str(err) or err.__class__.__name__
    return ha_safe_text(message, fallback=err.__class__.__name__) or err.__class__.__name__
