"""Fix flow for rollout_manager.py's own "install_stuck"/"install_stuck_zigbee"
Repair issues (see that module's own _async_maybe_raise_stuck_issue) -- a
single, generic confirm flow, since there's only ever one real action: tell
our own queue to stop waiting on the entity, never touch the install itself,
which may still genuinely finish on its own."""
from __future__ import annotations

from typing import Any

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant

from .rollout_manager import STUCK_ISSUE_ID_PREFIX
from .runtime_data import get_data


class _StopWaitingRepairFlow(ConfirmRepairFlow):
    def __init__(self, hass: HomeAssistant, entity_id: str) -> None:
        super().__init__()
        self._hass = hass
        self._entity_id = entity_id

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> Any:
        if user_input is not None:
            data = get_data(self._hass)
            if data is not None:
                await data.rollout_manager.async_stop_waiting_for(self._entity_id)
        return await super().async_step_confirm(user_input)


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """entity_id comes from the issue's own stored `data` (set when the
    issue was raised) when available, falling back to parsing it back out
    of issue_id itself (f"install_stuck_{entity_id}", see
    _async_maybe_raise_stuck_issue) -- entity_id never legitimately
    contains that literal prefix, so this is safe either way."""
    entity_id = (data or {}).get("entity_id") or issue_id.removeprefix(STUCK_ISSUE_ID_PREFIX)
    return _StopWaitingRepairFlow(hass, entity_id)
