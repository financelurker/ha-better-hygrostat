"""Home Keeper link, tested against the real Home Keeper integration."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.better_hygrostat.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, entity_registry as er

from .helpers import DEHUM, DEHUM_POWER, advance, base_states, eid, setup_room

pytest.importorskip("custom_components.home_keeper", reason="Home Keeper is not installed")


async def _setup_real_hk(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain="home_keeper", data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service("home_keeper", "add_task")


async def _tasks(hass: HomeAssistant) -> list[dict]:
    resp = await hass.services.async_call(
        "home_keeper", "list_tasks", {}, blocking=True, return_response=True
    )
    return [t for t in resp["tasks"] if (t.get("source") or {}).get(DOMAIN)]


async def test_real_home_keeper_roundtrip(hass: HomeAssistant, freezer, plugs) -> None:
    await _setup_real_hk(hass)
    base_states(hass, 40)
    entry = await setup_room(hass)
    await advance(hass, freezer, 95 * 60, humidity_step=-0.08)
    refill = eid(hass, entry, "binary_sensor", "refill")
    assert hass.states.get(refill).state == "on"

    tasks = await _tasks(hass)
    assert len(tasks) == 1
    task = tasks[0]
    assert task["next_due"] is not None
    assert task["managed_by"]["integration"] == DOMAIN

    # the user completes it in Home Keeper
    await hass.services.async_call(
        "home_keeper", "complete_task", {"task_id": task["id"]}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(refill).state == "off"
    task = (await _tasks(hass))[0]
    assert task["next_due"] is None
    assert len(task["completions"]) == 1

    # empty again -> the same task is armed again
    await advance(hass, freezer, 95 * 60, humidity_step=-0.05)
    assert hass.states.get(refill).state == "on"
    tasks = await _tasks(hass)
    assert len(tasks) == 1
    assert tasks[0]["next_due"] is not None


async def test_home_keeper_loaded_later(hass: HomeAssistant, freezer, plugs) -> None:
    """Issue raised before Home Keeper runs -> the task follows once it starts."""
    base_states(hass, 40)
    entry = await setup_room(hass)
    await advance(hass, freezer, 95 * 60, humidity_step=-0.08)
    assert hass.states.get(eid(hass, entry, "binary_sensor", "refill")).state == "on"

    await _setup_real_hk(hass)
    await advance(hass, freezer, 120)  # allow for a retry
    tasks = await _tasks(hass)
    assert len(tasks) == 1
    assert tasks[0]["next_due"] is not None


# ------------------------------------------------------------- Appliances (0.2)


def _plug_device(hass: HomeAssistant) -> str:
    """Create the plug as a real device in an area."""
    plug_entry = MockConfigEntry(domain="test_plug")
    plug_entry.add_to_hass(hass)
    area = ar.async_get(hass).async_create("Living Room")
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=plug_entry.entry_id,
        identifiers={("test_plug", "plug1")},
        name="Humidifier plug",
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    er.async_get(hass).async_get_or_create(
        "switch", "test_plug", "plug1", device_id=device.id, suggested_object_id="humidifier_plug"
    )
    return device.id


async def _assets(hass: HomeAssistant) -> list[dict]:
    resp = await hass.services.async_call(
        "home_keeper", "list_assets", {}, blocking=True, return_response=True
    )
    return [a for a in resp["assets"] if (a.get("source") or {}).get(DOMAIN)]


async def test_appliance_created_and_tasks_attached(hass: HomeAssistant, freezer, plugs) -> None:
    await _setup_real_hk(hass)
    plug_dev = _plug_device(hass)
    base_states(hass, 40)
    entry = await setup_room(hass)

    assets = await _assets(hass)
    assert len(assets) == 1
    asset = assets[0]
    assert asset["name"] == "Living Room: Humidifier"
    assert asset["kind"] == "virtual"
    assert asset["device_id"]
    assert asset["managed_by"]["integration"] == DOMAIN
    assert plug_dev in asset["related_device_ids"]
    assert asset["area_id"] == "living_room"

    # issue -> the task hangs on the appliance's device
    await advance(hass, freezer, 95 * 60, humidity_step=-0.08)
    task = (await _tasks(hass))[0]
    assert task["device_id"] == asset["device_id"]

    # the name can be changed freely and survives a reload
    await hass.services.async_call(
        "home_keeper",
        "update_asset",
        {"asset_id": asset["id"], "name": "Venta LW45"},
        blocking=True,
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assets = await _assets(hass)
    assert len(assets) == 1
    assert assets[0]["name"] == "Venta LW45"


async def test_dehumidifier_gets_own_appliance(hass: HomeAssistant, freezer, plugs) -> None:
    await _setup_real_hk(hass)
    base_states(hass, 70)
    hass.states.async_set(DEHUM, "off")
    hass.states.async_set(DEHUM_POWER, 0.0, {"unit_of_measurement": "W"})
    entry = await setup_room(hass, dehumidifier=DEHUM, dehumidifier_power=DEHUM_POWER)
    roles = {a["source"][DOMAIN]["role"]: a for a in await _assets(hass)}
    assert set(roles) == {"humidifier", "dehumidifier"}

    hass.states.async_set(DEHUM_POWER, 230.0, {"unit_of_measurement": "W"})
    await advance(hass, freezer, 300)
    hass.states.async_set(DEHUM_POWER, 1.0, {"unit_of_measurement": "W"})
    await advance(hass, freezer, 210)
    task = next(
        t for t in await _tasks(hass) if t["source"][DOMAIN]["issue"] == "dehumidifier_tank"
    )
    assert task["device_id"] == roles["dehumidifier"]["device_id"]

    # dehumidifier removed from the config -> appliance released, kept
    opts = dict(entry.options)
    opts.pop("dehumidifier")
    opts.pop("dehumidifier_power")
    hass.config_entries.async_update_entry(entry, options=opts)
    await hass.async_block_till_done()
    left = {a["source"][DOMAIN]["role"]: a for a in await _assets(hass)}
    assert "dehumidifier" in left
    assert left["dehumidifier"].get("managed_by") is None
    assert left["humidifier"]["managed_by"]["integration"] == DOMAIN


async def test_migrates_v01_task_to_appliance(hass: HomeAssistant, freezer, plugs) -> None:
    """A task from 0.1.0 (on the room device) moves to the new appliance."""
    await _setup_real_hk(hass)
    base_states(hass, 40)
    entry = await setup_room(hass, home_keeper=False)
    await advance(hass, freezer, 95 * 60, humidity_step=-0.08)
    room = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    resp = await hass.services.async_call(
        "home_keeper",
        "add_task",
        {
            "name": "Wohnzimmer: Refill water",
            "recurrence_type": "triggered",
            "device_id": room.id,
            "source": {
                DOMAIN: {"entry_id": entry.entry_id, "issue": "refill", "device_id": room.id}
            },
        },
        blocking=True,
        return_response=True,
    )
    old_id = resp["task_id"]
    opts = {**entry.options, "home_keeper": True}
    hass.config_entries.async_update_entry(entry, options=opts)
    await hass.async_block_till_done()

    tasks = await _tasks(hass)
    asset = (await _assets(hass))[0]
    assert len(tasks) == 1
    assert tasks[0]["id"] == old_id
    assert tasks[0]["device_id"] == asset["device_id"]
    assert tasks[0]["source"][DOMAIN]["device_id"] == asset["device_id"]


async def test_user_deleted_appliance_is_respected(hass: HomeAssistant, freezer, plugs) -> None:
    await _setup_real_hk(hass)
    base_states(hass, 40)
    entry = await setup_room(hass)
    asset = (await _assets(hass))[0]
    await hass.services.async_call(
        "home_keeper", "delete_asset", {"asset_id": asset["id"]}, blocking=True
    )
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert await _assets(hass) == []

    # tasks then land on the room device
    await advance(hass, freezer, 95 * 60, humidity_step=-0.08)
    room = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert (await _tasks(hass))[0]["device_id"] == room.id


async def test_remove_entry_releases_appliance(hass: HomeAssistant, freezer, plugs) -> None:
    await _setup_real_hk(hass)
    base_states(hass, 40)
    entry = await setup_room(hass)
    await advance(hass, freezer, 95 * 60, humidity_step=-0.08)
    assert len(await _tasks(hass)) == 1
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert await _tasks(hass) == []
    assets = await _assets(hass)
    assert len(assets) == 1
    assert assets[0].get("managed_by") is None


async def test_cleaning_task_draws_hygiene_additive(hass: HomeAssistant, freezer, plugs) -> None:
    """README tip: link the cleaning task to a consumable part."""
    await _setup_real_hk(hass)
    base_states(hass, 35)
    entry = await setup_room(hass, cleaning_interval=1)
    asset = (await _assets(hass))[0]
    await hass.services.async_call(
        "home_keeper",
        "update_asset",
        {
            "asset_id": asset["id"],
            "parts": [
                {"name": "Hygiene additive", "type": "consumable", "stock": 3, "reorder_at": 1},
            ],
        },
        blocking=True,
    )
    part_id = (await _assets(hass))[0]["parts"][0]["id"]

    await advance(hass, freezer, 65 * 60, step=60)  # 1 h of runtime -> cleaning due
    task = next(t for t in await _tasks(hass) if t["source"][DOMAIN]["issue"] == "cleaning")
    await hass.services.async_call(
        "home_keeper",
        "set_task_consumable",
        {"task_id": task["id"], "asset_id": asset["id"], "part_id": part_id},
        blocking=True,
    )
    await hass.services.async_call(
        "home_keeper", "complete_task", {"task_id": task["id"]}, blocking=True
    )
    await hass.async_block_till_done()
    assert (await _assets(hass))[0]["parts"][0]["stock"] == 2
    assert hass.states.get(eid(hass, entry, "binary_sensor", "cleaning")).state == "off"
    assert float(hass.states.get(eid(hass, entry, "sensor", "runtime_since_cleaning")).state) == 0
