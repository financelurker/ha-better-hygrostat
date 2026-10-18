"""Save the demo dashboard (sections view for the Office room)."""

import asyncio
import json

import aiohttp

TOKEN = json.load(open("session.json"))["token"]


def tile(entity, name=None, cols=6, **kw):
    card = {"type": "tile", "entity": entity, "grid_options": {"columns": cols}, **kw}
    if name:
        card["name"] = name
    return card


CONFIG = {
    "title": "Home",
    "views": [
        {
            "title": "Office",
            "path": "office",
            "type": "sections",
            "max_columns": 3,
            "sections": [
                {
                    "type": "grid",
                    "cards": [
                        {"type": "heading", "heading": "Office", "icon": "mdi:desk"},
                        {
                            "type": "humidifier",
                            "entity": "humidifier.office",
                            "name": "Office",
                            "grid_options": {"columns": 12},
                        },
                        tile("sensor.office_status", "Status", 12),
                    ],
                },
                {
                    "type": "grid",
                    "cards": [
                        {"type": "heading", "heading": "Climate", "icon": "mdi:water-percent"},
                        tile("sensor.office_absolute_humidity", "Abs. humidity"),
                        tile("sensor.office_dew_point", "Dew point"),
                        tile("sensor.office_effective_humidify_target", "Effective target"),
                        tile("sensor.office_outdoor_air_at_room_temperature", "Outdoor, warmed"),
                        tile("binary_sensor.office_humidifying_season", "Season"),
                        tile("binary_sensor.office_window_open", "Window"),
                        {
                            "type": "history-graph",
                            "entities": [{"entity": "humidifier.office", "name": "Office"}],
                            "hours_to_show": 1,
                            "fit_y_data": True,
                            "grid_options": {"columns": 12},
                        },
                    ],
                },
                {
                    "type": "grid",
                    "cards": [
                        {"type": "heading", "heading": "Maintenance", "icon": "mdi:wrench"},
                        tile("binary_sensor.office_refill_water", "Refill water"),
                        tile("binary_sensor.office_cleaning_due", "Cleaning"),
                        tile("sensor.office_runtime_since_refill", "Since refill"),
                        tile("sensor.office_runtime_since_cleaning", "Since cleaning"),
                        tile("binary_sensor.office_humidifier_not_responding", "Power check"),
                        tile("switch.humidifier_plug", "Plug"),
                        tile("button.office_refilled", "Refilled", hide_state=True),
                        tile("button.office_cleaned", "Cleaned", hide_state=True),
                    ],
                },
            ],
        }
    ],
}


async def main() -> None:
    async with aiohttp.ClientSession() as s:
        ws = await s.ws_connect("http://127.0.0.1:8123/api/websocket")
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": TOKEN})
        await ws.receive_json()
        # A dashboard of its own: the default dashboard is the auto-generated overview.
        await ws.send_json(
            {
                "id": 1,
                "type": "lovelace/dashboards/create",  # fails harmlessly if it exists
                "url_path": "office-demo",
                "title": "Office",
                "icon": "mdi:desk",
                "mode": "storage",
                "show_in_sidebar": True,
                "require_admin": False,
            }
        )
        print(await ws.receive_json())
        await ws.send_json(
            {"id": 2, "type": "lovelace/config/save", "url_path": "office-demo", "config": CONFIG}
        )
        print(await ws.receive_json())


asyncio.run(main())
