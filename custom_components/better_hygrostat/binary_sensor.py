"""State and problem binary sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BetterHygrostatConfigEntry
from .const import (
    ISSUE_CLEANING,
    ISSUE_DEHUM_FAULT,
    ISSUE_DEHUM_TANK,
    ISSUE_HUM_FAULT,
    ISSUE_REFILL,
    ISSUE_STORAGE,
)
from .controller import HygrostatController
from .entity import BetterHygrostatEntity


@dataclass(frozen=True, kw_only=True)
class BHBinaryDescription(BinarySensorEntityDescription):
    """Describes a Better Hygrostat binary sensor."""

    value: Callable[[HygrostatController], bool | None]
    available: Callable[[HygrostatController], bool] = lambda c: True
    issue: str | None = None


def _issue(key: str, icon: str, available=lambda c: True) -> BHBinaryDescription:
    return BHBinaryDescription(
        key=key,
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon=icon,
        issue=key,
        value=lambda c: c.issue_active(key),
        available=available,
    )


BINARY_SENSORS: list[BHBinaryDescription] = [
    BHBinaryDescription(
        key="window_open",
        device_class=BinarySensorDeviceClass.WINDOW,
        value=lambda c: c.window_open,
        available=lambda c: bool(c.windows),
    ),
    BHBinaryDescription(
        key="humidifying_season",
        icon="mdi:snowflake-thermometer",
        value=lambda c: c.season_active,
    ),
    BHBinaryDescription(
        key="ventilation_recommended",
        icon="mdi:window-open-variant",
        value=lambda c: c.ventilation_recommended,
        available=lambda c: c.has_outdoor_humidity,
    ),
    _issue(ISSUE_REFILL, "mdi:cup-water"),
    _issue(ISSUE_CLEANING, "mdi:spray-bottle"),
    _issue(ISSUE_STORAGE, "mdi:package-down"),
    _issue(
        ISSUE_HUM_FAULT,
        "mdi:power-plug-off",
        available=lambda c: bool(c.humidifier.power_entity),
    ),
    _issue(
        ISSUE_DEHUM_TANK,
        "mdi:water-alert",
        available=lambda c: (
            c.dehumidifier is not None
            and bool(c.dehumidifier.power_entity or c.dehumidifier.tank_sensor)
        ),
    ),
    _issue(
        ISSUE_DEHUM_FAULT,
        "mdi:power-plug-off",
        available=lambda c: c.dehumidifier is not None and bool(c.dehumidifier.power_entity),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BetterHygrostatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the platform."""
    ctrl = entry.runtime_data.controller
    async_add_entities(BHBinarySensor(entry, ctrl, d) for d in BINARY_SENSORS if d.available(ctrl))


class BHBinarySensor(BetterHygrostatEntity, BinarySensorEntity):
    """Binary sensor driven by the controller."""

    entity_description: BHBinaryDescription

    def __init__(self, entry, ctrl, desc: BHBinaryDescription) -> None:
        """Initialise."""
        super().__init__(entry, ctrl, desc.key)
        self.entity_description = desc

    @property
    def is_on(self) -> bool | None:
        """Return the state."""
        return self.entity_description.value(self.ctrl)

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return extra attributes."""
        key = self.entity_description.issue
        if key is None:
            return None
        issue = self.ctrl.issue(key)
        return {"since": issue.get("since"), "reason": issue.get("reason")}
