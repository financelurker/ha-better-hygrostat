"""Empty-tank detection with realistic humidity curves.

The curves follow a real case: with a full tank the humidifier brings the room from
43 % to 47 % in about half an hour; with an empty tank humidity rises a little at first
and then falls by only about 0.4 % RH per hour while the humidifier keeps running.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.core import HomeAssistant

from .helpers import HUM, PLUG, POWER, WINDOW, base_states, eid, setup_room

FULL = 0.15  # % RH per minute while running with water: 43 -> 47 in ~27 min
DRYING = -0.05  # % RH per minute while off


def empty_tank(run_min: float) -> float:
    """% RH per minute while running with an empty tank (as in the real case)."""
    return 0.09 if run_min < 20 else -0.4 / 60


class Room:
    """Humidity that follows the humidifier plug, minute by minute."""

    def __init__(self, hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
        self.hass = hass
        self.freezer = freezer
        self.running: Callable[[float], float] = lambda _run_min: FULL
        self.off: float = DRYING
        self.run_min = 0.0
        self.power = False
        self.power_dip = False

    async def run(self, minutes: float, until: Callable[[], bool] | None = None) -> float:
        """Advance *minutes*; stop early when *until* is true. Return elapsed minutes."""
        elapsed = 0.0
        while elapsed < minutes:
            plug_on = self.hass.states.get(PLUG).state == "on"
            self.run_min = self.run_min + 1 if plug_on else 0.0
            rate = self.running(self.run_min) if plug_on else self.off
            humidity = float(self.hass.states.get(HUM).state) + rate
            self.hass.states.async_set(HUM, round(humidity, 3), {"unit_of_measurement": "%"})
            if self.power:
                watts = 20.0 if plug_on and not self.power_dip else 0.4
                self.hass.states.async_set(POWER, watts, {"unit_of_measurement": "W"})
            self.freezer.tick(timedelta(minutes=1))
            async_fire_time_changed(self.hass)
            await self.hass.async_block_till_done()
            elapsed += 1
            if until is not None and until():
                break
        return elapsed


def refill_state(hass: HomeAssistant, entry) -> str:
    return hass.states.get(eid(hass, entry, "binary_sensor", "refill")).state


async def learn_usual_runs(room: Room, entry) -> None:
    """Let the humidifier complete a few normal runs so it learns their length."""
    await room.run(8 * 60)
    ctrl = entry.runtime_data.controller
    assert ctrl.typical_run_min is not None
    assert 20 <= ctrl.typical_run_min <= 35


async def start_empty_run(room: Room) -> None:
    """Wait until the humidifier switches on, then let the tank be empty."""
    await room.run(4 * 60, until=lambda: room.hass.states.get(PLUG).state == "on")
    assert room.hass.states.get(PLUG).state == "on"
    room.running = empty_tank


async def test_real_case_slow_decline_is_detected(hass: HomeAssistant, freezer, plugs) -> None:
    """The reported case: -0.4 % RH/h is too slow for the falling rule; the run is not."""
    base_states(hass, 42.5)
    entry = await setup_room(hass)
    room = Room(hass, freezer)
    await learn_usual_runs(room, entry)
    await start_empty_run(room)

    await room.run(110)
    assert refill_state(hass, entry) == "off"
    await room.run(20)
    refill = hass.states.get(eid(hass, entry, "binary_sensor", "refill"))
    assert refill.state == "on"
    assert refill.attributes["reason"] == "long_run"
    assert hass.states.get(PLUG).state == "on"  # still humidifying (no tank block)

    status = hass.states.get(eid(hass, entry, "sensor", "status")).attributes
    assert status["long_run_limit_min"] == 120
    assert status["run_without_target_min"] >= 120


async def test_refill_resolves_at_target(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 42.5)
    entry = await setup_room(hass)
    room = Room(hass, freezer)
    await learn_usual_runs(room, entry)
    typical = entry.runtime_data.controller.typical_run_min
    await start_empty_run(room)
    await room.run(180, until=lambda: refill_state(hass, entry) == "on")
    assert refill_state(hass, entry) == "on"

    room.running = lambda _run_min: FULL  # refilled without pressing anything
    await room.run(60, until=lambda: refill_state(hass, entry) == "off")
    assert refill_state(hass, entry) == "off"
    since_refill = hass.states.get(eid(hass, entry, "sensor", "runtime_since_refill"))
    assert since_refill.attributes["history_h"]
    # the long empty run was not learned as a usual run
    assert entry.runtime_data.controller.typical_run_min == typical


async def test_restart_keeps_the_measurement(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 42.5)
    entry = await setup_room(hass)
    room = Room(hass, freezer)
    await learn_usual_runs(room, entry)
    await start_empty_run(room)
    await room.run(90)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await room.run(40, until=lambda: refill_state(hass, entry) == "on")
    assert refill_state(hass, entry) == "on"


async def test_short_power_dip_only_pauses(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 42.5)
    hass.states.async_set(POWER, 0.4, {"unit_of_measurement": "W"})
    entry = await setup_room(hass, humidifier_power=POWER)
    room = Room(hass, freezer)
    room.power = True
    await learn_usual_runs(room, entry)
    await start_empty_run(room)
    await room.run(70)

    room.power_dip = True  # e.g. the device restarts or the meter reports 0 W briefly
    await room.run(2)
    room.power_dip = False
    await room.run(65, until=lambda: refill_state(hass, entry) == "on")
    assert refill_state(hass, entry) == "on"
    assert hass.states.get(eid(hass, entry, "binary_sensor", "humidifier_fault")).state == "off"


async def test_weak_device_is_not_empty(hass: HomeAssistant, freezer, plugs) -> None:
    """Runs for hours below the target, but humidity still rises: no alarm."""
    base_states(hass, 40)
    entry = await setup_room(hass)
    room = Room(hass, freezer)
    room.running = lambda _run_min: 0.5 / 60  # +0.5 % RH per hour
    await room.run(7 * 60)
    assert hass.states.get(PLUG).state == "on"
    assert refill_state(hass, entry) == "off"


async def test_plateau_without_history(hass: HomeAssistant, freezer, plugs) -> None:
    """Without learned runs the limit is 3 x the option (6 h): flat humidity then alarms."""
    base_states(hass, 40)
    entry = await setup_room(hass)
    room = Room(hass, freezer)
    room.running = lambda _run_min: 0.0
    await room.run(5 * 60 + 50)
    assert refill_state(hass, entry) == "off"
    await room.run(20)
    refill = hass.states.get(eid(hass, entry, "binary_sensor", "refill"))
    assert refill.state == "on"
    assert refill.attributes["reason"] == "long_run"


async def test_window_does_not_cause_a_false_alarm(hass: HomeAssistant, freezer, plugs) -> None:
    """Airing in the middle of a long run: humidity drops, then rises again with water."""
    base_states(hass, 41)
    entry = await setup_room(hass, tank_long_run=30)  # no history: limit 90 min
    room = Room(hass, freezer)
    room.running = lambda _run_min: 0.03  # slow but steady progress
    await room.run(40)
    assert hass.states.get(PLUG).state == "on"

    hass.states.async_set(WINDOW, "on")
    room.off = -0.1  # airing dries the room
    await room.run(30)
    assert hass.states.get(PLUG).state == "off"
    hass.states.async_set(WINDOW, "off")
    room.off = DRYING
    await room.run(4 * 60, until=lambda: float(hass.states.get(HUM).state) >= 47)
    assert refill_state(hass, entry) == "off"


async def test_falling_rule_still_catches_a_fast_drop(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 42.5)
    entry = await setup_room(hass)
    room = Room(hass, freezer)
    room.running = lambda _run_min: -0.08  # clearly falling although running
    await room.run(100, until=lambda: refill_state(hass, entry) == "on")
    refill = hass.states.get(eid(hass, entry, "binary_sensor", "refill"))
    assert refill.state == "on"
    assert refill.attributes["reason"] == "humidity_falling"
