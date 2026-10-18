"""Dehumidify-above threshold (only with a dehumidifier)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BetterHygrostatConfigEntry
from .controller import HygrostatController
from .entity import BetterHygrostatEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BetterHygrostatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the threshold when a dehumidifier is configured."""
    ctrl = entry.runtime_data.controller
    if ctrl.has_dehumidifier:
        async_add_entities([DehumidifyAbove(entry, ctrl)])


class DehumidifyAbove(BetterHygrostatEntity, NumberEntity):
    """Humidity above which the dehumidifier runs."""

    _attr_native_min_value = 40
    _attr_native_max_value = 80
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:water-minus"

    def __init__(self, entry: BetterHygrostatConfigEntry, ctrl: HygrostatController) -> None:
        """Initialise the threshold."""
        super().__init__(entry, ctrl, "dehumidify_above")

    @property
    def native_value(self) -> float:
        """Return the threshold."""
        return self.ctrl.target_high

    async def async_set_native_value(self, value: float) -> None:
        """Set the threshold."""
        await self.ctrl.async_set_target_high(value)
