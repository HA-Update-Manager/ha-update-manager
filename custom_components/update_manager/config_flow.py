from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_MAJOR_BLOCKED,
    CONF_MAJOR_WAIT_DAYS,
    CONF_MINOR_BLOCKED,
    CONF_MINOR_WAIT_DAYS,
    CONF_PATCH_BLOCKED,
    CONF_PATCH_WAIT_DAYS,
    CONF_PROFILE,
    CONF_UNKNOWN_BLOCKED,
    CONF_UNKNOWN_WAIT_DAYS,
    DOMAIN,
    PROFILE_BALANCED,
    PROFILE_CONSERVATIVE,
    PROFILE_CUSTOM,
    PROFILE_FREE,
    PROFILE_PRESETS,
)

# Labels come from strings.json/translations (selector.profile.options.*)
# via translation_key below, not hardcoded here.
_PROFILE_VALUES = [PROFILE_CONSERVATIVE, PROFILE_BALANCED, PROFILE_FREE, PROFILE_CUSTOM]


def _details_schema(defaults: dict[str, int | bool]) -> vol.Schema:
    # A profile only pre-fills these -- every field stays visible and
    # editable regardless of which profile was picked (see FUTURE.md).
    return vol.Schema(
        {
            vol.Required(
                CONF_PATCH_WAIT_DAYS, default=defaults[CONF_PATCH_WAIT_DAYS]
            ): NumberSelector(NumberSelectorConfig(min=0, max=365, mode=NumberSelectorMode.BOX)),
            vol.Required(CONF_PATCH_BLOCKED, default=defaults[CONF_PATCH_BLOCKED]): BooleanSelector(),
            vol.Required(
                CONF_MINOR_WAIT_DAYS, default=defaults[CONF_MINOR_WAIT_DAYS]
            ): NumberSelector(NumberSelectorConfig(min=0, max=365, mode=NumberSelectorMode.BOX)),
            vol.Required(CONF_MINOR_BLOCKED, default=defaults[CONF_MINOR_BLOCKED]): BooleanSelector(),
            vol.Required(
                CONF_MAJOR_WAIT_DAYS, default=defaults[CONF_MAJOR_WAIT_DAYS]
            ): NumberSelector(NumberSelectorConfig(min=0, max=365, mode=NumberSelectorMode.BOX)),
            vol.Required(CONF_MAJOR_BLOCKED, default=defaults[CONF_MAJOR_BLOCKED]): BooleanSelector(),
            vol.Required(
                CONF_UNKNOWN_WAIT_DAYS, default=defaults[CONF_UNKNOWN_WAIT_DAYS]
            ): NumberSelector(NumberSelectorConfig(min=0, max=365, mode=NumberSelectorMode.BOX)),
            vol.Required(CONF_UNKNOWN_BLOCKED, default=defaults[CONF_UNKNOWN_BLOCKED]): BooleanSelector(),
        }
    )


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

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return UpdateManagerOptionsFlow()


class UpdateManagerOptionsFlow(config_entries.OptionsFlow):
    def __init__(self) -> None:
        self._chosen_profile: str = PROFILE_CUSTOM

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        if user_input is not None:
            self._chosen_profile = user_input[CONF_PROFILE]
            return await self.async_step_details()

        schema = vol.Schema(
            {
                vol.Required(CONF_PROFILE, default=PROFILE_CUSTOM): SelectSelector(
                    SelectSelectorConfig(
                        options=_PROFILE_VALUES, mode=SelectSelectorMode.LIST, translation_key="profile"
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_details(self, user_input: dict[str, Any] | None = None) -> config_entries.FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        if self._chosen_profile == PROFILE_CUSTOM:
            defaults = dict(self.config_entry.options) or PROFILE_PRESETS[PROFILE_BALANCED]
        else:
            defaults = PROFILE_PRESETS[self._chosen_profile]

        return self.async_show_form(step_id="details", data_schema=_details_schema(defaults))
