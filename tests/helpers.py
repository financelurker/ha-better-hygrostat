"""Shared helpers for the tests."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.better_hygrostat.const import DEFAULTS, DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

HUM = "sensor.room_humidity"
TEMP = "sensor.room_temperature"
PLUG = "switch.humidifier_plug"
POWER = "sensor.humidifier_power"
DEHUM = "switch.dehumidifier_plug"
DEHUM_POWER = "sensor.dehumidifier_power"
WINDOW = "binary_sensor.window"
OUT_T = "sensor.outdoor_temperature"
OUT_H = "sensor.outdoor_humidity"
ROOM = "Living Room"


def base_states(hass: HomeAssistant, humidity: float = 35.0) -> None:
    """Set the room sensors, the plug and the window."""
    hass.states.async_set(HUM, humidity, {"unit_of_measurement": "%"})
    hass.states.async_set(TEMP, 21.0, {"unit_of_measurement": "°C"})
    hass.states.async_set(PLUG, "off")
    hass.states.async_set(WINDOW, "off")


async def setup_room(hass: HomeAssistant, title: str = ROOM, **options) -> MockConfigEntry:
    """Set up a room with the defaults plus *options*."""
    opts = {
        **DEFAULTS,
        "humidity_sensor": HUM,
        "temperature_sensor": TEMP,
        "humidifier": PLUG,
        "windows": [WINDOW],
        **options,
    }
    entry = MockConfigEntry(domain=DOMAIN, title=title, data={}, options=opts)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def eid(hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str) -> str:
    """Return the entity id of an entity of the room."""
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, f"{platform}.{key} missing"
    return entity_id


async def advance(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    seconds: float,
    humidity_step: float = 0.0,
    step: float = 30.0,
) -> None:
    """Move time forward; optionally change the room humidity per minute."""
    elapsed = 0.0
    while elapsed < seconds:
        freezer.tick(timedelta(seconds=step))
        elapsed += step
        current = float(hass.states.get(HUM).state)
        hass.states.async_set(
            HUM, round(current + humidity_step * step / 60, 3), {"unit_of_measurement": "%"}
        )
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
