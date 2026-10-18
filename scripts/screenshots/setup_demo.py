"""Onboard a fresh HA and set up Home Keeper and a Better Hygrostat room via the real flows."""

import asyncio
import json
import sys

import aiohttp

BASE = "http://127.0.0.1:8123"
CLIENT = BASE + "/"
USER, PASSWORD = "demo", "demo-pass-2026"


async def main() -> None:
    async with aiohttp.ClientSession() as s:
        r = await s.post(
            f"{BASE}/api/onboarding/users",
            json={
                "client_id": CLIENT,
                "name": "Demo",
                "username": USER,
                "password": PASSWORD,
                "language": "en",
            },
        )
        code = (await r.json())["auth_code"]
        r = await s.post(
            f"{BASE}/auth/token",
            data={"grant_type": "authorization_code", "code": code, "client_id": CLIENT},
        )
        token = (await r.json())["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        for step, body in (
            ("core_config", {}),
            ("analytics", {}),
            ("integration", {"client_id": CLIENT, "redirect_uri": CLIENT}),
        ):
            r = await s.post(f"{BASE}/api/onboarding/{step}", json=body, headers=h)
            print(step, r.status)

        ws = await s.ws_connect(f"{BASE}/api/websocket")
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        await ws.receive_json()
        n = 0

        async def call(msg):
            nonlocal n
            n += 1
            await ws.send_json({"id": n, **msg})
            while True:
                res = await ws.receive_json()
                if res.get("id") == n and res.get("type") == "result":
                    if not res["success"]:
                        print("WS error", msg, res, file=sys.stderr)
                    return res.get("result")

        area = await call(
            {"type": "config/area_registry/create", "name": "Office", "icon": "mdi:desk"}
        )
        area_id = area["area_id"]
        for ent in (
            "sensor.office_humidity",
            "sensor.office_temperature",
            "switch.humidifier_plug",
            "sensor.humidifier_power",
            "binary_sensor.office_window",
        ):
            await call(
                {"type": "config/entity_registry/update", "entity_id": ent, "area_id": area_id}
            )

        async def flow(path, flow_id, data):
            r = await s.post(f"{BASE}/api/config/{path}/flow/{flow_id}", json=data, headers=h)
            res = await r.json()
            print(res.get("step_id") or res.get("type"), res.get("errors"))
            return res

        # Home Keeper (optional companion)
        r = await s.post(
            f"{BASE}/api/config/config_entries/flow", json={"handler": "home_keeper"}, headers=h
        )
        res = await r.json()
        while res.get("type") == "form":
            res = await flow("config_entries", res["flow_id"], {})
        print("home_keeper", res.get("type"))

        # Better Hygrostat room, step by step
        r = await s.post(
            f"{BASE}/api/config/config_entries/flow",
            json={"handler": "better_hygrostat"},
            headers=h,
        )
        fid = (await r.json())["flow_id"]
        await flow(
            "config_entries",
            fid,
            {
                "name": "Office",
                "humidity_sensor": "sensor.office_humidity",
                "temperature_sensor": "sensor.office_temperature",
                "humidifier": "switch.humidifier_plug",
                "humidifier_power": "sensor.humidifier_power",
                "humidifier_power_min": 2,
            },
        )
        await flow("config_entries", fid, {})  # no dehumidifier
        await flow(
            "config_entries",
            fid,
            {
                "windows": ["binary_sensor.office_window"],
                "window_open_delay": 45,
                "window_close_delay": 600,
            },
        )
        res = await flow(
            "config_entries",
            fid,
            {
                "outdoor_temperature": "sensor.outdoor_temperature",
                "outdoor_humidity": "sensor.outdoor_humidity",
            },
        )
        entry_id = res.get("result", {}).get("entry_id")
        print("entry", entry_id)

        devices = await call({"type": "config/device_registry/list"})
        dev = [d for d in devices if any(i[0] == "better_hygrostat" for i in d["identifiers"])]
        if dev:
            await call(
                {
                    "type": "config/device_registry/update",
                    "device_id": dev[0]["id"],
                    "area_id": area_id,
                }
            )
        json.dump(
            {"token": token, "device_id": dev[0]["id"] if dev else None, "entry_id": entry_id},
            open("session.json", "w"),
        )
        print("device", dev[0]["id"] if dev else None)


asyncio.run(main())
