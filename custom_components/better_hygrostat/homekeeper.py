"""Optional link to Home Keeper (prestomation/ha-home-keeper).

Services and events only, no Python import - works without Home Keeper installed.
Contract: Home Keeper's docs/INTEGRATING.md (triggered tasks, source, origin).

- issue raised          -> add_task (triggered, armed) or trigger_task
- resolved here         -> complete_task with origin=better_hygrostat
- completed in HK       -> Controller.async_resolve(..., ORIGIN_HOME_KEEPER)
- one managed appliance per device (humidifier/dehumidifier); tasks hang on its
  device. Appliances deleted by the user are not created again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
from datetime import datetime
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    ISSUE_CLEANING,
    ISSUE_DEHUM_FAULT,
    ISSUE_DEHUM_TANK,
    ISSUE_HUM_FAULT,
    ISSUE_REFILL,
    ISSUE_STORAGE,
    NAME,
    ORIGIN_HOME_KEEPER,
)
from .controller import HygrostatController

_LOGGER = logging.getLogger(__name__)

HK = "home_keeper"
EVENT_COMPLETED = "home_keeper_task_completed"
EVENT_DELETED = "home_keeper_task_deleted"
EVENT_REGISTER = "home_keeper_register_companions"
EVENT_ASSET_DELETED = "home_keeper_asset_deleted"

_TEXTS: dict[str, dict[str, tuple[str, str]]] = {
    "de": {
        ISSUE_REFILL: (
            "Wasser nachfüllen",
            "Die absolute Feuchte fällt, obwohl der Befeuchter läuft und alle Fenster "
            "zu sind – vermutlich ist der Tank leer. Nach dem Nachfüllen abhaken.",
        ),
        ISSUE_CLEANING: (
            "Befeuchter reinigen",
            "Fällig nach Betriebsstunden oder zum Saisonstart. Abhaken setzt den "
            "Reinigungszähler zurück.",
        ),
        ISSUE_STORAGE: (
            "Befeuchter einlagern",
            "Die Befeuchtungssaison ist vorbei: Gerät reinigen, vollständig "
            "trocknen lassen und einlagern. Kein Wasser über den Sommer stehen lassen.",
        ),
        ISSUE_HUM_FAULT: (
            "Befeuchter prüfen",
            "Die Steckdose ist eingeschaltet, aber das Gerät nimmt keine Leistung auf "
            "(Geräteschalter aus, Stecker gezogen, defekt?).",
        ),
        ISSUE_DEHUM_TANK: (
            "Entfeuchter-Tank leeren",
            "Der Entfeuchter hat sich abgeschaltet – vermutlich ist der Tank voll.",
        ),
        ISSUE_DEHUM_FAULT: (
            "Entfeuchter prüfen",
            "Die Steckdose ist eingeschaltet, aber das Gerät nimmt keine Leistung auf.",
        ),
    },
    "en": {
        ISSUE_REFILL: (
            "Refill water",
            "Absolute humidity is falling although the humidifier runs and all "
            "windows are closed - the tank is probably empty. Check off after refilling.",
        ),
        ISSUE_CLEANING: (
            "Clean humidifier",
            "Due after runtime hours or at season start. Completing resets the counter.",
        ),
        ISSUE_STORAGE: (
            "Store humidifier",
            "The humidifying season is over: clean, dry completely and store the device.",
        ),
        ISSUE_HUM_FAULT: (
            "Check humidifier",
            "The plug is on but the device draws no power.",
        ),
        ISSUE_DEHUM_TANK: (
            "Empty dehumidifier tank",
            "The dehumidifier stopped - its tank is probably full.",
        ),
        ISSUE_DEHUM_FAULT: (
            "Check dehumidifier",
            "The plug is on but the device draws no power.",
        ),
    },
}


ROLE_HUM = "humidifier"
ROLE_DEHUM = "dehumidifier"

# Which issue belongs to which device (appliance)
ISSUE_ROLE: dict[str, str] = {
    ISSUE_REFILL: ROLE_HUM,
    ISSUE_CLEANING: ROLE_HUM,
    ISSUE_STORAGE: ROLE_HUM,
    ISSUE_HUM_FAULT: ROLE_HUM,
    ISSUE_DEHUM_TANK: ROLE_DEHUM,
    ISSUE_DEHUM_FAULT: ROLE_DEHUM,
}

_ASSET_TEXTS: dict[str, dict[str, tuple[str, str]]] = {
    "de": {
        ROLE_HUM: (
            "Befeuchter",
            "Von Better Hygrostat angelegt. Name, Hersteller, Modell, Handbuch und "
            "Teile hier frei pflegen – z. B. das Hygienemittel als Verbrauchsteil mit "
            "Bestand und es mit der Reinigungs-Task verknüpfen.",
        ),
        ROLE_DEHUM: (
            "Entfeuchter",
            "Von Better Hygrostat angelegt. Name, Hersteller, Modell, Handbuch und "
            "Teile (z. B. Filter) hier frei pflegen.",
        ),
    },
    "en": {
        ROLE_HUM: (
            "Humidifier",
            "Created by Better Hygrostat. Edit name, manufacturer, model, manual and "
            "parts freely - e.g. add the hygiene additive as a stocked consumable and "
            "link it to the cleaning task.",
        ),
        ROLE_DEHUM: (
            "Dehumidifier",
            "Created by Better Hygrostat. Edit name, manufacturer, model, manual and "
            "parts (e.g. filter) freely.",
        ),
    },
}

_ASSET_ICONS = {ROLE_HUM: "mdi:air-humidifier", ROLE_DEHUM: "mdi:air-humidifier-off"}


class HomeKeeperGlue:
    """Keeps the appliances and tasks of one room in sync with Home Keeper."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, ctrl: HygrostatController) -> None:
        """Initialise."""
        self.hass = hass
        self.entry = entry
        self.ctrl = ctrl
        self._unsubs: list[Callable[[], None]] = []
        self._retries = 0
        self._lock = asyncio.Lock()
        # role -> device id of the appliance (Home Keeper's virtual device)
        self._asset_devices: dict[str, str | None] = {}

    # ------------------------------------------------------------- helpers

    @property
    def available(self) -> bool:
        """Return whether Home Keeper is installed."""
        return self.hass.services.has_service(HK, "add_task")

    @property
    def _tasks(self) -> dict[str, str]:
        return self.ctrl.data.setdefault("hk_tasks", {})

    @property
    def _assets(self) -> dict[str, str]:
        return self.ctrl.data.setdefault("hk_assets", {})

    @property
    def _declined(self) -> list[str]:
        """Roles whose appliance the user deleted (do not create them again)."""
        return self.ctrl.data.setdefault("hk_assets_declined", [])

    def _lang(self) -> str:
        lang = (self.hass.config.language or "en").split("-")[0]
        return lang if lang in _TEXTS else "en"

    def _text(self, key: str) -> tuple[str, str]:
        name, notes = _TEXTS[self._lang()][key]
        return f"{self.entry.title}: {name}", notes

    def _roles(self) -> list[str]:
        return [ROLE_HUM, ROLE_DEHUM] if self.ctrl.has_dehumidifier else [ROLE_HUM]

    def _managed_by(self) -> dict[str, Any]:
        return {
            "integration": DOMAIN,
            "display_name": NAME,
            "icon": "mdi:air-humidifier",
            "config_entry_id": self.entry.entry_id,
        }

    def _room_device(self) -> dr.DeviceEntry | None:
        return dr.async_get(self.hass).async_get_device_by_identifier(
            (DOMAIN, self.entry.entry_id), self.entry.entry_id
        )

    def _entity_device(self, entity_id: str | None) -> dr.DeviceEntry | None:
        if not entity_id:
            return None
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is None or entry.device_id is None:
            return None
        return dr.async_get(self.hass).async_get(entry.device_id)

    def _task_device(self, key: str) -> str | None:
        """Return the appliance device of the matching role, else the room device."""
        device_id = self._asset_devices.get(ISSUE_ROLE.get(key, ROLE_HUM))
        if device_id:
            return device_id
        room = self._room_device()
        return room.id if room else None

    async def _call(self, service: str, data: dict[str, Any], response: bool = False) -> Any:
        if not self.hass.services.has_service(HK, service):
            _LOGGER.debug("Home Keeper ohne Service %s - uebersprungen", service)
            return None
        try:
            result = await self.hass.services.async_call(
                HK, service, data, blocking=True, return_response=response
            )
            # ohne Antwort: True = erfolgreich (None bedeutet Fehler)
            return result if response else True
        except HomeAssistantError as err:
            if getattr(err, "translation_key", None) == "integration_not_loaded":
                _LOGGER.debug("Home Keeper not ready yet (%s)", service)
            else:
                _LOGGER.warning("Home Keeper %s fehlgeschlagen: %s", service, err)
        except Exception as err:
            _LOGGER.warning("Home Keeper %s fehlgeschlagen: %s", service, err)
        return None

    # ----------------------------------------------------------- lifecycle

    async def async_start(self) -> None:
        """Load stored data, subscribe to events and start evaluating."""
        self._unsubs.append(self.ctrl.async_add_issue_listener(self._on_issue))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_COMPLETED, self._on_completed))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_DELETED, self._on_deleted))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_ASSET_DELETED, self._on_asset_deleted))
        self._unsubs.append(self.hass.bus.async_listen(EVENT_REGISTER, self._on_hk_ready))
        if self.available:
            await self._register()
            await self.async_reconcile()

    @callback
    def async_stop(self) -> None:
        """Unsubscribe and save the data."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def _register(self) -> None:
        await self._call(
            "register_companion",
            {
                "domain": DOMAIN,
                "name": NAME,
                "icon": "mdi:air-humidifier",
                "description": "Humidifiers and dehumidifiers: refill, clean, store.",
                "config_entry_id": self.entry.entry_id,
                "capabilities": ["appliances", "triggered_tasks"],
            },
        )

    @callback
    def _on_hk_ready(self, _event: Event) -> None:
        async def _run() -> None:
            await self._register()
            await self.async_reconcile()

        self.hass.async_create_task(_run())

    @callback
    def _schedule_retry(self) -> None:
        if not self.available or self._retries >= 10:
            return
        self._retries += 1

        @callback
        def _retry(_now: Any) -> None:
            self.hass.async_create_task(self.async_reconcile())

        self._unsubs.append(async_call_later(self.hass, 30, _retry))

    async def async_reconcile(self) -> None:
        """Reconcile appliances, tasks and state after start or reload."""
        async with self._lock:
            if not await self._reconcile_assets():
                # Home Keeper may still be loading -> retry later (max. 10x, every 30 s)
                self._schedule_retry()
                return
            if not await self._reconcile_tasks():
                self._schedule_retry()
                return
            self._retries = 0

    # ---------------------------------------------------------- appliances

    async def _list_my_assets(self) -> dict[str, dict] | None:
        resp = await self._call("list_assets", {}, response=True)
        if resp is None:
            return None
        mine: dict[str, dict] = {}
        for asset in resp.get("assets", []):
            src = (asset.get("source") or {}).get(DOMAIN) or {}
            if src.get("entry_id") == self.entry.entry_id and src.get("role"):
                mine[src["role"]] = asset
        return mine

    async def _reconcile_assets(self) -> bool:
        mine = await self._list_my_assets()
        if mine is None:
            return False

        # deleted by the user -> respect it, do not create it again
        for role in list(self._assets):
            if role not in mine:
                self._assets.pop(role, None)
                if role not in self._declined:
                    self._declined.append(role)
                _LOGGER.info(
                    "%s: Appliance '%s' wurde in Home Keeper geloescht - wird nicht neu angelegt",
                    self.entry.title,
                    role,
                )

        created = False
        for role in self._roles():
            if role not in mine and role not in self._declined:
                created |= await self._create_asset(role)
        if created:
            mine = await self._list_my_assets()
            if mine is None:
                return False

        # device no longer configured (e.g. dehumidifier removed) -> release it
        for role, asset in list(mine.items()):
            if role not in self._roles():
                if asset.get("managed_by"):
                    await self._call("update_asset", {"asset_id": asset["id"], "managed_by": None})
                mine.pop(role)

        self._assets.clear()
        self._assets.update({role: asset["id"] for role, asset in mine.items()})
        self._asset_devices = {role: asset.get("device_id") for role, asset in mine.items()}
        return True

    async def _create_asset(self, role: str) -> bool:
        name, notes = _ASSET_TEXTS[self._lang()][role]
        dev = self.ctrl.humidifier if role == ROLE_HUM else self.ctrl.dehumidifier
        room = self._room_device()
        plug = self._entity_device(dev.entity_id if dev else None)
        power = self._entity_device(dev.power_entity if dev else None)
        related: list[str] = []
        for device in (plug, power, room):
            if device is not None and device.id not in related:
                related.append(device.id)
        data: dict[str, Any] = {
            "name": f"{self.entry.title}: {name}",
            "kind": "virtual",
            "icon": _ASSET_ICONS[role],
            "notes": notes,
            "managed_by": self._managed_by(),
            "source": {DOMAIN: {"entry_id": self.entry.entry_id, "role": role}},
        }
        if related:
            data["related_device_ids"] = related
        area_id = next((d.area_id for d in (room, plug) if d is not None and d.area_id), None)
        if area_id:
            data["area_id"] = area_id
        ok = await self._call("add_asset", data) is not None
        if ok:
            _LOGGER.info("%s: Appliance '%s' in Home Keeper angelegt", self.entry.title, role)
        return ok

    @callback
    def _on_asset_deleted(self, event: Event) -> None:
        asset_id = event.data.get("asset_id")
        for role, aid in list(self._assets.items()):
            if aid == asset_id:
                self._assets.pop(role)
                self._asset_devices.pop(role, None)
                if role not in self._declined:
                    self._declined.append(role)
                # move the tasks back to the room device
                self.hass.async_create_task(self.async_reconcile())

    # --------------------------------------------------------------- tasks

    async def _reconcile_tasks(self) -> bool:
        resp = await self._call("list_tasks", {}, response=True)
        if resp is None:
            return False
        found: dict[str, dict] = {}
        for task in resp.get("tasks", []):
            src = (task.get("source") or {}).get(DOMAIN) or {}
            if src.get("entry_id") == self.entry.entry_id and src.get("issue"):
                found[src["issue"]] = task
        self._tasks.clear()
        self._tasks.update({k: t["id"] for k, t in found.items()})

        for key, task in found.items():
            # attach to the right appliance (also migrates tasks from 0.1.0)
            want = self._task_device(key)
            if want and task.get("device_id") != want:
                src = dict((task.get("source") or {}).get(DOMAIN) or {})
                src["device_id"] = want
                await self._call(
                    "update_task",
                    {"task_id": task["id"], "device_id": want, "source": {DOMAIN: src}},
                )

            armed = task.get("next_due") is not None
            issue = self.ctrl.issue(key)
            active = bool(issue.get("active"))
            if active and not armed:
                # completed in HK while we were not running? -> take it over
                last = _last_completion(task)
                since = _parse(issue.get("since"))
                if last and since and last > since:
                    await self.ctrl.async_resolve(key, ORIGIN_HOME_KEEPER)
                else:
                    await self._call("trigger_task", {"task_id": task["id"]})
            elif not active and armed:
                await self._call("complete_task", {"task_id": task["id"], "origin": DOMAIN})
        for key in self.ctrl.data["issues"]:
            if self.ctrl.issue_active(key) and key not in self._tasks:
                await self._arm_unlocked(key)
        return True

    @callback
    def _on_issue(self, key: str, active: bool, origin: str) -> None:
        if not self.available:
            return
        if active:
            self.hass.async_create_task(self._arm(key))
        elif origin != ORIGIN_HOME_KEEPER and key in self._tasks:
            self.hass.async_create_task(
                self._call("complete_task", {"task_id": self._tasks[key], "origin": DOMAIN})
            )

    async def _arm(self, key: str) -> None:
        async with self._lock:
            await self._arm_unlocked(key)

    async def _arm_unlocked(self, key: str) -> None:
        task_id = self._tasks.get(key)
        if task_id:
            await self._call("trigger_task", {"task_id": task_id})
            return
        name, notes = self._text(key)
        source: dict[str, Any] = {"entry_id": self.entry.entry_id, "issue": key}
        data: dict[str, Any] = {
            "name": name,
            "notes": notes,
            "recurrence_type": "triggered",
            "managed_by": self._managed_by(),
        }
        if device_id := self._task_device(key):
            data["device_id"] = device_id
            source["device_id"] = device_id
        data["source"] = {DOMAIN: source}
        resp = await self._call("add_task", data, response=True)
        if resp and resp.get("task_id"):
            self._tasks[key] = resp["task_id"]

    @callback
    def _on_completed(self, event: Event) -> None:
        if event.data.get("origin") == DOMAIN:
            return  # Echo unseres eigenen complete_task
        src = (event.data.get("source") or {}).get(DOMAIN) or {}
        if src.get("entry_id") != self.entry.entry_id:
            return
        key = src.get("issue")
        if key:
            self.hass.async_create_task(self.ctrl.async_resolve(key, ORIGIN_HOME_KEEPER))

    @callback
    def _on_deleted(self, event: Event) -> None:
        task_id = event.data.get("task_id")
        for key, tid in list(self._tasks.items()):
            if tid == task_id:
                self._tasks.pop(key)


async def async_release(hass: HomeAssistant, stored: dict) -> None:
    """Integration removed: delete tasks, release appliances (stock is kept)."""
    if not hass.services.has_service(HK, "list_tasks"):
        return
    for task_id in (stored.get("hk_tasks") or {}).values():
        with contextlib.suppress(Exception):
            await hass.services.async_call(HK, "delete_task", {"task_id": task_id}, blocking=True)
    for asset_id in (stored.get("hk_assets") or {}).values():
        with contextlib.suppress(Exception):
            await hass.services.async_call(
                HK, "update_asset", {"asset_id": asset_id, "managed_by": None}, blocking=True
            )


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = dt_util.parse_datetime(str(value))
    return dt_util.as_utc(parsed) if parsed else None


def _last_completion(task: dict) -> datetime | None:
    comps = task.get("completions") or []
    stamps = [d for c in comps if (d := _parse(c.get("ts") or c.get("completed_at")))]
    if not stamps and task.get("last_completed"):
        stamps = [d for d in [_parse(task["last_completed"])] if d]
    return max(stamps) if stamps else None
