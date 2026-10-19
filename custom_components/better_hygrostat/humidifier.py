"""The hygrostat entity of a room."""

from __future__ import annotations

from typing import Any

from homeassistant.components.humidifier import (
    HumidifierAction,
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BetterHygrostatConfigEntry
from .const import ISSUES, MODES, STATUS_DEHUMIDIFYING, STATUS_HUMIDIFYING
from .controller import HygrostatController
from .entity import BetterHygrostatEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BetterHygrostatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hygrostat entity."""
    async_add_entities([BetterHygrostat(entry, entry.runtime_data.controller)])


class BetterHygrostat(BetterHygrostatEntity, HumidifierEntity):
    """Room hygrostat: target humidity, modes and current action."""

    _attr_name = None  # the entity is named like the device (the room)
    _attr_min_humidity = 20
    _attr_max_humidity = 80

    def __init__(self, entry: BetterHygrostatConfigEntry, controller: HygrostatController) -> None:
        """Initialise the hygrostat."""
        super().__init__(entry, controller, "hygrostat")
        if controller.has_dehumidifier:
            self._attr_supported_features = HumidifierEntityFeature.MODES
            self._attr_available_modes = MODES
            self._attr_device_class = None
        else:
            self._attr_device_class = HumidifierDeviceClass.HUMIDIFIER

    @property
    def is_on(self) -> bool:
        """Return whether control is enabled."""
        return self.ctrl.enabled

    @property
    def current_humidity(self) -> float | None:
        """Return the room humidity."""
        return self.ctrl.humidity

    @property
    def target_humidity(self) -> float:
        """Return the humidify target."""
        return self.ctrl.target_low

    @property
    def mode(self) -> str | None:
        """Return the mode (only with a dehumidifier)."""
        return self.ctrl.mode if self.ctrl.has_dehumidifier else None

    @property
    def action(self) -> HumidifierAction:
        """Return what the room is doing right now."""
        if not self.ctrl.enabled:
            return HumidifierAction.OFF
        if self.ctrl.status == STATUS_HUMIDIFYING:
            return HumidifierAction.HUMIDIFYING
        if self.ctrl.status == STATUS_DEHUMIDIFYING:
            return HumidifierAction.DRYING
        return HumidifierAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return status details."""
        c = self.ctrl
        attrs: dict[str, Any] = {
            "status": c.status,
            "effective_target": round(c.effective_target_low, 1),
            "season_active": c.season_active,
            "window_open": c.window_open,
            "window_unknown": c.window_unknown,
            "problems": [k for k in ISSUES if c.issue_active(k)],
        }
        if c.has_dehumidifier:
            attrs["dehumidify_above"] = c.target_high
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable control."""
        await self.ctrl.async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable control and switch the devices off once."""
        await self.ctrl.async_set_enabled(False)

    async def async_set_humidity(self, humidity: int) -> None:
        """Set the humidify target."""
        await self.ctrl.async_set_target_low(humidity)

    async def async_set_mode(self, mode: str) -> None:
        """Set the mode."""
        await self.ctrl.async_set_mode(mode)
