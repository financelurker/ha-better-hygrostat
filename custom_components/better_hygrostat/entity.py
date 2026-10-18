"""Common base for all entities of a room."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.loader import async_get_loaded_integration

from .const import DOMAIN, NAME
from .controller import HygrostatController


class BetterHygrostatEntity(Entity):
    """Base entity: one device per room, updated by the controller."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, controller: HygrostatController, key: str) -> None:
        """Initialise the entity for a room."""
        self.ctrl = controller
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=NAME,
            model="Hygrostat + dehumidifier" if controller.has_dehumidifier else "Hygrostat",
            sw_version=str(async_get_loaded_integration(controller.hass, DOMAIN).version),
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to controller updates."""
        self.async_on_remove(self.ctrl.async_add_listener(self.async_write_ha_state))
