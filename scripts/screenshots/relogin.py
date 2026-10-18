"""Log in to the demo instance again and store a long-lived token in session.json."""

import asyncio
import json

import aiohttp

BASE = "http://127.0.0.1:8123"
CLIENT = BASE + "/"


async def main() -> None:
    async with aiohttp.ClientSession() as s:
        r = await s.post(
            f"{BASE}/auth/login_flow",
            json={"client_id": CLIENT, "handler": ["homeassistant", None], "redirect_uri": CLIENT},
        )
        fid = (await r.json())["flow_id"]
        r = await s.post(
            f"{BASE}/auth/login_flow/{fid}",
            json={"username": "demo", "password": "demo-pass-2026", "client_id": CLIENT},
        )
        code = (await r.json())["result"]
        r = await s.post(
            f"{BASE}/auth/token",
            data={"grant_type": "authorization_code", "code": code, "client_id": CLIENT},
        )
        token = (await r.json())["access_token"]
        ws = await s.ws_connect(f"{BASE}/api/websocket")
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": token})
        await ws.receive_json()
        await ws.send_json(
            {
                "id": 1,
                "type": "auth/long_lived_access_token",
                "client_name": "screenshots",
                "lifespan": 30,
            }
        )
        long_lived = (await ws.receive_json())["result"]
    with open("session.json") as f:
        session = json.load(f)
    session["token"] = long_lived
    with open("session.json", "w") as f:
        json.dump(session, f)
    print("token refreshed")


asyncio.run(main())
