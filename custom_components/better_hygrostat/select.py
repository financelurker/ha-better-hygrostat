"""Override of the humidifying season."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BetterHygrostatConfigEntry
from .const import OVERRIDE_AUTO, OVERRIDES
from .controller import HygrostatController
from .entity import BetterHygrostatEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BetterHygrostatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the season override."""
    async_add_entities([SeasonOverride(entry, entry.runtime_data.controller)])


class SeasonOverride(BetterHygrostatEntity, SelectEntity):
    """Season: automatic, always active or inactive."""

    _attr_options = OVERRIDES
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-sync"

    def __init__(self, entry: BetterHygrostatConfigEntry, ctrl: HygrostatController) -> None:
        """Initialise the select."""
        super().__init__(entry, ctrl, "season_override")

    @property
    def current_option(self) -> str:
        """Return the current override."""
        return self.ctrl.data.get("season_override", OVERRIDE_AUTO)

    async def async_select_option(self, option: str) -> None:
        """Set the override."""
        await self.ctrl.async_set_season_override(option)
