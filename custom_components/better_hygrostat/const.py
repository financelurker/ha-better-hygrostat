"""Constants for Better Hygrostat."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "better_hygrostat"
NAME = "Better Hygrostat"

PLATFORMS: list[Platform] = [
    Platform.HUMIDIFIER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]

STORAGE_VERSION = 1
TICK_SECONDS = 30

# --- config: room ------------------------------------------------------------
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_TEMPERATURE_SENSOR = "temperature_sensor"

# --- config: devices ---------------------------------------------------------
CONF_HUMIDIFIER = "humidifier"
CONF_HUMIDIFIER_POWER = "humidifier_power"
CONF_HUMIDIFIER_POWER_MIN = "humidifier_power_min"
CONF_DEHUMIDIFIER = "dehumidifier"
CONF_DEHUMIDIFIER_POWER = "dehumidifier_power"
CONF_DEHUMIDIFIER_POWER_MIN = "dehumidifier_power_min"
CONF_DEHUMIDIFIER_TANK_SENSOR = "dehumidifier_tank_sensor"

# --- config: windows and doors -----------------------------------------------
CONF_WINDOWS = "windows"
CONF_WINDOW_OPEN_DELAY = "window_open_delay"  # seconds
CONF_WINDOW_CLOSE_DELAY = "window_close_delay"  # seconds

# --- config: outdoor ---------------------------------------------------------
CONF_OUTDOOR_TEMPERATURE = "outdoor_temperature"
CONF_OUTDOOR_HUMIDITY = "outdoor_humidity"
CONF_WEATHER = "weather"

# --- config: control ---------------------------------------------------------
CONF_TARGET_LOW = "target_low"  # humidify target
CONF_TARGET_HIGH = "target_high"  # dehumidify above
CONF_DRY_TOLERANCE = "dry_tolerance"
CONF_WET_TOLERANCE = "wet_tolerance"
CONF_MIN_ON = "min_on"  # minutes
CONF_MIN_OFF = "min_off"  # minutes
CONF_CHANGEOVER_LOCK = "changeover_lock"  # minutes
CONF_SENSOR_STALE = "sensor_stale"  # minutes, 0 = off

# --- config: season ----------------------------------------------------------
CONF_SEASON_METHOD = "season_method"
CONF_HEATING_LIMIT = "heating_limit"  # °C
CONF_SEASON_BAND = "season_band"  # percentage points of hysteresis
CONF_CONDENSATION_LIMIT = "condensation_limit"
CONF_CONDENSATION_OFFSET = "condensation_offset"

# --- config: maintenance -----------------------------------------------------
CONF_TANK_DETECTION = "tank_detection"
CONF_TANK_MIN_RUNTIME = "tank_min_runtime"  # minutes
CONF_TANK_WINDOW = "tank_window"  # minutes
CONF_TANK_SLOPE = "tank_slope"  # g/m³ per hour (negative = falling)
CONF_TANK_BLOCK = "tank_block"
CONF_CLEANING_INTERVAL = "cleaning_interval"  # runtime hours, 0 = off
CONF_HOME_KEEPER = "home_keeper"

SEASON_AUTO = "auto"
SEASON_EQUIVALENT = "equivalent_humidity"
SEASON_HEATING_LIMIT = "heating_limit"
SEASON_ALWAYS = "always"
SEASON_METHODS = [SEASON_AUTO, SEASON_EQUIVALENT, SEASON_HEATING_LIMIT, SEASON_ALWAYS]

DEFAULTS: dict = {
    CONF_HUMIDIFIER_POWER_MIN: 2.0,
    CONF_DEHUMIDIFIER_POWER_MIN: 5.0,
    CONF_WINDOWS: [],
    CONF_WINDOW_OPEN_DELAY: 45,
    CONF_WINDOW_CLOSE_DELAY: 600,
    CONF_TARGET_LOW: 45,
    CONF_TARGET_HIGH: 60,
    CONF_DRY_TOLERANCE: 2.0,
    CONF_WET_TOLERANCE: 2.0,
    CONF_MIN_ON: 10,
    CONF_MIN_OFF: 10,
    CONF_CHANGEOVER_LOCK: 30,
    CONF_SENSOR_STALE: 120,
    CONF_SEASON_METHOD: SEASON_AUTO,
    CONF_HEATING_LIMIT: 14.0,
    CONF_SEASON_BAND: 5.0,
    CONF_CONDENSATION_LIMIT: True,
    CONF_CONDENSATION_OFFSET: 0.0,
    CONF_TANK_DETECTION: True,
    CONF_TANK_MIN_RUNTIME: 60,
    CONF_TANK_WINDOW: 90,
    CONF_TANK_SLOPE: -0.15,
    CONF_TANK_BLOCK: False,
    CONF_CLEANING_INTERVAL: 250,
    CONF_HOME_KEEPER: True,
}

# modes of the hygrostat entity (only with a dehumidifier)
MODE_AUTO = "auto"
MODE_HUMIDIFY = "humidify"
MODE_DEHUMIDIFY = "dehumidify"
MODES = [MODE_AUTO, MODE_HUMIDIFY, MODE_DEHUMIDIFY]

# season override (select)
OVERRIDE_AUTO = "auto"
OVERRIDE_ON = "on"
OVERRIDE_OFF = "off"
OVERRIDES = [OVERRIDE_AUTO, OVERRIDE_ON, OVERRIDE_OFF]

# status (enum sensor)
STATUS_OFF = "off"
STATUS_IDLE = "idle"
STATUS_HUMIDIFYING = "humidifying"
STATUS_DEHUMIDIFYING = "dehumidifying"
STATUS_WINDOW_OPEN = "window_open"
STATUS_WINDOW_UNKNOWN = "window_unknown"
STATUS_SENSOR_ERROR = "sensor_error"
STATUS_SEASON_INACTIVE = "season_inactive"
STATUS_TANK_EMPTY = "tank_empty"
STATUSES = [
    STATUS_OFF,
    STATUS_IDLE,
    STATUS_HUMIDIFYING,
    STATUS_DEHUMIDIFYING,
    STATUS_WINDOW_OPEN,
    STATUS_WINDOW_UNKNOWN,
    STATUS_SENSOR_ERROR,
    STATUS_SEASON_INACTIVE,
    STATUS_TANK_EMPTY,
]

# maintenance/problem cases ("issues") -> problem binary sensors + Home Keeper tasks
ISSUE_REFILL = "refill"
ISSUE_CLEANING = "cleaning"
ISSUE_STORAGE = "storage"
ISSUE_HUM_FAULT = "humidifier_fault"
ISSUE_DEHUM_TANK = "dehumidifier_tank"
ISSUE_DEHUM_FAULT = "dehumidifier_fault"
ISSUES = [
    ISSUE_REFILL,
    ISSUE_CLEANING,
    ISSUE_STORAGE,
    ISSUE_HUM_FAULT,
    ISSUE_DEHUM_TANK,
    ISSUE_DEHUM_FAULT,
]

# origin of a resolution
ORIGIN_USER = "user"
ORIGIN_AUTO = "auto"
ORIGIN_HOME_KEEPER = "home_keeper"

# power metering: how long a switched-on device may draw nothing
POWER_GRACE_SECONDS = 180

# After a Home Assistant start nothing is switched on for this long (switching off is
# not delayed), so sensors that come up late cannot trigger a short run.
STARTUP_HOLD_SECONDS = 30

# A window/door contact that is unavailable or unknown blocks switching on; after this
# long it is ignored (with a warning), so a dead contact does not block for good.
CONTACT_UNAVAILABLE_IGNORE_SECONDS = 30 * 60
