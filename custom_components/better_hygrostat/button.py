"""Buttons to confirm maintenance."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BetterHygrostatConfigEntry
from .const import ISSUE_CLEANING, ISSUE_DEHUM_TANK, ISSUE_REFILL, ISSUE_STORAGE, ORIGIN_USER
from .controller import HygrostatController
from .entity import BetterHygrostatEntity

BUTTONS = [
    ("refilled", ISSUE_REFILL, "mdi:cup-water"),
    ("cleaned", ISSUE_CLEANING, "mdi:spray-bottle"),
    ("stored", ISSUE_STORAGE, "mdi:package-down"),
    ("dehumidifier_emptied", ISSUE_DEHUM_TANK, "mdi:water-off"),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BetterHygrostatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the maintenance buttons."""
    ctrl = entry.runtime_data.controller
    async_add_entities(
        MaintenanceButton(entry, ctrl, key, issue, icon)
        for key, issue, icon in BUTTONS
        if issue != ISSUE_DEHUM_TANK or ctrl.has_dehumidifier
    )


class MaintenanceButton(BetterHygrostatEntity, ButtonEntity):
    """Confirms that a maintenance task is done."""

    def __init__(
        self,
        entry: BetterHygrostatConfigEntry,
        ctrl: HygrostatController,
        key: str,
        issue: str,
        icon: str,
    ) -> None:
        """Initialise the button."""
        super().__init__(entry, ctrl, key)
        self._issue = issue
        self._attr_icon = icon

    async def async_press(self) -> None:
        """Resolve the issue."""
        await self.ctrl.async_resolve(self._issue, ORIGIN_USER)
