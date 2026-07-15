from __future__ import annotations

from typing import Any

from homeassistant import config_entries

from .const import DOMAIN


class UpdateManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        # Single instance: this integration is a system-wide, local rule
        # engine, not something you'd ever want more than one of.
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="Update Manager", data={})

        return self.async_show_form(step_id="user")

    # No options flow: staging rules now live on the "Instellingen" tab of
    # Update Manager's own panel (panel.py), not in a generic HA options
    # screen -- see FUTURE.md's "Tussenstap" note (2026-07-15) on why that
    # was always meant to be temporary. The underlying data (the config
    # entry's options dict) is unchanged, just written by the panel's
    # update_manager/save_settings websocket command instead.
