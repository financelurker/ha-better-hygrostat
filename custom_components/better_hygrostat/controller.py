"""Control logic of Better Hygrostat.

One controller per room (config entry). It reads the sensors, decides which device should
run, switches it and keeps track of maintenance and problem states ("issues").
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
import logging
import statistics
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from . import physics
from .const import (
    CONF_CHANGEOVER_LOCK,
    CONF_CLEANING_INTERVAL,
    CONF_CONDENSATION_LIMIT,
    CONF_CONDENSATION_OFFSET,
    CONF_DEHUMIDIFIER,
    CONF_DEHUMIDIFIER_POWER,
    CONF_DEHUMIDIFIER_POWER_MIN,
    CONF_DEHUMIDIFIER_TANK_SENSOR,
    CONF_DRY_TOLERANCE,
    CONF_HEATING_LIMIT,
    CONF_HUMIDIFIER,
    CONF_HUMIDIFIER_POWER,
    CONF_HUMIDIFIER_POWER_MIN,
    CONF_HUMIDITY_SENSOR,
    CONF_MIN_OFF,
    CONF_MIN_ON,
    CONF_OUTDOOR_HUMIDITY,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_SEASON_BAND,
    CONF_SEASON_METHOD,
    CONF_SENSOR_STALE,
    CONF_TANK_BLOCK,
    CONF_TANK_DETECTION,
    CONF_TANK_MIN_RUNTIME,
    CONF_TANK_SLOPE,
    CONF_TANK_WINDOW,
    CONF_TARGET_HIGH,
    CONF_TARGET_LOW,
    CONF_TEMPERATURE_SENSOR,
    CONF_WEATHER,
    CONF_WET_TOLERANCE,
    CONF_WINDOW_CLOSE_DELAY,
    CONF_WINDOW_OPEN_DELAY,
    CONF_WINDOWS,
    DEFAULTS,
    DOMAIN,
    ISSUE_CLEANING,
    ISSUE_DEHUM_FAULT,
    ISSUE_DEHUM_TANK,
    ISSUE_HUM_FAULT,
    ISSUE_REFILL,
    ISSUE_STORAGE,
    ISSUES,
    MODE_AUTO,
    MODE_DEHUMIDIFY,
    MODE_HUMIDIFY,
    ORIGIN_AUTO,
    OVERRIDE_AUTO,
    OVERRIDE_OFF,
    OVERRIDE_ON,
    POWER_GRACE_SECONDS,
    SEASON_ALWAYS,
    SEASON_AUTO,
    SEASON_EQUIVALENT,
    SEASON_HEATING_LIMIT,
    STATUS_DEHUMIDIFYING,
    STATUS_HUMIDIFYING,
    STATUS_IDLE,
    STATUS_OFF,
    STATUS_SEASON_INACTIVE,
    STATUS_SENSOR_ERROR,
    STATUS_TANK_EMPTY,
    STATUS_WINDOW_OPEN,
    STORAGE_VERSION,
    TICK_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

OUTDOOR_SAMPLE_SECONDS = 600  # one outdoor sample every 10 min for the 24 h mean
OUTDOOR_HISTORY_SECONDS = 24 * 3600
TANK_SAMPLE_SECONDS = 60
TANK_CLEAR_WINDOW_SECONDS = 30 * 60
COMMAND_RETRY_SECONDS = 60
REFILL_HISTORY_MAX = 10

IssueListener = Callable[[str, bool, str], None]


def _now() -> float:
    return dt_util.utcnow().timestamp()


def _float_state(state: State | None) -> float | None:
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN, ""):
        return None
    try:
        return float(state.state)
    except TypeError, ValueError:
        return None


def _to_celsius(value: float | None, unit: str | None) -> float | None:
    if value is None:
        return None
    if unit in (None, "", UnitOfTemperature.CELSIUS):
        return value
    try:
        return TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
    except Exception:  # unknown unit: keep the value
        return value


@dataclass
class ControlledDevice:
    """A switched device (plug or humidifier entity)."""

    entity_id: str
    power_entity: str | None
    power_min: float
    is_dehumidifier: bool
    tank_sensor: str | None = None
    # runtime data (not persisted)
    on_since: float | None = None
    off_since: float | None = None
    last_off: float | None = None
    powered_this_run: bool = False
    low_power_since: float | None = None
    last_command: tuple[bool, float] | None = None
    extra: dict = field(default_factory=dict)

    @property
    def domain(self) -> str:
        """Return the domain of the switched entity."""
        return self.entity_id.split(".", 1)[0]


class HygrostatController:
    """The brain of one room."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialise."""
        self.hass = hass
        self.entry = entry
        self.opts: dict[str, Any] = {**DEFAULTS, **entry.data, **entry.options}
        o = self.opts

        self.humidifier = ControlledDevice(
            entity_id=o[CONF_HUMIDIFIER],
            power_entity=o.get(CONF_HUMIDIFIER_POWER),
            power_min=float(o[CONF_HUMIDIFIER_POWER_MIN]),
            is_dehumidifier=False,
        )
        self.dehumidifier: ControlledDevice | None = None
        if o.get(CONF_DEHUMIDIFIER):
            self.dehumidifier = ControlledDevice(
                entity_id=o[CONF_DEHUMIDIFIER],
                power_entity=o.get(CONF_DEHUMIDIFIER_POWER),
                power_min=float(o[CONF_DEHUMIDIFIER_POWER_MIN]),
                is_dehumidifier=True,
                tank_sensor=o.get(CONF_DEHUMIDIFIER_TANK_SENSOR),
            )

        self.windows: list[str] = list(o.get(CONF_WINDOWS) or [])
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.data: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._unsubs: list[Callable[[], None]] = []
        self._window_timer: Callable[[], None] | None = None
        self._listeners: list[Callable[[], None]] = []
        self._issue_listeners: list[IssueListener] = []
        self._started = False

        # readings (refreshed on every evaluation)
        self.humidity: float | None = None
        self.temperature: float | None = None
        self.abs_humidity: float | None = None
        self.dew_point: float | None = None
        self.outdoor_temperature: float | None = None
        self.outdoor_humidity: float | None = None
        self.outdoor_abs_humidity: float | None = None
        self.outdoor_equivalent: float | None = None
        self.condensation_limit: float | None = None
        self.sensor_ok = False
        self.status = STATUS_OFF
        self.tank_slope: float | None = None

        # windows
        self.window_raw_open = False
        self.window_raw_since: float = _now()
        self.window_open = False

        self._last_account: float | None = None
        self._last_running: dict[str, bool] = {"hum": False, "dehum": False}
        self._tank_samples: list[tuple[float, float]] = []
        self._tank_reset_at: float = _now()

    # ------------------------------------------------------------------ setup

    @property
    def has_dehumidifier(self) -> bool:
        """Return whether a dehumidifier is configured."""
        return self.dehumidifier is not None

    @property
    def has_outdoor(self) -> bool:
        """Return whether an outdoor temperature source is configured."""
        o = self.opts
        return bool(o.get(CONF_OUTDOOR_TEMPERATURE) or o.get(CONF_WEATHER))

    @property
    def has_outdoor_humidity(self) -> bool:
        """Return whether outdoor temperature and humidity are available."""
        o = self.opts
        return bool(
            (o.get(CONF_OUTDOOR_TEMPERATURE) and o.get(CONF_OUTDOOR_HUMIDITY))
            or o.get(CONF_WEATHER)
        )

    async def async_start(self) -> None:
        """Load stored data, subscribe to events and start evaluating."""
        stored = await self._store.async_load() or {}
        self.data = {
            "enabled": True,
            "mode": MODE_AUTO,
            "target_low": float(self.opts[CONF_TARGET_LOW]),
            "target_high": float(self.opts[CONF_TARGET_HIGH]),
            "season_override": OVERRIDE_AUTO,
            "season_active": None,
            "season_runtime_s": 0.0,
            "outdoor_samples": [],  # [ts, t_out, eq|None]
            "hum_total_s": 0.0,
            "hum_since_refill_s": 0.0,
            "hum_since_clean_s": 0.0,
            "dehum_total_s": 0.0,
            "refill_history_h": [],
            "issues": {},
            "hk_tasks": {},
            **stored,
        }
        # Take targets from the options only when they were changed there
        # (otherwise the value last set on the hygrostat entity wins).
        for key, opt in (("target_low", CONF_TARGET_LOW), ("target_high", CONF_TARGET_HIGH)):
            configured = float(self.opts[opt])
            if self.data.get(f"cfg_{key}") != configured:
                self.data[key] = configured
                self.data[f"cfg_{key}"] = configured
        for key in ISSUES:
            self.data["issues"].setdefault(key, {"active": False, "since": None, "reason": None})

        tracked = [
            self.opts[CONF_HUMIDITY_SENSOR],
            self.opts[CONF_TEMPERATURE_SENSOR],
            *self.windows,
            *[
                e
                for e in (
                    self.opts.get(CONF_OUTDOOR_TEMPERATURE),
                    self.opts.get(CONF_OUTDOOR_HUMIDITY),
                    self.opts.get(CONF_WEATHER),
                )
                if e
            ],
        ]
        for dev in self._devices():
            tracked.append(dev.entity_id)
            if dev.power_entity:
                tracked.append(dev.power_entity)
            if dev.tank_sensor:
                tracked.append(dev.tank_sensor)

        self._unsubs.append(
            async_track_state_change_event(self.hass, tracked, self._on_state_event)
        )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._on_tick, timedelta(seconds=TICK_SECONDS))
        )

        now = _now()
        for dev in self._devices():
            state = self.hass.states.get(dev.entity_id)
            if state is not None and state.state == STATE_ON:
                dev.on_since = now
            else:
                dev.off_since = now - 24 * 3600  # do not block the minimum off time
        self.window_raw_open = self._read_window_raw()
        self.window_open = self.window_raw_open
        self.window_raw_since = now - 24 * 3600

        @callback
        def _started(_hass: HomeAssistant) -> None:
            self._started = True
            self.hass.async_create_task(self.async_update("start"))

        self._unsubs.append(async_at_started(self.hass, _started))

    async def async_stop(self) -> None:
        """Unsubscribe and save the data."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._window_timer:
            self._window_timer()
            self._window_timer = None
        await self._store.async_save(self.data)

    def _devices(self) -> list[ControlledDevice]:
        return [d for d in (self.humidifier, self.dehumidifier) if d is not None]

    # ----------------------------------------------------------- listeners

    @callback
    def async_add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for state updates."""
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    @callback
    def async_add_issue_listener(self, cb: IssueListener) -> Callable[[], None]:
        """Register a callback for raised and resolved issues."""
        self._issue_listeners.append(cb)
        return lambda: self._issue_listeners.remove(cb)

    @callback
    def _notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    @callback
    def _schedule_save(self) -> None:
        self._store.async_delay_save(lambda: self.data, 30)

    # -------------------------------------------------------------- events

    @callback
    def _on_state_event(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        new = event.data["new_state"]
        old = event.data["old_state"]
        now = _now()
        for dev in self._devices():
            if entity_id == dev.entity_id:
                was_on = old is not None and old.state == STATE_ON
                is_on = new is not None and new.state == STATE_ON
                if is_on and not was_on:
                    dev.on_since = now
                    dev.off_since = None
                    dev.powered_this_run = False
                    dev.low_power_since = None
                elif was_on and not is_on:
                    dev.off_since = now
                    dev.last_off = now
                    dev.on_since = None
        if entity_id in self.windows:
            raw = self._read_window_raw()
            if raw != self.window_raw_open:
                self.window_raw_open = raw
                self.window_raw_since = now
                if raw:
                    self._reset_tank_samples(now)
                delay = (
                    self.opts[CONF_WINDOW_OPEN_DELAY] if raw else self.opts[CONF_WINDOW_CLOSE_DELAY]
                )
                if self._window_timer:
                    self._window_timer()

                @callback
                def _fire(_now_dt: Any) -> None:
                    self._window_timer = None
                    self.hass.async_create_task(self.async_update("window_delay"))

                self._window_timer = async_call_later(self.hass, float(delay) + 0.5, _fire)
        if self._started:
            self.hass.async_create_task(self.async_update(entity_id))

    @callback
    def _on_tick(self, _now_dt: Any) -> None:
        if self._started:
            self.hass.async_create_task(self.async_update("tick"))

    # ------------------------------------------------------------- reading

    def _read_window_raw(self) -> bool:
        for entity_id in self.windows:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state == STATE_ON:
                return True
        return False

    def _read_inputs(self, now: float) -> None:
        o = self.opts
        h_state = self.hass.states.get(o[CONF_HUMIDITY_SENSOR])
        t_state = self.hass.states.get(o[CONF_TEMPERATURE_SENSOR])
        self.humidity = _float_state(h_state)
        self.temperature = _to_celsius(
            _float_state(t_state),
            t_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if t_state else None,
        )

        stale_min = float(o[CONF_SENSOR_STALE])
        stale = False
        if h_state is not None and stale_min > 0:
            reported = getattr(h_state, "last_reported", None) or h_state.last_updated
            stale = now - reported.timestamp() > stale_min * 60
        self.sensor_ok = self.humidity is not None and not stale

        if self.humidity is not None and self.temperature is not None:
            self.abs_humidity = physics.absolute_humidity(self.temperature, self.humidity)
            self.dew_point = physics.dew_point(self.temperature, self.humidity)
        else:
            self.abs_humidity = None
            self.dew_point = None

        # outdoor: dedicated sensors take precedence over the weather entity
        t_out = h_out = None
        if o.get(CONF_OUTDOOR_TEMPERATURE):
            st = self.hass.states.get(o[CONF_OUTDOOR_TEMPERATURE])
            t_out = _to_celsius(
                _float_state(st),
                st.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if st else None,
            )
        if o.get(CONF_OUTDOOR_HUMIDITY):
            h_out = _float_state(self.hass.states.get(o[CONF_OUTDOOR_HUMIDITY]))
        if o.get(CONF_WEATHER) and (t_out is None or h_out is None):
            ws = self.hass.states.get(o[CONF_WEATHER])
            if ws is not None and ws.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                if t_out is None and ws.attributes.get(ATTR_TEMPERATURE) is not None:
                    try:
                        t_out = _to_celsius(
                            float(ws.attributes[ATTR_TEMPERATURE]),
                            ws.attributes.get("temperature_unit"),
                        )
                    except TypeError, ValueError:
                        t_out = None
                if h_out is None and ws.attributes.get("humidity") is not None:
                    try:
                        h_out = float(ws.attributes["humidity"])
                    except TypeError, ValueError:
                        h_out = None
        self.outdoor_temperature = t_out
        self.outdoor_humidity = h_out
        if t_out is not None and h_out is not None:
            self.outdoor_abs_humidity = physics.absolute_humidity(t_out, h_out)
            indoor_t = self.temperature if self.temperature is not None else 21.0
            self.outdoor_equivalent = physics.equivalent_humidity(t_out, h_out, indoor_t)
        else:
            self.outdoor_abs_humidity = None
            self.outdoor_equivalent = None

        if o[CONF_CONDENSATION_LIMIT] and t_out is not None:
            self.condensation_limit = physics.condensation_limit(
                t_out, float(o[CONF_CONDENSATION_OFFSET])
            )
        else:
            self.condensation_limit = None

    def _power(self, dev: ControlledDevice) -> float | None:
        if not dev.power_entity:
            return None
        return _float_state(self.hass.states.get(dev.power_entity))

    def device_is_on(self, dev: ControlledDevice | None) -> bool:
        """Return whether the device is switched on."""
        if dev is None:
            return False
        state = self.hass.states.get(dev.entity_id)
        return state is not None and state.state == STATE_ON

    def device_available(self, dev: ControlledDevice) -> bool:
        """Return whether the device entity is available."""
        state = self.hass.states.get(dev.entity_id)
        return state is not None and state.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )

    def device_running(self, dev: ControlledDevice | None) -> bool:
        """Return whether the device really runs (power above threshold, else: switched on)."""
        if dev is None or not self.device_is_on(dev):
            return False
        power = self._power(dev)
        if power is None:
            return True
        return power >= dev.power_min

    # ---------------------------------------------------------- properties

    @property
    def enabled(self) -> bool:
        """Return whether control is enabled."""
        return bool(self.data.get("enabled", True))

    @property
    def mode(self) -> str:
        """Return the mode (always humidify without a dehumidifier)."""
        mode = self.data.get("mode", MODE_AUTO)
        if not self.has_dehumidifier:
            return MODE_HUMIDIFY
        return mode

    @property
    def target_low(self) -> float:
        """Return the humidify target."""
        return float(self.data["target_low"])

    @property
    def target_high(self) -> float:
        """Return the dehumidify-above threshold."""
        return float(self.data["target_high"])

    @property
    def effective_target_low(self) -> float:
        """Return the humidify target after the condensation limit."""
        target = self.target_low
        if self.condensation_limit is not None:
            target = min(target, self.condensation_limit)
        return target

    @property
    def season_active(self) -> bool:
        """Return whether the humidifying season is active."""
        override = self.data.get("season_override", OVERRIDE_AUTO)
        if override == OVERRIDE_ON:
            return True
        if override == OVERRIDE_OFF:
            return False
        active = self.data.get("season_active")
        return True if active is None else bool(active)

    def season_method(self) -> str:
        """Return the season method in use."""
        method = self.opts[CONF_SEASON_METHOD]
        if method == SEASON_AUTO:
            if self.has_outdoor_humidity:
                return SEASON_EQUIVALENT
            if self.has_outdoor:
                return SEASON_HEATING_LIMIT
            return SEASON_ALWAYS
        return method

    def outdoor_means(self) -> tuple[float | None, float | None]:
        """Return the 24 h means of outdoor temperature and equivalent humidity."""
        samples = self.data.get("outdoor_samples") or []
        temps = [s[1] for s in samples if s[1] is not None]
        eqs = [s[2] for s in samples if s[2] is not None]
        return (
            statistics.fmean(temps) if temps else None,
            statistics.fmean(eqs) if eqs else None,
        )

    def issue_active(self, key: str) -> bool:
        """Return whether an issue is active."""
        return bool(self.data["issues"].get(key, {}).get("active"))

    def issue(self, key: str) -> dict:
        """Return the state of an issue."""
        return self.data["issues"].get(key, {})

    def hours(self, key: str) -> float:
        """Return a stored runtime counter in hours."""
        return round(float(self.data.get(key, 0.0)) / 3600.0, 2)

    @property
    def typical_tank_runtime_h(self) -> float | None:
        """Return the median runtime per tank filling."""
        hist = self.data.get("refill_history_h") or []
        return round(statistics.median(hist), 1) if hist else None

    @property
    def ventilation_recommended(self) -> bool | None:
        """Return whether airing would dry the room for free."""
        if self.outdoor_abs_humidity is None or self.abs_humidity is None:
            return None
        if self.humidity is None:
            return None
        limit = self.target_high if self.has_dehumidifier else self.target_low + 10
        return self.humidity > limit and self.outdoor_abs_humidity < self.abs_humidity - 1.0

    # ------------------------------------------------------- user actions

    async def async_set_enabled(self, enabled: bool) -> None:
        """Enable or disable control."""
        self.data["enabled"] = enabled
        if not enabled:
            # Switch everything off once; afterwards the devices are left alone
            # (manual operation is possible).
            for dev in self._devices():
                if self.device_is_on(dev):
                    await self._command(dev, False)
        await self.async_update("enabled")

    async def async_set_mode(self, mode: str) -> None:
        """Set the mode."""
        self.data["mode"] = mode
        await self.async_update("mode")

    async def async_set_target_low(self, value: float) -> None:
        """Set the humidify target."""
        self.data["target_low"] = float(value)
        if self.target_high < value + 5:
            self.data["target_high"] = float(value) + 5
        await self.async_update("target_low")

    async def async_set_target_high(self, value: float) -> None:
        """Set the dehumidify-above threshold."""
        self.data["target_high"] = float(value)
        if self.target_low > value - 5:
            self.data["target_low"] = float(value) - 5
        await self.async_update("target_high")

    async def async_set_season_override(self, value: str) -> None:
        """Set the season override."""
        self.data["season_override"] = value
        await self.async_update("season_override")

    async def async_resolve(self, key: str, origin: str) -> None:
        """Mark an issue as resolved (button, Home Keeper or detected automatically)."""
        now = _now()
        if key == ISSUE_REFILL:
            if self.issue_active(ISSUE_REFILL):
                hist = list(self.data.get("refill_history_h") or [])
                hist.append(round(self.data["hum_since_refill_s"] / 3600.0, 2))
                self.data["refill_history_h"] = hist[-REFILL_HISTORY_MAX:]
            self.data["hum_since_refill_s"] = 0.0
            self._reset_tank_samples(now)
        elif key == ISSUE_CLEANING:
            self.data["hum_since_clean_s"] = 0.0
        self._clear_issue(key, origin)
        await self.async_update(f"resolve_{key}")

    # ----------------------------------------------------------- issues

    @callback
    def _raise_issue(self, key: str, reason: str) -> None:
        issue = self.data["issues"][key]
        if issue.get("active"):
            return
        issue.update({"active": True, "since": dt_util.utcnow().isoformat(), "reason": reason})
        _LOGGER.info("%s: issue '%s' raised (%s)", self.entry.title, key, reason)
        for cb in list(self._issue_listeners):
            cb(key, True, reason)

    @callback
    def _clear_issue(self, key: str, origin: str) -> None:
        issue = self.data["issues"][key]
        if not issue.get("active"):
            return
        issue.update({"active": False, "since": None, "reason": None})
        _LOGGER.info("%s: issue '%s' resolved (%s)", self.entry.title, key, origin)
        for cb in list(self._issue_listeners):
            cb(key, False, origin)

    # --------------------------------------------------------- evaluation

    async def async_update(self, reason: str = "") -> None:
        """Read the inputs, update all states and switch the devices."""
        async with self._lock:
            now = _now()
            self._read_inputs(now)
            self._update_window(now)
            self._account_runtime(now)
            self._sample_outdoor(now)
            self._update_season()
            self._check_power(now)
            self._check_tank(now)
            self._check_cleaning()
            want_hum, want_dehum = self._decide(now)
            if self.enabled:
                await self._apply(self.humidifier, want_hum, now)
                if self.dehumidifier is not None:
                    await self._apply(self.dehumidifier, want_dehum, now)
            self._schedule_save()
        self._notify()

    def _update_window(self, now: float) -> None:
        if not self.windows:
            self.window_open = False
            return
        elapsed = now - self.window_raw_since
        if self.window_raw_open and elapsed >= self.opts[CONF_WINDOW_OPEN_DELAY]:
            self.window_open = True
        elif not self.window_raw_open and elapsed >= self.opts[CONF_WINDOW_CLOSE_DELAY]:
            self.window_open = False

    def _account_runtime(self, now: float) -> None:
        if self._last_account is not None:
            dt = max(0.0, min(now - self._last_account, 600.0))
            if self._last_running["hum"]:
                for key in ("hum_total_s", "hum_since_refill_s", "hum_since_clean_s"):
                    self.data[key] = float(self.data.get(key, 0.0)) + dt
                if self.season_active:
                    self.data["season_runtime_s"] = (
                        float(self.data.get("season_runtime_s", 0.0)) + dt
                    )
            if self._last_running["dehum"]:
                self.data["dehum_total_s"] = float(self.data.get("dehum_total_s", 0.0)) + dt
        self._last_account = now
        self._last_running = {
            "hum": self.device_running(self.humidifier),
            "dehum": self.device_running(self.dehumidifier),
        }

    def _sample_outdoor(self, now: float) -> None:
        if self.outdoor_temperature is None:
            return
        samples: list = self.data.setdefault("outdoor_samples", [])
        if samples and now - samples[-1][0] < OUTDOOR_SAMPLE_SECONDS:
            return
        samples.append(
            [
                now,
                round(self.outdoor_temperature, 2),
                None if self.outdoor_equivalent is None else round(self.outdoor_equivalent, 1),
            ]
        )
        cutoff = now - OUTDOOR_HISTORY_SECONDS
        self.data["outdoor_samples"] = [s for s in samples if s[0] >= cutoff]

    def _update_season(self) -> None:
        method = self.season_method()
        prev = self.data.get("season_active")
        mean_t, mean_eq = self.outdoor_means()
        band = float(self.opts[CONF_SEASON_BAND])
        new = prev
        if method == SEASON_ALWAYS:
            new = True
        elif method == SEASON_EQUIVALENT and mean_eq is not None:
            limit = self.target_low
            if prev is None:
                new = mean_eq < limit
            elif prev and mean_eq > limit + band:
                new = False
            elif not prev and mean_eq < limit - band:
                new = True
        elif method == SEASON_HEATING_LIMIT and mean_t is not None:
            limit = float(self.opts[CONF_HEATING_LIMIT])
            if prev is None:
                new = mean_t < limit
            elif prev and mean_t > limit + 2.0:
                new = False
            elif not prev and mean_t < limit:
                new = True
        if new == prev:
            return
        self.data["season_active"] = new
        _LOGGER.info("%s: humidifying season %s", self.entry.title, "active" if new else "inactive")
        if prev is None:
            return  # first evaluation: create no maintenance tasks
        if new:
            self._clear_issue(ISSUE_STORAGE, ORIGIN_AUTO)
            self._raise_issue(ISSUE_CLEANING, "season_start")
            self.data["season_runtime_s"] = 0.0
        elif float(self.data.get("season_runtime_s", 0.0)) >= 3600:
            self._raise_issue(ISSUE_STORAGE, "season_end")

    def _check_power(self, now: float) -> None:
        for dev in self._devices():
            fault_key = ISSUE_DEHUM_FAULT if dev.is_dehumidifier else ISSUE_HUM_FAULT

            # dehumidifier with its own tank sensor
            if dev.is_dehumidifier and dev.tank_sensor:
                tank = self.hass.states.get(dev.tank_sensor)
                if tank is not None and tank.state == STATE_ON:
                    self._raise_issue(ISSUE_DEHUM_TANK, "sensor")
                elif tank is not None and tank.state not in (
                    STATE_UNAVAILABLE,
                    STATE_UNKNOWN,
                ):
                    self._clear_issue(ISSUE_DEHUM_TANK, ORIGIN_AUTO)

            if not dev.power_entity:
                continue
            power = self._power(dev)
            if not self.device_is_on(dev) or power is None:
                dev.low_power_since = None
                continue
            if power >= dev.power_min:
                dev.powered_this_run = True
                dev.low_power_since = None
                self._clear_issue(fault_key, ORIGIN_AUTO)
                if dev.is_dehumidifier and not dev.tank_sensor:
                    self._clear_issue(ISSUE_DEHUM_TANK, ORIGIN_AUTO)
                continue
            if dev.low_power_since is None:
                dev.low_power_since = now
            on_for = now - (dev.on_since or now)
            if now - dev.low_power_since < POWER_GRACE_SECONDS or on_for < POWER_GRACE_SECONDS:
                continue
            # dehumidifier: drew power and stopped -> tank full; never drew power -> fault
            if (
                dev.is_dehumidifier
                and not dev.tank_sensor
                and (dev.powered_this_run or self.issue_active(ISSUE_DEHUM_TANK))
            ):
                self._raise_issue(ISSUE_DEHUM_TANK, "power")
                continue
            if dev.is_dehumidifier and self.issue_active(ISSUE_DEHUM_TANK):
                continue
            self._raise_issue(fault_key, "no_power")

    def _reset_tank_samples(self, now: float) -> None:
        self._tank_samples = []
        self._tank_reset_at = now
        self.tank_slope = None

    def _check_tank(self, now: float) -> None:
        if not self.opts[CONF_TANK_DETECTION]:
            return
        hum = self.humidifier
        if not self.device_running(hum) or self.window_raw_open:
            if self._tank_samples:
                self._reset_tank_samples(now)
            return
        if self.abs_humidity is None:
            return
        if not self._tank_samples or now - self._tank_samples[-1][0] >= TANK_SAMPLE_SECONDS:
            self._tank_samples.append((now, self.abs_humidity))
        window_s = float(self.opts[CONF_TANK_WINDOW]) * 60
        keep_s = max(window_s, TANK_CLEAR_WINDOW_SECONDS)
        self._tank_samples = [s for s in self._tank_samples if s[0] >= now - keep_s]

        threshold = float(self.opts[CONF_TANK_SLOPE])
        if not self.issue_active(ISSUE_REFILL):
            start = max(hum.on_since or now, self._tank_reset_at, self.window_raw_since)
            samples = [s for s in self._tank_samples if s[0] >= now - window_s]
            if len(samples) < 3:
                return
            self.tank_slope = physics.slope_per_hour(samples)
            span = samples[-1][0] - samples[0][0]
            if (
                now - start >= float(self.opts[CONF_TANK_MIN_RUNTIME]) * 60
                and span >= 0.9 * window_s
                and self.tank_slope is not None
                and self.tank_slope <= threshold
            ):
                self._raise_issue(ISSUE_REFILL, "humidity_falling")
        else:
            # resolved automatically once absolute humidity clearly rises while running
            samples = [s for s in self._tank_samples if s[0] >= now - TANK_CLEAR_WINDOW_SECONDS]
            if len(samples) < 3:
                return
            self.tank_slope = physics.slope_per_hour(samples)
            span = samples[-1][0] - samples[0][0]
            if (
                span >= 0.8 * TANK_CLEAR_WINDOW_SECONDS
                and self.tank_slope is not None
                and self.tank_slope >= abs(threshold)
            ):
                hist = list(self.data.get("refill_history_h") or [])
                hist.append(round(self.data["hum_since_refill_s"] / 3600.0, 2))
                self.data["refill_history_h"] = hist[-REFILL_HISTORY_MAX:]
                self.data["hum_since_refill_s"] = 0.0
                self._reset_tank_samples(now)  # drop the old "falling" samples
                self._clear_issue(ISSUE_REFILL, ORIGIN_AUTO)

    def _check_cleaning(self) -> None:
        interval_h = float(self.opts[CONF_CLEANING_INTERVAL])
        if interval_h > 0 and self.data["hum_since_clean_s"] >= interval_h * 3600:
            self._raise_issue(ISSUE_CLEANING, "runtime")

    def _decide(self, now: float) -> tuple[bool, bool]:
        """Return the wanted state (humidifier, dehumidifier) and set the status."""
        hum, dehum = self.humidifier, self.dehumidifier
        hum_on = self.device_is_on(hum)
        dehum_on = self.device_is_on(dehum)

        if not self.enabled:
            self.status = STATUS_OFF
            return hum_on, dehum_on
        if not self.sensor_ok:
            self.status = STATUS_SENSOR_ERROR
            return False, False
        if self.window_open:
            self.status = STATUS_WINDOW_OPEN
            return False, False

        h = float(self.humidity)  # sensor_ok guarantees a value
        dry = float(self.opts[CONF_DRY_TOLERANCE])
        wet = float(self.opts[CONF_WET_TOLERANCE])
        lock_s = float(self.opts[CONF_CHANGEOVER_LOCK]) * 60
        mode = self.mode

        def recently_on(dev: ControlledDevice | None) -> bool:
            if dev is None:
                return False
            if self.device_is_on(dev):
                return True
            return dev.last_off is not None and now - dev.last_off < lock_s

        # --- humidifier
        low = self.effective_target_low
        tank_blocked = self.opts[CONF_TANK_BLOCK] and self.issue_active(ISSUE_REFILL)
        hum_allowed = (
            mode in (MODE_AUTO, MODE_HUMIDIFY)
            and self.season_active
            and not tank_blocked
            and not recently_on(dehum)
        )
        if not hum_allowed:
            want_hum, hum_forced = False, True
        else:
            hum_forced = False
            if h < low - dry:
                want_hum = True
            elif h >= low + wet:
                want_hum = False
            else:
                want_hum = hum_on

        # --- dehumidifier
        want_dehum, dehum_forced = False, True
        if dehum is not None:
            high = self.target_high
            dehum_allowed = mode in (MODE_AUTO, MODE_DEHUMIDIFY) and not recently_on(hum)
            if dehum_allowed:
                dehum_forced = False
                if h > high + wet:
                    want_dehum = True
                elif h <= high - dry:
                    want_dehum = False
                else:
                    want_dehum = dehum_on

        if want_hum and want_dehum:  # the dead band should prevent this
            want_dehum = False

        want_hum = self._respect_cycle(hum, hum_on, want_hum, hum_forced, now)
        if dehum is not None:
            want_dehum = self._respect_cycle(dehum, dehum_on, want_dehum, dehum_forced, now)

        if want_hum:
            self.status = STATUS_HUMIDIFYING
        elif want_dehum:
            self.status = STATUS_DEHUMIDIFYING
        elif tank_blocked:
            self.status = STATUS_TANK_EMPTY
        elif not self.season_active and mode != MODE_DEHUMIDIFY and h < low - dry:
            self.status = STATUS_SEASON_INACTIVE
        else:
            self.status = STATUS_IDLE
        return want_hum, want_dehum

    def _respect_cycle(
        self,
        dev: ControlledDevice,
        is_on: bool,
        want: bool,
        forced: bool,
        now: float,
    ) -> bool:
        if want == is_on:
            return want
        if is_on and not want:
            if forced:
                return False  # locks switch off at once
            min_on = float(self.opts[CONF_MIN_ON]) * 60
            return dev.on_since is not None and now - dev.on_since < min_on
        min_off = float(self.opts[CONF_MIN_OFF]) * 60
        return not (dev.off_since is not None and now - dev.off_since < min_off)

    async def _apply(self, dev: ControlledDevice, want: bool, now: float) -> None:
        if not self.device_available(dev):
            return
        if self.device_is_on(dev) == want:
            return
        if (
            dev.last_command is not None
            and dev.last_command[0] == want
            and now - dev.last_command[1] < COMMAND_RETRY_SECONDS
        ):
            return
        await self._command(dev, want)

    async def _command(self, dev: ControlledDevice, on: bool) -> None:
        dev.last_command = (on, _now())
        domain = dev.domain
        service = SERVICE_TURN_ON if on else SERVICE_TURN_OFF
        if domain not in ("switch", "input_boolean", "humidifier", "fan", "light"):
            domain = "homeassistant"
        _LOGGER.debug("%s: %s.%s %s", self.entry.title, domain, service, dev.entity_id)
        try:
            await self.hass.services.async_call(
                domain, service, {ATTR_ENTITY_ID: dev.entity_id}, blocking=True
            )
            if on and dev.domain == "humidifier":
                # smart device: open up its own controller, we do the controlling
                state = self.hass.states.get(dev.entity_id)
                if state is not None:
                    key = "min_humidity" if dev.is_dehumidifier else "max_humidity"
                    value = state.attributes.get(key)
                    if value is not None:
                        await self.hass.services.async_call(
                            "humidifier",
                            "set_humidity",
                            {ATTR_ENTITY_ID: dev.entity_id, "humidity": value},
                            blocking=True,
                        )
        except Exception as err:
            _LOGGER.warning(
                "%s: switching %s failed: %s",
                self.entry.title,
                dev.entity_id,
                err,
            )
