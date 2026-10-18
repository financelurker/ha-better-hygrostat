"""Drive the demo room: humidity follows the humidifier plug, then the tank runs dry.

Phase 1 (25 min): the humidifier raises the humidity while on; it falls while off.
                  The window is open from minute 18 to 20.5.
Phase 2 (until the refill problem shows): the tank is empty, the humidity falls
                  although the plug is on.

Options: --phase1 MIN, --window FROM-TO (minutes, "none" for no window) and --resume
(continue from the current humidity instead of 43.6 %).
"""

import argparse
import asyncio
import json
import time

import aiohttp

BASE = "http://127.0.0.1:8123"
H = {"Authorization": f"Bearer {json.load(open('session.json'))['token']}"}
STEP = 10  # seconds


ARGS = argparse.ArgumentParser()
ARGS.add_argument("--phase1", type=float, default=25)
ARGS.add_argument("--window", default="18-20.5")
ARGS.add_argument("--resume", action="store_true")
OPT = ARGS.parse_args()
WINDOW = None if OPT.window == "none" else tuple(float(x) for x in OPT.window.split("-"))


async def main() -> None:
    async with aiohttp.ClientSession(headers=H) as s:

        async def state(entity_id):
            r = await s.get(f"{BASE}/api/states/{entity_id}")
            return (await r.json())["state"]

        async def action(domain, service, data):
            await s.post(f"{BASE}/api/services/{domain}/{service}", json=data)

        hum = float(await state("input_number.office_humidity")) if OPT.resume else 43.6
        await action(
            "input_number", "set_value", {"entity_id": "input_number.office_humidity", "value": hum}
        )
        start = time.monotonic()
        window = False
        while True:
            minute = (time.monotonic() - start) / 60
            plug_on = await state("switch.humidifier_plug") == "on"
            await action(
                "input_number",
                "set_value",
                {
                    "entity_id": "input_number.humidifier_power_value",
                    "value": 18.6 if plug_on else 0.4,
                },
            )
            want_window = WINDOW is not None and WINDOW[0] <= minute < WINDOW[1]
            if want_window != window:
                window = want_window
                await action(
                    "input_boolean",
                    "turn_on" if window else "turn_off",
                    {"entity_id": "input_boolean.office_window_state"},
                )
            if minute < OPT.phase1:
                if window:
                    hum -= 0.14
                elif plug_on:
                    hum += 0.12
                else:
                    hum -= 0.08
            elif await state("binary_sensor.office_refill_water") != "on":
                hum -= 0.04 if plug_on else 0.06
            else:
                print("refill problem raised after", round(minute, 1), "min")
                return
            await action(
                "input_number",
                "set_value",
                {"entity_id": "input_number.office_humidity", "value": round(hum, 2)},
            )
            await asyncio.sleep(STEP)


asyncio.run(main())
