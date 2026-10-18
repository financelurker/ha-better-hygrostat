"""Shorten the timings of the demo room so the simulation produces a history quickly."""

import asyncio
import json

import aiohttp

BASE = "http://127.0.0.1:8123"
S = json.load(open("session.json"))
H = {"Authorization": f"Bearer {S['token']}"}

CONTROL = {
    "target_low": 45,
    "target_high": 60,
    "dry_tolerance": 1,
    "wet_tolerance": 1.5,
    "min_on": 1,
    "min_off": 1,
    "changeover_lock": 30,
    "sensor_stale": 120,
}
MAINTENANCE = {
    "tank_detection": True,
    "tank_min_runtime": 15,
    "tank_window": 15,
    "tank_slope": -0.15,
    "tank_block": False,
    "cleaning_interval": 250,
    "home_keeper": True,
}


async def main() -> None:
    async with aiohttp.ClientSession(headers=H) as s:
        r = await s.post(
            f"{BASE}/api/config/config_entries/options/flow", json={"handler": S["entry_id"]}
        )
        fid = (await r.json())["flow_id"]
        for step, data in (("control", CONTROL), ("maintenance", MAINTENANCE)):
            await s.post(
                f"{BASE}/api/config/config_entries/options/flow/{fid}", json={"next_step_id": step}
            )
            r = await s.post(f"{BASE}/api/config/config_entries/options/flow/{fid}", json=data)
            print(step, (await r.json()).get("type"))
        r = await s.post(
            f"{BASE}/api/config/config_entries/options/flow/{fid}", json={"next_step_id": "save"}
        )
        print("save", (await r.json()).get("type"))


asyncio.run(main())
