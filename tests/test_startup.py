"""Restarts: window contacts that come up late must not switch the humidifier on."""

from __future__ import annotations

import pytest

from custom_components.better_hygrostat.const import DEFAULTS, DOMAIN
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant

from .helpers import HUM, PLUG, TEMP, WINDOW, advance, base_states, eid, setup_room


async def _reload(hass: HomeAssistant, entry) -> None:
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_restart_with_open_window_and_late_contact(
    hass: HomeAssistant, freezer, plugs
) -> None:
    """The reported case: window open, restart, contact unavailable for a while."""
    base_states(hass, 35)
    hass.states.async_set(WINDOW, "on")
    entry = await setup_room(hass)
    status = eid(hass, entry, "sensor", "status")
    assert hass.states.get(PLUG).state == "off"
    assert hass.states.get(status).state == "window_open"

    # restart: the contact is unavailable until its integration has loaded
    hass.states.async_set(WINDOW, "unavailable")
    await _reload(hass, entry)
    assert hass.states.get(PLUG).state == "off"
    assert hass.states.get(status).state == "window_open"  # remembered from before

    await advance(hass, freezer, 60)
    assert hass.states.get(PLUG).state == "off"

    # the contact comes back: still open
    hass.states.async_set(WINDOW, "on")
    await advance(hass, freezer, 60)
    assert hass.states.get(PLUG).state == "off"
    assert plugs.count(("turn_on", PLUG)) == 0  # never switched on

    # closed: the normal close delay applies
    hass.states.async_set(WINDOW, "off")
    await advance(hass, freezer, 300)
    assert hass.states.get(PLUG).state == "off"
    await advance(hass, freezer, 330)
    assert hass.states.get(PLUG).state == "on"


async def test_unavailable_contact_blocks_until_known(hass: HomeAssistant, freezer, plugs) -> None:
    """Window closed before the restart; the contact comes back closed: no delay."""
    base_states(hass, 50)
    entry = await setup_room(hass)
    status = eid(hass, entry, "sensor", "status")
    window = eid(hass, entry, "binary_sensor", "window_open")

    hass.states.async_set(WINDOW, "unavailable")
    hass.states.async_set(HUM, 35, {"unit_of_measurement": "%"})
    await _reload(hass, entry)
    assert hass.states.get(PLUG).state == "off"
    assert hass.states.get(status).state == "window_unknown"
    assert hass.states.get(window).state == "unknown"

    hass.states.async_set(WINDOW, "off")
    await advance(hass, freezer, 30)
    assert hass.states.get(PLUG).state == "on"
    assert hass.states.get(window).state == "off"


async def test_contact_back_open_blocks_at_once(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 50)
    entry = await setup_room(hass)
    hass.states.async_set(WINDOW, "unavailable")
    hass.states.async_set(HUM, 35, {"unit_of_measurement": "%"})
    await _reload(hass, entry)

    hass.states.async_set(WINDOW, "on")
    await hass.async_block_till_done()
    assert hass.states.get(PLUG).state == "off"
    assert hass.states.get(eid(hass, entry, "sensor", "status")).state == "window_open"
    await advance(hass, freezer, 120)
    assert hass.states.get(PLUG).state == "off"


async def test_dead_contact_is_ignored_after_30_min(
    hass: HomeAssistant, freezer, plugs, caplog: pytest.LogCaptureFixture
) -> None:
    base_states(hass, 35)
    hass.states.async_set(WINDOW, "unavailable")
    entry = await setup_room(hass)
    assert hass.states.get(PLUG).state == "off"

    await advance(hass, freezer, 29 * 60, step=60)
    assert hass.states.get(PLUG).state == "off"
    await advance(hass, freezer, 2 * 60, step=60)
    assert hass.states.get(PLUG).state == "on"
    assert hass.states.get(eid(hass, entry, "sensor", "status")).state == "humidifying"
    assert "is ignored until it reports again" in caplog.text


async def test_startup_hold_after_home_assistant_start(hass: HomeAssistant, freezer, plugs) -> None:
    """During a Home Assistant start nothing is switched on for 30 s."""
    base_states(hass, 35)
    hass.set_state(CoreState.not_running)
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    opts = {
        **DEFAULTS,
        "humidity_sensor": HUM,
        "temperature_sensor": TEMP,
        "humidifier": PLUG,
        "windows": [WINDOW],
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Living Room", data={}, options=opts)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(PLUG).state == "off"  # not started yet

    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert hass.states.get(PLUG).state == "off"
    await advance(hass, freezer, 20, step=10)
    assert hass.states.get(PLUG).state == "off"
    await advance(hass, freezer, 20, step=10)
    assert hass.states.get(PLUG).state == "on"


async def test_startup_hold_does_not_delay_switching_off(
    hass: HomeAssistant, freezer, plugs
) -> None:
    base_states(hass, 35)
    hass.states.async_set(PLUG, "on")
    hass.states.async_set(WINDOW, "on")
    hass.set_state(CoreState.not_running)
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    opts = {
        **DEFAULTS,
        "humidity_sensor": HUM,
        "temperature_sensor": TEMP,
        "humidifier": PLUG,
        "windows": [WINDOW],
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Living Room", data={}, options=opts)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert hass.states.get(PLUG).state == "off"
