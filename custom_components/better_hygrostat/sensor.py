"""Measurement and counter sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BetterHygrostatConfigEntry
from .const import STATUSES
from .controller import HygrostatController
from .entity import BetterHygrostatEntity


@dataclass(frozen=True, kw_only=True)
class BHSensorDescription(SensorEntityDescription):
    """Describes a Better Hygrostat sensor."""

    value: Callable[[HygrostatController], Any]
    attrs: Callable[[HygrostatController], dict] | None = None
    available: Callable[[HygrostatController], bool] = lambda c: True


def _r(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def _season_attrs(c: HygrostatController) -> dict:
    mean_t, mean_eq = c.outdoor_means()
    return {
        "method": c.season_method(),
        "outdoor_temperature_24h": _r(mean_t),
        "outdoor_equivalent_humidity_24h": _r(mean_eq),
    }


SENSORS: list[BHSensorDescription] = [
    BHSensorDescription(
        key="status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUSES,
        value=lambda c: c.status,
        attrs=lambda c: {"tank_slope_g_m3_h": _r(c.tank_slope, 3)},
    ),
    BHSensorDescription(
        key="absolute_humidity",
        native_unit_of_measurement="g/m³",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:water-percent",
        value=lambda c: _r(c.abs_humidity, 2),
    ),
    BHSensorDescription(
        key="dew_point",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value=lambda c: _r(c.dew_point),
    ),
    BHSensorDescription(
        key="effective_target",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:target",
        value=lambda c: _r(c.effective_target_low),
        attrs=lambda c: {
            "target": c.target_low,
            "condensation_limit": _r(c.condensation_limit),
        },
    ),
    BHSensorDescription(
        key="outdoor_equivalent_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:home-thermometer-outline",
        value=lambda c: _r(c.outdoor_equivalent),
        attrs=_season_attrs,
        available=lambda c: c.has_outdoor_humidity,
    ),
    BHSensorDescription(
        key="humidifier_runtime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:timer-outline",
        value=lambda c: c.hours("hum_total_s"),
    ),
    BHSensorDescription(
        key="runtime_since_refill",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        icon="mdi:cup-water",
        value=lambda c: c.hours("hum_since_refill_s"),
        attrs=lambda c: {
            "typical_tank_runtime_h": c.typical_tank_runtime_h,
            "history_h": list(c.data.get("refill_history_h") or []),
        },
    ),
    BHSensorDescription(
        key="runtime_since_cleaning",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        icon="mdi:spray-bottle",
        value=lambda c: c.hours("hum_since_clean_s"),
    ),
    BHSensorDescription(
        key="dehumidifier_runtime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:timer-outline",
        value=lambda c: c.hours("dehum_total_s"),
        available=lambda c: c.has_dehumidifier,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BetterHygrostatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the platform."""
    ctrl = entry.runtime_data.controller
    async_add_entities(BHSensor(entry, ctrl, desc) for desc in SENSORS if desc.available(ctrl))


class BHSensor(BetterHygrostatEntity, SensorEntity):
    """Sensor driven by the controller."""

    entity_description: BHSensorDescription

    def __init__(self, entry, ctrl, desc: BHSensorDescription) -> None:
        """Initialise."""
        super().__init__(entry, ctrl, desc.key)
        self.entity_description = desc

    @property
    def native_value(self) -> Any:
        """Return the value."""
        return self.entity_description.value(self.ctrl)

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return extra attributes."""
        if self.entity_description.attrs is None:
            return None
        return self.entity_description.attrs(self.ctrl)
