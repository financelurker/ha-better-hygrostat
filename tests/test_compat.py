"""Keys that existing installations depend on must not change.

Unique ids, the storage key and the option keys tie a running installation to its
entities, history, counters and Home Keeper tasks. Changing any of them would turn an
update into a new installation.
"""

from __future__ import annotations

from custom_components.better_hygrostat import const
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .helpers import DEHUM, base_states, setup_room

EXPECTED_KEYS = {
    "humidifier": {"hygrostat"},
    "sensor": {
        "status",
        "absolute_humidity",
        "dew_point",
        "effective_target",
        "humidifier_runtime",
        "runtime_since_refill",
        "runtime_since_cleaning",
        "dehumidifier_runtime",
    },
    "binary_sensor": {
        "window_open",
        "humidifying_season",
        "refill",
        "cleaning",
        "storage",
        "dehumidifier_tank",
    },
    "number": {"dehumidify_above"},
    "select": {"season_override"},
    "button": {"refilled", "cleaned", "stored", "dehumidifier_emptied"},
}


def test_domain_and_storage_key() -> None:
    assert const.DOMAIN == "better_hygrostat"
    assert const.STORAGE_VERSION == 1


def test_option_keys() -> None:
    assert {
        const.CONF_HUMIDITY_SENSOR,
        const.CONF_TEMPERATURE_SENSOR,
        const.CONF_HUMIDIFIER,
        const.CONF_DEHUMIDIFIER,
        const.CONF_WINDOWS,
        const.CONF_TARGET_LOW,
        const.CONF_TARGET_HIGH,
        const.CONF_HOME_KEEPER,
    } == {
        "humidity_sensor",
        "temperature_sensor",
        "humidifier",
        "dehumidifier",
        "windows",
        "target_low",
        "target_high",
        "home_keeper",
    }


async def test_unique_ids(hass: HomeAssistant, plugs) -> None:
    base_states(hass, 50)
    hass.states.async_set(DEHUM, "off")
    hass.states.async_set("sensor.dehumidifier_power", 0.0, {"unit_of_measurement": "W"})
    entry = await setup_room(
        hass, dehumidifier=DEHUM, dehumidifier_power="sensor.dehumidifier_power"
    )
    found: dict[str, set[str]] = {}
    for item in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        assert item.unique_id.startswith(f"{entry.entry_id}_")
        found.setdefault(item.domain, set()).add(item.unique_id.removeprefix(f"{entry.entry_id}_"))
    for platform, keys in EXPECTED_KEYS.items():
        assert keys <= found.get(platform, set()), platform
    store = entry.runtime_data.controller._store
    assert store.key == f"better_hygrostat.{entry.entry_id}"
