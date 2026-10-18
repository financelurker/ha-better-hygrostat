"""Home Keeper link, tested against Home Keeper's official test fake."""

from __future__ import annotations

from datetime import timedelta

import pytest

from custom_components.better_hygrostat.const import DOMAIN
from homeassistant.core import HomeAssistant

from .helpers import OUT_H, OUT_T, PLUG, advance, base_states, eid, setup_room

testing = pytest.importorskip(
    "custom_components.home_keeper.testing", reason="Home Keeper is not installed"
)
async_setup_fake_home_keeper = testing.async_setup_fake_home_keeper


async def test_empty_tank_home_keeper_roundtrip(hass: HomeAssistant, freezer, plugs) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    base_states(hass, 40)
    entry = await setup_room(hass)
    refill = eid(hass, entry, "binary_sensor", "refill")
    since_refill = eid(hass, entry, "sensor", "runtime_since_refill")
    assert hass.states.get(PLUG).state == "on"

    # 50 min of falling humidity -> too early (min runtime 60 min, window 90 min)
    await advance(hass, freezer, 50 * 60, humidity_step=-0.08)
    assert hass.states.get(refill).state == "off"
    # still falling at 95 min -> tank empty
    await advance(hass, freezer, 45 * 60, humidity_step=-0.08)
    assert hass.states.get(refill).state == "on"
    assert float(hass.states.get(since_refill).state) > 1.0

    task = hk.get_task_by_source(DOMAIN, entry_id=entry.entry_id, issue="refill")
    assert task is not None
    assert task["recurrence_type"] == "triggered"
    assert task["next_due"] is not None  # scharf
    assert task["managed_by"]["integration"] == DOMAIN

    # completed in Home Keeper -> resolved here, counter reset
    hk.fire_user_completion(task["id"])
    await hass.async_block_till_done()
    assert hass.states.get(refill).state == "off"
    assert float(hass.states.get(since_refill).state) == 0.0
    assert hass.states.get(since_refill).attributes["history_h"]
    # no echo loop: exactly one completion
    assert len(hk.tasks[task["id"]]["completions"]) == 1


async def test_empty_tank_auto_clear_completes_task(hass: HomeAssistant, freezer, plugs) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    base_states(hass, 40)
    entry = await setup_room(hass)
    refill = eid(hass, entry, "binary_sensor", "refill")
    await advance(hass, freezer, 95 * 60, humidity_step=-0.08)
    assert hass.states.get(refill).state == "on"
    task = hk.get_task_by_source(DOMAIN, entry_id=entry.entry_id, issue="refill")

    # refilled without pressing anything: humidity clearly rises again
    await advance(hass, freezer, 35 * 60, humidity_step=0.08)
    assert hass.states.get(refill).state == "off"
    assert hk.tasks[task["id"]]["next_due"] is None  # completed in HK (dormant)
    assert len(hk.tasks[task["id"]]["completions"]) == 1


async def test_button_resolves_and_completes_task(hass: HomeAssistant, freezer, plugs) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    base_states(hass, 40)
    entry = await setup_room(hass)
    await advance(hass, freezer, 95 * 60, humidity_step=-0.08)
    task = hk.get_task_by_source(DOMAIN, entry_id=entry.entry_id, issue="refill")
    assert task is not None
    button = eid(hass, entry, "button", "refilled")
    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(eid(hass, entry, "binary_sensor", "refill")).state == "off"
    assert hk.tasks[task["id"]]["next_due"] is None


async def test_season_from_outdoor_and_cleaning_task(hass: HomeAssistant, freezer, plugs) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    base_states(hass, 35)
    hass.states.async_set(OUT_T, 25.0, {"unit_of_measurement": "°C"})
    hass.states.async_set(OUT_H, 70.0, {"unit_of_measurement": "%"})
    entry = await setup_room(hass, outdoor_temperature=OUT_T, outdoor_humidity=OUT_H)
    season = eid(hass, entry, "binary_sensor", "humidifying_season")
    status = eid(hass, entry, "sensor", "status")

    # summer: no humidifying despite 35 %
    assert hass.states.get(season).state == "off"
    assert hass.states.get(PLUG).state == "off"
    assert hass.states.get(status).state == "season_inactive"

    # cold, damp outdoor air -> 24 h mean drops -> season starts
    hass.states.async_set(OUT_T, 0.0, {"unit_of_measurement": "°C"})
    hass.states.async_set(OUT_H, 80.0, {"unit_of_measurement": "%"})
    await advance(hass, freezer, 60 * 60, step=60)
    assert hass.states.get(season).state == "on"
    assert hass.states.get(PLUG).state == "on"
    assert hass.states.get(eid(hass, entry, "binary_sensor", "cleaning")).state == "on"
    assert hk.get_task_by_source(DOMAIN, entry_id=entry.entry_id, issue="cleaning")


async def test_reconcile_completion_while_unloaded(hass: HomeAssistant, freezer, plugs) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    base_states(hass, 40)
    entry = await setup_room(hass)
    await advance(hass, freezer, 95 * 60, humidity_step=-0.08)
    task = hk.get_task_by_source(DOMAIN, entry_id=entry.entry_id, issue="refill")
    assert task is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=5))
    hk.fire_user_completion(task["id"])  # while we are not running
    await hass.async_block_till_done()

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(eid(hass, entry, "binary_sensor", "refill")).state == "off"
    # no duplicate task on restart
    assert len([t for t in hk.tasks.values() if (t.get("source") or {}).get(DOMAIN)]) == 1


async def test_season_end_requests_storage(hass: HomeAssistant, freezer, plugs) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    base_states(hass, 35)
    hass.states.async_set(OUT_T, 0.0, {"unit_of_measurement": "°C"})
    hass.states.async_set(OUT_H, 80.0, {"unit_of_measurement": "%"})
    entry = await setup_room(hass, outdoor_temperature=OUT_T, outdoor_humidity=OUT_H)
    assert hass.states.get(PLUG).state == "on"
    # 2 h of runtime in the season
    await advance(hass, freezer, 2 * 3600, step=60)
    # spring: warm and damp -> season ends once the mean changes
    hass.states.async_set(OUT_T, 22.0, {"unit_of_measurement": "°C"})
    hass.states.async_set(OUT_H, 70.0, {"unit_of_measurement": "%"})
    await advance(hass, freezer, 24 * 3600, step=300)
    assert hass.states.get(eid(hass, entry, "binary_sensor", "humidifying_season")).state == "off"
    assert hass.states.get(eid(hass, entry, "binary_sensor", "storage")).state == "on"
    assert hass.states.get(PLUG).state == "off"
    assert hk.get_task_by_source(DOMAIN, entry_id=entry.entry_id, issue="storage")


async def test_german_task_names(hass: HomeAssistant, freezer, plugs) -> None:
    hass.config.language = "de"
    hk = await async_setup_fake_home_keeper(hass)
    base_states(hass, 40)
    entry = await setup_room(hass, title="Wohnzimmer")
    await advance(hass, freezer, 95 * 60, humidity_step=-0.08)
    task = hk.get_task_by_source(DOMAIN, entry_id=entry.entry_id, issue="refill")
    assert task["name"] == "Wohnzimmer: Wasser nachfüllen"


async def test_english_task_names(hass: HomeAssistant, freezer, plugs) -> None:
    hk = await async_setup_fake_home_keeper(hass)
    base_states(hass, 40)
    entry = await setup_room(hass)
    await advance(hass, freezer, 95 * 60, humidity_step=-0.08)
    task = hk.get_task_by_source(DOMAIN, entry_id=entry.entry_id, issue="refill")
    assert task["name"] == "Living Room: Refill water"
