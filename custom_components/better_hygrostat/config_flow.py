"""Config flow (one entry per room) and options flow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector as sel

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
    CONF_HOME_KEEPER,
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
    SEASON_METHODS,
)

SWITCH_DOMAINS = ["switch", "input_boolean", "humidifier", "fan"]


def _entity(domain: str | list[str], device_class: str | None = None, multiple=False):
    cfg: dict[str, Any] = {"domain": domain, "multiple": multiple}
    if device_class:
        cfg["device_class"] = device_class
    return sel.EntitySelector(sel.EntitySelectorConfig(**cfg))


def _num(minimum: float, maximum: float, step: float = 1, unit: str | None = None):
    return sel.NumberSelector(
        sel.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            unit_of_measurement=unit,
            mode=sel.NumberSelectorMode.BOX,
        )
    )


def _bool():
    return sel.BooleanSelector()


# One schema per step; its keys are used to drop cleared optional fields
def schema_room(with_name: bool) -> vol.Schema:
    """Return the schema of the room step."""
    fields: dict = {}
    if with_name:
        fields[vol.Required(CONF_NAME)] = sel.TextSelector()
    fields.update(
        {
            vol.Required(CONF_HUMIDITY_SENSOR): _entity("sensor", "humidity"),
            vol.Required(CONF_TEMPERATURE_SENSOR): _entity("sensor", "temperature"),
            vol.Required(CONF_HUMIDIFIER): _entity(SWITCH_DOMAINS),
            vol.Optional(CONF_HUMIDIFIER_POWER): _entity("sensor", "power"),
            vol.Optional(
                CONF_HUMIDIFIER_POWER_MIN, default=DEFAULTS[CONF_HUMIDIFIER_POWER_MIN]
            ): _num(0, 500, 0.5, "W"),
        }
    )
    return vol.Schema(fields)


def schema_dehumidifier() -> vol.Schema:
    """Return the schema of the dehumidifier step."""
    return vol.Schema(
        {
            vol.Optional(CONF_DEHUMIDIFIER): _entity(SWITCH_DOMAINS),
            vol.Optional(CONF_DEHUMIDIFIER_POWER): _entity("sensor", "power"),
            vol.Optional(
                CONF_DEHUMIDIFIER_POWER_MIN,
                default=DEFAULTS[CONF_DEHUMIDIFIER_POWER_MIN],
            ): _num(0, 1000, 0.5, "W"),
            vol.Optional(CONF_DEHUMIDIFIER_TANK_SENSOR): _entity("binary_sensor"),
        }
    )


def schema_windows() -> vol.Schema:
    """Return the schema of the windows step."""
    return vol.Schema(
        {
            vol.Optional(CONF_WINDOWS): _entity("binary_sensor", multiple=True),
            vol.Optional(CONF_WINDOW_OPEN_DELAY, default=DEFAULTS[CONF_WINDOW_OPEN_DELAY]): _num(
                0, 3600, 5, "s"
            ),
            vol.Optional(CONF_WINDOW_CLOSE_DELAY, default=DEFAULTS[CONF_WINDOW_CLOSE_DELAY]): _num(
                0, 7200, 30, "s"
            ),
        }
    )


def schema_outdoor() -> vol.Schema:
    """Return the schema of the outdoor step."""
    return vol.Schema(
        {
            vol.Optional(CONF_OUTDOOR_TEMPERATURE): _entity("sensor", "temperature"),
            vol.Optional(CONF_OUTDOOR_HUMIDITY): _entity("sensor", "humidity"),
            vol.Optional(CONF_WEATHER): _entity("weather"),
        }
    )


def schema_control() -> vol.Schema:
    """Return the schema of the control step."""
    d = DEFAULTS
    return vol.Schema(
        {
            vol.Optional(CONF_TARGET_LOW, default=d[CONF_TARGET_LOW]): _num(20, 70, 1, "%"),
            vol.Optional(CONF_TARGET_HIGH, default=d[CONF_TARGET_HIGH]): _num(40, 80, 1, "%"),
            vol.Optional(CONF_DRY_TOLERANCE, default=d[CONF_DRY_TOLERANCE]): _num(0, 10, 0.5, "%"),
            vol.Optional(CONF_WET_TOLERANCE, default=d[CONF_WET_TOLERANCE]): _num(0, 10, 0.5, "%"),
            vol.Optional(CONF_MIN_ON, default=d[CONF_MIN_ON]): _num(0, 120, 1, "min"),
            vol.Optional(CONF_MIN_OFF, default=d[CONF_MIN_OFF]): _num(0, 120, 1, "min"),
            vol.Optional(CONF_CHANGEOVER_LOCK, default=d[CONF_CHANGEOVER_LOCK]): _num(
                0, 240, 5, "min"
            ),
            vol.Optional(CONF_SENSOR_STALE, default=d[CONF_SENSOR_STALE]): _num(0, 1440, 10, "min"),
        }
    )


def schema_season() -> vol.Schema:
    """Return the schema of the season step."""
    d = DEFAULTS
    return vol.Schema(
        {
            vol.Optional(CONF_SEASON_METHOD, default=d[CONF_SEASON_METHOD]): sel.SelectSelector(
                sel.SelectSelectorConfig(options=SEASON_METHODS, translation_key=CONF_SEASON_METHOD)
            ),
            vol.Optional(CONF_HEATING_LIMIT, default=d[CONF_HEATING_LIMIT]): _num(5, 20, 0.5, "°C"),
            vol.Optional(CONF_SEASON_BAND, default=d[CONF_SEASON_BAND]): _num(1, 15, 1, "%"),
            vol.Optional(CONF_CONDENSATION_LIMIT, default=d[CONF_CONDENSATION_LIMIT]): _bool(),
            vol.Optional(CONF_CONDENSATION_OFFSET, default=d[CONF_CONDENSATION_OFFSET]): _num(
                -10, 15, 1, "%"
            ),
        }
    )


def schema_maintenance() -> vol.Schema:
    """Return the schema of the maintenance step."""
    d = DEFAULTS
    return vol.Schema(
        {
            vol.Optional(CONF_TANK_DETECTION, default=d[CONF_TANK_DETECTION]): _bool(),
            vol.Optional(CONF_TANK_MIN_RUNTIME, default=d[CONF_TANK_MIN_RUNTIME]): _num(
                15, 480, 5, "min"
            ),
            vol.Optional(CONF_TANK_WINDOW, default=d[CONF_TANK_WINDOW]): _num(15, 240, 5, "min"),
            vol.Optional(CONF_TANK_SLOPE, default=d[CONF_TANK_SLOPE]): _num(-2, 0, 0.01, "g/m³/h"),
            vol.Optional(CONF_TANK_BLOCK, default=d[CONF_TANK_BLOCK]): _bool(),
            vol.Optional(CONF_CLEANING_INTERVAL, default=d[CONF_CLEANING_INTERVAL]): _num(
                0, 2000, 10, "h"
            ),
            vol.Optional(CONF_HOME_KEEPER, default=d[CONF_HOME_KEEPER]): _bool(),
        }
    )


STEPS = {
    "room": lambda: schema_room(False),
    "dehumidifier": schema_dehumidifier,
    "windows": schema_windows,
    "outdoor": schema_outdoor,
    "control": schema_control,
    "season": schema_season,
    "maintenance": schema_maintenance,
}


def _keys(schema: vol.Schema) -> list[str]:
    return [str(k.schema) for k in schema.schema]


def _merge(options: dict, schema: vol.Schema, user_input: dict) -> dict:
    """Schritt-Eingabe uebernehmen; geleerte optionale Felder entfernen."""
    out = {k: v for k, v in options.items() if k not in _keys(schema)}
    out.update({k: v for k, v in user_input.items() if v not in (None, "", [])})
    return out


def _validate(options: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    if options.get(CONF_DEHUMIDIFIER) and options.get(CONF_DEHUMIDIFIER) == options.get(
        CONF_HUMIDIFIER
    ):
        errors[CONF_DEHUMIDIFIER] = "same_device"
    low = options.get(CONF_TARGET_LOW, DEFAULTS[CONF_TARGET_LOW])
    high = options.get(CONF_TARGET_HIGH, DEFAULTS[CONF_TARGET_HIGH])
    if high < low + 5:
        errors[CONF_TARGET_HIGH] = "deadband"
    if options.get(CONF_OUTDOOR_HUMIDITY) and not options.get(CONF_OUTDOOR_TEMPERATURE):
        errors[CONF_OUTDOOR_HUMIDITY] = "needs_temperature"
    return errors


class BetterHygrostatConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow: one entry per room."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise."""
        self._options: dict[str, Any] = {}
        self._title = ""

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle the room step."""
        schema = schema_room(True)
        if user_input is not None:
            self._title = user_input.pop(CONF_NAME)
            self._options = _merge(self._options, schema, user_input)
            return await self.async_step_dehumidifier()
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_dehumidifier(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle the dehumidifier step."""
        return await self._step("dehumidifier", user_input, self.async_step_windows)

    async def async_step_windows(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle the windows step."""
        return await self._step("windows", user_input, self.async_step_outdoor)

    async def async_step_outdoor(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle the outdoor step."""
        return await self._step("outdoor", user_input, self._finish)

    async def _step(self, step_id: str, user_input, next_step) -> ConfigFlowResult:
        schema = STEPS[step_id]()
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = _merge(self._options, schema, user_input)
            errors = {k: v for k, v in _validate(candidate).items() if k in _keys(schema)}
            if not errors:
                self._options = candidate
                return await next_step()
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, self._options),
            errors=errors,
        )

    async def _finish(self, _user_input=None) -> ConfigFlowResult:
        options = {**DEFAULTS, **self._options}
        return self.async_create_entry(title=self._title, data={}, options=options)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Return the options flow."""
        return BetterHygrostatOptionsFlow()


class BetterHygrostatOptionsFlow(OptionsFlow):
    """Menue: jeder Bereich einzeln, am Ende speichern."""

    def __init__(self) -> None:
        """Initialise."""
        self._options: dict[str, Any] | None = None

    @property
    def options(self) -> dict[str, Any]:
        """Return the options being edited."""
        if self._options is None:
            self._options = {**DEFAULTS, **self.config_entry.data, **self.config_entry.options}
        return self._options

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(step_id="init", menu_options=[*STEPS, "save"])

    async def async_step_save(self, user_input=None) -> ConfigFlowResult:
        """Save the options."""
        return self.async_create_entry(data=self.options)

    async def _section(self, step_id: str, user_input) -> ConfigFlowResult:
        schema = STEPS[step_id]()
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = _merge(self.options, schema, user_input)
            errors = {k: v for k, v in _validate(candidate).items() if k in _keys(schema)}
            if not errors:
                self._options = candidate
                return await self.async_step_init()
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, self.options),
            errors=errors,
        )

    async def async_step_room(self, user_input=None) -> ConfigFlowResult:
        """Handle the room section."""
        return await self._section("room", user_input)

    async def async_step_dehumidifier(self, user_input=None) -> ConfigFlowResult:
        """Handle the dehumidifier step."""
        return await self._section("dehumidifier", user_input)

    async def async_step_windows(self, user_input=None) -> ConfigFlowResult:
        """Handle the windows step."""
        return await self._section("windows", user_input)

    async def async_step_outdoor(self, user_input=None) -> ConfigFlowResult:
        """Handle the outdoor step."""
        return await self._section("outdoor", user_input)

    async def async_step_control(self, user_input=None) -> ConfigFlowResult:
        """Handle the control section."""
        return await self._section("control", user_input)

    async def async_step_season(self, user_input=None) -> ConfigFlowResult:
        """Handle the season section."""
        return await self._section("season", user_input)

    async def async_step_maintenance(self, user_input=None) -> ConfigFlowResult:
        """Handle the maintenance section."""
        return await self._section("maintenance", user_input)
