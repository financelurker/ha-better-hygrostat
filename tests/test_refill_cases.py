"""Regression cases from real nights, and what an unclean restart must not break.

Both cases are kept as they happened; a change that makes one of them pass must not make
the other fail.

- 2026-11-03: after the usual short runs the tank runs dry; humidity rises ~1.8 % in the
  first 20 minutes, then falls by only ~0.4 % RH per hour (see also test_tank.py).
- 2026-11-15: the humidifier starts at 37.5 % and brings the room to ~44.1 % in about
  2.5 hours, then the tank is empty and humidity falls by ~0.68 % RH per hour. Home
  Assistant restarted uncleanly at ~02:56 (run minute ~158) and the state on disk was
  from before the run, so the runtime counter started over.
"""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.better_hygrostat.const import DOMAIN
from homeassistant.core import HomeAssistant

from .helpers import HUM, PLUG, base_states, eid, setup_room
from .test_tank import Room, empty_tank, learn_usual_runs, refill_state, start_empty_run


def case_20261115(run_min: float) -> float:
    """% RH per minute while running in the 2026-11-15 night (from 37.5 %)."""
    if run_min < 150:
        return 0.088 * (1 - run_min / 150)  # +6.6 % in 2.5 h, levelling off
    return -0.68 / 60


def storage_key(entry: MockConfigEntry) -> str:
    return f"{DOMAIN}.{entry.entry_id}"


async def start_case_20261115(hass: HomeAssistant, room: Room, entry) -> None:
    """Learn the usual runs, then start the night run at 37.5 % with an empty tank."""
    await learn_usual_runs(room, entry)
    await room.run(4 * 60, until=lambda: hass.states.get(PLUG).state == "off")
    room.running = case_20261115
    hass.states.async_set(HUM, 37.5, {"unit_of_measurement": "%"})
    await room.run(30, until=lambda: hass.states.get(PLUG).state == "on")
    assert hass.states.get(PLUG).state == "on"


async def unclean_restart(hass: HomeAssistant, entry, hass_storage: dict, old: dict) -> None:
    """Restart with *old* as the state on disk, as after a crash or power cut."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hass_storage[storage_key(entry)]["data"] = old
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def before_this_run(hass_storage: dict, entry) -> dict:
    """The stored state as if the last write had happened before the current run."""
    data = dict(hass_storage[storage_key(entry)]["data"])
    data.update(
        {"hum_unsatisfied_s": 0.0, "tank_samples": [], "tank_since": None, "tank_peak": None}
    )
    return data


def reason(hass: HomeAssistant, entry) -> str | None:
    return hass.states.get(eid(hass, entry, "binary_sensor", "refill")).attributes["reason"]


# ------------------------------------------------------------------ persistence


async def test_state_is_stored_while_running(
    hass: HomeAssistant, freezer, plugs, hass_storage
) -> None:
    """The cause of 2026-11-15: the state was only written on a clean shutdown."""
    base_states(hass, 40)
    entry = await setup_room(hass)
    room = Room(hass, freezer)
    room.running = lambda _run_min: 0.01
    await room.run(30)

    stored = hass_storage[storage_key(entry)]["data"]
    assert stored["hum_unsatisfied_s"] >= 20 * 60
    assert stored["tank_samples"]


async def test_unclean_restart_keeps_the_measurement(
    hass: HomeAssistant, freezer, plugs, hass_storage
) -> None:
    """With the state written while running, a crash loses at most a few minutes."""
    base_states(hass, 42.5)
    entry = await setup_room(hass)
    room = Room(hass, freezer)
    await learn_usual_runs(room, entry)
    await start_empty_run(room)
    await room.run(90)

    on_disk = dict(hass_storage[storage_key(entry)]["data"])  # what a crash would leave
    await unclean_restart(hass, entry, hass_storage, on_disk)
    assert entry.runtime_data.controller.data["hum_unsatisfied_s"] >= 80 * 60
    await room.run(45, until=lambda: refill_state(hass, entry) == "on")
    assert refill_state(hass, entry) == "on"


# ------------------------------------------------------------- case 2026-11-15


async def test_case_20261115_detected(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 42.5)
    entry = await setup_room(hass)
    room = Room(hass, freezer)
    await start_case_20261115(hass, room, entry)

    await room.run(119)
    assert refill_state(hass, entry) == "off"  # still rising: not empty yet
    elapsed = 119 + await room.run(100, until=lambda: refill_state(hass, entry) == "on")
    assert refill_state(hass, entry) == "on"
    assert elapsed <= 215  # by ~03:33; nothing came before 04:40 in reality
    assert reason(hass, entry) in ("long_run", "below_peak")


async def test_case_20261115_after_unclean_restart(
    hass: HomeAssistant, freezer, plugs, hass_storage
) -> None:
    """As it happened: the counter starts over at run minute 158; the peak rule still fires."""
    base_states(hass, 42.5)
    entry = await setup_room(hass)
    room = Room(hass, freezer)
    await start_case_20261115(hass, room, entry)
    old = before_this_run(hass_storage, entry)
    await room.run(158)
    assert refill_state(hass, entry) in ("off", "on")

    await unclean_restart(hass, entry, hass_storage, old)
    if refill_state(hass, entry) == "on":
        return  # already detected before the crash
    elapsed = 158 + await room.run(100, until=lambda: refill_state(hass, entry) == "on")
    assert refill_state(hass, entry) == "on"
    assert elapsed <= 245  # by ~04:23, before the 04:40 of the real night
    assert reason(hass, entry) == "below_peak"


# ------------------------------------------------------------- case 2026-11-03


async def test_case_20261103_after_unclean_restart(
    hass: HomeAssistant, freezer, plugs, hass_storage
) -> None:
    """The first real case, with the counter lost in the middle of the night."""
    base_states(hass, 42.5)
    entry = await setup_room(hass)
    room = Room(hass, freezer)
    await learn_usual_runs(room, entry)
    await start_empty_run(room)
    assert room.running is empty_tank
    old = before_this_run(hass_storage, entry)
    await room.run(90)
    assert refill_state(hass, entry) == "off"

    await unclean_restart(hass, entry, hass_storage, old)
    elapsed = 90 + await room.run(150, until=lambda: refill_state(hass, entry) == "on")
    assert refill_state(hass, entry) == "on"
    assert elapsed <= 225


# ---------------------------------------------------------------- no false alarm


async def test_spike_while_running_is_not_empty(hass: HomeAssistant, freezer, plugs) -> None:
    """Moisture from elsewhere (shower, cooking) lifts the peak, then decays: no alarm."""
    base_states(hass, 42)
    entry = await setup_room(hass, tank_long_run=720)  # keep the long-run rule out of it
    room = Room(hass, freezer)

    def spike(run_min: float) -> float:
        if 10 <= run_min < 15:
            return 0.6  # +3 % in 5 min
        if 15 <= run_min < 45:
            return -0.1  # back to 42 % within 30 min
        return 0.0

    room.running = spike
    await room.run(4 * 60)
    assert hass.states.get(PLUG).state == "on"
    assert refill_state(hass, entry) == "off"
