"""Translations are complete and have the same keys."""

import json
from pathlib import Path

BASE = Path(__file__).parents[1] / "custom_components" / "better_hygrostat" / "translations"


def _keys(d, prefix=""):
    out = set()
    for k, v in d.items():
        path = f"{prefix}.{k}"
        out.add(path)
        if isinstance(v, dict):
            out |= _keys(v, path)
    return out


def test_de_en_same_keys():
    de = json.loads((BASE / "de.json").read_text(encoding="utf-8"))
    en = json.loads((BASE / "en.json").read_text(encoding="utf-8"))
    assert _keys(de) == _keys(en)


def test_entities_translated():
    from custom_components.better_hygrostat.binary_sensor import BINARY_SENSORS
    from custom_components.better_hygrostat.button import BUTTONS
    from custom_components.better_hygrostat.const import STATUSES
    from custom_components.better_hygrostat.sensor import SENSORS

    de = json.loads((BASE / "de.json").read_text(encoding="utf-8"))["entity"]
    for d in SENSORS:
        assert d.key in de["sensor"]
    for d in BINARY_SENSORS:
        assert d.key in de["binary_sensor"]
    for key, _, _ in BUTTONS:
        assert key in de["button"]
    assert set(de["sensor"]["status"]["state"]) == set(STATUSES)
