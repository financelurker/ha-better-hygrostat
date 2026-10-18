"""Better Hygrostat: a room hygrostat with window, season and maintenance logic."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import CONF_HOME_KEEPER, DOMAIN, PLATFORMS, STORAGE_VERSION
from .controller import HygrostatController
from .homekeeper import HomeKeeperGlue, async_release


@dataclass
class RuntimeData:
    """Runtime data of a config entry."""

    controller: HygrostatController
    glue: HomeKeeperGlue | None


type BetterHygrostatConfigEntry = ConfigEntry[RuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: BetterHygrostatConfigEntry) -> bool:
    """Set up the platform."""
    controller = HygrostatController(hass, entry)
    await controller.async_start()

    glue: HomeKeeperGlue | None = None
    if controller.opts.get(CONF_HOME_KEEPER):
        glue = HomeKeeperGlue(hass, entry, controller)
    else:
        # turning Home Keeper off and on again re-creates deleted appliances
        controller.data["hk_assets_declined"] = []

    entry.runtime_data = RuntimeData(controller, glue)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if glue is not None:
        # after the platforms, so the device exists for device_id
        await glue.async_start()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BetterHygrostatConfigEntry) -> bool:
    """Unload a config entry."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        data = entry.runtime_data
        if data.glue is not None:
            data.glue.async_stop()
        await data.controller.async_stop()
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Gespeicherte Daten entfernen, Home-Keeper-Tasks loeschen, Appliances freigeben."""
    store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
    stored = await store.async_load() or {}
    await async_release(hass, stored)
    await store.async_remove()


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
