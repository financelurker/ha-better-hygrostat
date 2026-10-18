"""End-to-end tests of the hygrostat in a real Home Assistant test instance."""

from __future__ import annotations

from custom_components.better_hygrostat.const import DEFAULTS, DOMAIN
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .helpers import (
    DEHUM,
    DEHUM_POWER,
    HUM,
    OUT_H,
    OUT_T,
    PLUG,
    POWER,
    TEMP,
    WINDOW,
    advance,
    base_states,
    eid,
    setup_room,
)


async def test_config_flow(hass: HomeAssistant) -> None:
    base_states(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Bedroom",
            "humidity_sensor": HUM,
            "temperature_sensor": TEMP,
            "humidifier": PLUG,
        },
    )
    assert result["step_id"] == "dehumidifier"
    # the same switch as dehumidifier -> error
    bad = await hass.config_entries.flow.async_configure(result["flow_id"], {"dehumidifier": PLUG})
    assert bad["errors"] == {"dehumidifier": "same_device"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "windows"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"windows": [WINDOW]}
    )
    assert result["step_id"] == "outdoor"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bedroom"
    assert result["options"]["windows"] == [WINDOW]
    assert "dehumidifier" not in result["options"]


async def test_options_flow_menu(hass: HomeAssistant, plugs) -> None:
    base_states(hass)
    entry = await setup_room(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "control"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **{
                k: DEFAULTS[k]
                for k in (
                    "dry_tolerance",
                    "wet_tolerance",
                    "min_on",
                    "min_off",
                    "changeover_lock",
                    "sensor_stale",
                )
            },
            "target_low": 40,
            "target_high": 42,
        },
    )
    assert result["errors"] == {"target_high": "deadband"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **{
                k: DEFAULTS[k]
                for k in (
                    "dry_tolerance",
                    "wet_tolerance",
                    "min_on",
                    "min_off",
                    "changeover_lock",
                    "sensor_stale",
                )
            },
            "target_low": 40,
            "target_high": 60,
        },
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "save"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    hygro = eid(hass, entry, "humidifier", "hygrostat")
    assert hass.states.get(hygro).attributes["humidity"] == 40


async def test_humidify_and_window(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 35)
    entry = await setup_room(hass)
    hygro = eid(hass, entry, "humidifier", "hygrostat")
    status = eid(hass, entry, "sensor", "status")

    assert hass.states.get(PLUG).state == "on"
    assert hass.states.get(hygro).attributes["action"] == "humidifying"

    # window open briefly (below the delay) -> stays on
    hass.states.async_set(WINDOW, "on")
    await hass.async_block_till_done()
    await advance(hass, freezer, 30)
    assert hass.states.get(PLUG).state == "on"
    # after 45 s -> off, even before the minimum on time is over
    await advance(hass, freezer, 30)
    assert hass.states.get(PLUG).state == "off"
    assert hass.states.get(status).state == "window_open"

    # closed: on again only after 10 min
    hass.states.async_set(WINDOW, "off")
    await hass.async_block_till_done()
    await advance(hass, freezer, 300)
    assert hass.states.get(PLUG).state == "off"
    await advance(hass, freezer, 330)
    assert hass.states.get(PLUG).state == "on"

    # target reached -> off only after the minimum on time
    hass.states.async_set(HUM, 48, {"unit_of_measurement": "%"})
    await advance(hass, freezer, 60)
    assert hass.states.get(PLUG).state == "on"
    await advance(hass, freezer, 600)
    assert hass.states.get(PLUG).state == "off"
    assert hass.states.get(status).state == "idle"


async def test_hygrostat_off_leaves_plug_alone(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 35)
    entry = await setup_room(hass)
    hygro = eid(hass, entry, "humidifier", "hygrostat")
    assert hass.states.get(PLUG).state == "on"
    await hass.services.async_call("humidifier", "turn_off", {"entity_id": hygro}, blocking=True)
    assert hass.states.get(PLUG).state == "off"
    # switched on by hand: left alone
    hass.states.async_set(PLUG, "on")
    await advance(hass, freezer, 120)
    assert hass.states.get(PLUG).state == "on"


async def test_sensor_unavailable_switches_off(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 35)
    entry = await setup_room(hass)
    assert hass.states.get(PLUG).state == "on"
    hass.states.async_set(HUM, "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(PLUG).state == "off"
    assert hass.states.get(eid(hass, entry, "sensor", "status")).state == "sensor_error"


async def test_equilibrium_is_not_empty(hass: HomeAssistant, freezer, plugs) -> None:
    """Too weak a device: humidity levels off -> no false alarm."""
    base_states(hass, 40)
    entry = await setup_room(hass)
    await advance(hass, freezer, 120 * 60, humidity_step=0.0)
    assert hass.states.get(eid(hass, entry, "binary_sensor", "refill")).state == "off"


async def test_works_without_home_keeper(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 40)
    entry = await setup_room(hass)
    await advance(hass, freezer, 95 * 60, humidity_step=-0.08)
    assert hass.states.get(eid(hass, entry, "binary_sensor", "refill")).state == "on"


async def test_power_fault(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 35)
    hass.states.async_set(POWER, 0.0, {"unit_of_measurement": "W"})
    entry = await setup_room(hass, humidifier_power=POWER)
    fault = eid(hass, entry, "binary_sensor", "humidifier_fault")
    assert hass.states.get(PLUG).state == "on"
    await advance(hass, freezer, 150)
    assert hass.states.get(fault).state == "off"
    await advance(hass, freezer, 60)
    assert hass.states.get(fault).state == "on"
    hass.states.async_set(POWER, 18.0, {"unit_of_measurement": "W"})
    await hass.async_block_till_done()
    assert hass.states.get(fault).state == "off"


async def test_condensation_limit_lowers_target(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 42)
    hass.states.async_set(OUT_T, -10.0, {"unit_of_measurement": "°C"})
    hass.states.async_set(OUT_H, 85.0, {"unit_of_measurement": "%"})
    entry = await setup_room(hass, outdoor_temperature=OUT_T, outdoor_humidity=OUT_H)
    target = hass.states.get(eid(hass, entry, "sensor", "effective_target"))
    assert float(target.state) == 35.0
    # 42 % is above the limit -> no humidifying
    assert hass.states.get(PLUG).state == "off"


async def test_season_override(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 35)
    entry = await setup_room(hass)
    select = eid(hass, entry, "select", "season_override")
    await hass.services.async_call(
        "select", "select_option", {"entity_id": select, "option": "off"}, blocking=True
    )
    await advance(hass, freezer, 30)
    assert hass.states.get(PLUG).state == "off"


async def test_dehumidifier_and_tank_full(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 70)
    hass.states.async_set(DEHUM, "off")
    hass.states.async_set(DEHUM_POWER, 0.0, {"unit_of_measurement": "W"})
    entry = await setup_room(hass, dehumidifier=DEHUM, dehumidifier_power=DEHUM_POWER)
    hygro = eid(hass, entry, "humidifier", "hygrostat")
    tank = eid(hass, entry, "binary_sensor", "dehumidifier_tank")
    fault = eid(hass, entry, "binary_sensor", "dehumidifier_fault")

    assert hass.states.get(DEHUM).state == "on"
    assert hass.states.get(PLUG).state == "off"
    assert hass.states.get(hygro).attributes["action"] == "drying"
    assert hass.states.get(hygro).attributes["available_modes"] == [
        "auto",
        "humidify",
        "dehumidify",
    ]

    hass.states.async_set(DEHUM_POWER, 230.0, {"unit_of_measurement": "W"})
    await advance(hass, freezer, 300)
    hass.states.async_set(DEHUM_POWER, 1.0, {"unit_of_measurement": "W"})
    await advance(hass, freezer, 210)
    assert hass.states.get(tank).state == "on"
    assert hass.states.get(fault).state == "off"
    assert hass.states.get(DEHUM).state == "on"  # stays on -> notices the emptying

    hass.states.async_set(DEHUM_POWER, 220.0, {"unit_of_measurement": "W"})
    await advance(hass, freezer, 30)
    assert hass.states.get(tank).state == "off"


async def test_changeover_lock(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 70)
    hass.states.async_set(DEHUM, "off")
    await setup_room(hass, dehumidifier=DEHUM, min_on=0, min_off=0)
    assert hass.states.get(DEHUM).state == "on"
    # suddenly dry: dehumidifier off, humidifier only after the changeover lock
    hass.states.async_set(HUM, 30, {"unit_of_measurement": "%"})
    await advance(hass, freezer, 60)
    assert hass.states.get(DEHUM).state == "off"
    assert hass.states.get(PLUG).state == "off"
    await advance(hass, freezer, 30 * 60)
    assert hass.states.get(PLUG).state == "on"


async def test_unload_and_restore(hass: HomeAssistant, freezer, plugs) -> None:
    base_states(hass, 35)
    entry = await setup_room(hass)
    hygro = eid(hass, entry, "humidifier", "hygrostat")
    await hass.services.async_call(
        "humidifier", "set_humidity", {"entity_id": hygro, "humidity": 50}, blocking=True
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(hygro).attributes["humidity"] == 50
