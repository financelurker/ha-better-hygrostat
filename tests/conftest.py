"""Test fixtures."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant, ServiceCall


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


@pytest.fixture
def plugs(hass: HomeAssistant):
    """Fake plugs: switch.turn_on/off really change the state."""
    calls: list[tuple[str, str]] = []

    async def _handle(call: ServiceCall) -> None:
        ids = call.data["entity_id"]
        ids = [ids] if isinstance(ids, str) else ids
        for entity_id in ids:
            calls.append((call.service, entity_id))
            hass.states.async_set(entity_id, "on" if call.service == "turn_on" else "off")

    hass.services.async_register("switch", "turn_on", _handle)
    hass.services.async_register("switch", "turn_off", _handle)
    return calls
