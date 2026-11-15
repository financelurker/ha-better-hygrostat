"""Tasks show in Home Keeper right away (dormant, under Monitored), not only on a problem."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.better_hygrostat.const import DOMAIN
from homeassistant.core import HomeAssistant

from .helpers import POWER, base_states, setup_room

pytest.importorskip("custom_components.home_keeper", reason="Home Keeper is not installed")


async def _setup_hk(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain="home_keeper", data={}, options={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _tasks(hass: HomeAssistant) -> dict[str, dict]:
    resp = await hass.services.async_call(
        "home_keeper", "list_tasks", {}, blocking=True, return_response=True
    )
    return {
        t["source"][DOMAIN]["issue"]: t
        for t in resp["tasks"]
        if (t.get("source") or {}).get(DOMAIN)
    }


async def test_monitoring_tasks_exist_from_the_start(hass: HomeAssistant, plugs) -> None:
    await _setup_hk(hass)
    base_states(hass, 50)  # nothing to do, no problem
    await setup_room(hass)

    tasks = await _tasks(hass)
    assert set(tasks) == {"refill", "cleaning", "storage"}  # no power sensor: no fault task
    for task in tasks.values():
        assert task["next_due"] is None  # dormant: shown under Monitored, not due
        assert task["managed_by"]["integration"] == DOMAIN
        assert len(task["completions"]) == 1
        assert task["completions"][0]["note"] == "Monitoring started - no work done yet."
    assert tasks["refill"]["name"] == "Living Room: Refill water"


async def test_fault_task_with_a_power_sensor(hass: HomeAssistant, plugs) -> None:
    await _setup_hk(hass)
    base_states(hass, 50)
    hass.states.async_set(POWER, 0.4, {"unit_of_measurement": "W"})
    await setup_room(hass, humidifier_power=POWER)
    assert set(await _tasks(hass)) == {"refill", "cleaning", "storage", "humidifier_fault"}


async def test_german_monitoring_note(hass: HomeAssistant, plugs) -> None:
    hass.config.language = "de"
    await _setup_hk(hass)
    base_states(hass, 50)
    await setup_room(hass, title="Büro")
    tasks = await _tasks(hass)
    assert tasks["refill"]["name"] == "Büro: Wasser nachfüllen"
    assert tasks["refill"]["completions"][0]["note"].startswith("Überwachung gestartet")


async def test_restart_creates_no_duplicates(hass: HomeAssistant, plugs) -> None:
    await _setup_hk(hass)
    base_states(hass, 50)
    entry = await setup_room(hass)
    before = {k: t["id"] for k, t in (await _tasks(hass)).items()}
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    after = await _tasks(hass)
    assert {k: t["id"] for k, t in after.items()} == before
    assert all(len(t["completions"]) == 1 for t in after.values())


async def test_deleted_monitoring_task_is_not_created_again(hass: HomeAssistant, plugs) -> None:
    await _setup_hk(hass)
    base_states(hass, 50)
    entry = await setup_room(hass)
    cleaning = (await _tasks(hass))["cleaning"]
    await hass.services.async_call(
        "home_keeper", "delete_task", {"task_id": cleaning["id"], "force": True}, blocking=True
    )
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert set(await _tasks(hass)) == {"refill", "storage"}
