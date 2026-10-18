"""Humidity physics (pure functions, no Home Assistant)."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
import math

# Magnus formula over water (DWD coefficients)
_A = 17.62
_B = 243.12


def saturation_vapor_pressure(temp_c: float) -> float:
    """Return the saturation vapour pressure in hPa."""
    return 6.112 * math.exp(_A * temp_c / (_B + temp_c))


def absolute_humidity(temp_c: float, rel_humidity: float) -> float:
    """Return the absolute humidity in g/m³."""
    vapor = rel_humidity / 100.0 * saturation_vapor_pressure(temp_c)
    return 216.7 * vapor / (273.15 + temp_c)


def dew_point(temp_c: float, rel_humidity: float) -> float:
    """Return the dew point in °C."""
    rh = max(rel_humidity, 0.1)
    gamma = math.log(rh / 100.0) + _A * temp_c / (_B + temp_c)
    return _B * gamma / (_A - gamma)


def equivalent_humidity(outdoor_temp_c: float, outdoor_rh: float, indoor_temp_c: float) -> float:
    """Return the relative humidity outdoor air would have once warmed to room temperature.

    The vapour pressure stays the same when air is warmed; only the saturation vapour
    pressure rises.
    """
    value = (
        outdoor_rh
        * saturation_vapor_pressure(outdoor_temp_c)
        / saturation_vapor_pressure(indoor_temp_c)
    )
    return max(0.0, min(100.0, value))


# Rule of thumb: highest room humidity before it condenses on windows and thermal bridges.
_CONDENSATION_TABLE: list[tuple[float, float]] = [
    (-20.0, 30.0),
    (-10.0, 35.0),
    (-5.0, 40.0),
    (0.0, 45.0),
    (5.0, 50.0),
]


def condensation_limit(outdoor_temp_c: float, offset: float = 0.0) -> float:
    """Return the upper humidify limit for the outdoor temperature."""
    table = _CONDENSATION_TABLE
    if outdoor_temp_c <= table[0][0]:
        value = table[0][1]
    elif outdoor_temp_c >= table[-1][0]:
        value = table[-1][1]
    else:
        value = table[-1][1]
        for (t0, v0), (t1, v1) in pairwise(table):
            if t0 <= outdoor_temp_c <= t1:
                value = v0 + (v1 - v0) * (outdoor_temp_c - t0) / (t1 - t0)
                break
    return value + offset


def slope_per_hour(samples: Sequence[tuple[float, float]]) -> float | None:
    """Return the slope of a linear regression in units per hour.

    samples: (unix timestamp in seconds, value)
    """
    if len(samples) < 3:
        return None
    t0 = samples[0][0]
    xs = [(t - t0) / 3600.0 for t, _ in samples]
    ys = [v for _, v in samples]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return sxy / sxx
