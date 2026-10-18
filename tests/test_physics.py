from custom_components.better_hygrostat import physics


def test_absolute_humidity():
    # 20 Grad / 50 % ~ 8,6 g/m3
    assert abs(physics.absolute_humidity(20, 50) - 8.63) < 0.05


def test_equivalent_humidity_winter_and_summer():
    assert abs(physics.equivalent_humidity(5, 80, 21) - 28) < 1.5
    assert abs(physics.equivalent_humidity(20, 60, 21) - 56) < 1.5


def test_dew_point():
    assert abs(physics.dew_point(20, 50) - 9.3) < 0.2


def test_condensation_limit():
    assert physics.condensation_limit(10) == 50
    assert physics.condensation_limit(-30) == 30
    assert physics.condensation_limit(-2.5) == 42.5
    assert physics.condensation_limit(0, offset=3) == 48


def test_slope():
    samples = [(i * 600.0, 8.0 - 0.05 * i) for i in range(10)]  # -0,3 pro Stunde
    assert abs(physics.slope_per_hour(samples) + 0.3) < 1e-9
