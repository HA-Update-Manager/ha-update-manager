"""Purpose-specific automation triggers for Update Manager's own events
(const.py's own EVENT_ANNOUNCED/EVENT_INSTALLED/EVENT_INSTALL_FAILED), on
top of the plain events themselves (unchanged, no migration needed):
HA's own entity-target picker (triggers.yaml) is a nicer, discoverable way
to react to one specific update than configuring a generic Event trigger
by hand with the raw event_type string and matching event_data.entity_id
yourself. Inspired by Battery Notes 3.8.0 (github.com/andrew-codechimp/
HA-Battery-Notes/releases/tag/3.8.0), which replicated its own existing
events the same way.

Uses homeassistant.helpers.trigger.Trigger, the current, forward-looking
trigger API (confirmed present on the stable 2026.10.0 tag, not dev/next-
only): device automations, the older mechanism, no longer accept new
implementations. That page's own docs describe this API as "young and
still changes often", so this stays deliberately minimal: only
target.entity_id is honored for filtering (triggers.yaml's own target
restricts the UI picker to update-domain entities directly, never
device_id/area_id, so this isn't reachable from the panel; a hand-written
automation that adds device_id/area_id to the target via raw YAML simply
isn't filtered by those, a known, accepted simplification, not a silent
wrong-match)."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast, override

import voluptuous as vol

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.trigger import Trigger, TriggerActionRunner, TriggerConfig
from homeassistant.helpers.typing import ConfigType

from .const import EVENT_ANNOUNCED, EVENT_INSTALLED, EVENT_INSTALL_FAILED

# No extra options of our own (beyond the target every trigger already
# gets for free, see TriggerConfig), but async_validate_config still needs
# a schema to run the incoming (already target/options-split) config
# through, an empty one, same as Battery Notes' own BATTERY_NOTES_TRIGGER_SCHEMA
# for its own no-extra-options triggers.
_TRIGGER_SCHEMA = vol.Schema({})


class _UpdateManagerEventTrigger(Trigger):
    """Base for a trigger that fires on one of our own three events,
    optionally narrowed to specific entities via the trigger's target
    (triggers.yaml's own `target: entity: domain: update`)."""

    _event_type: str

    @classmethod
    @override
    async def async_validate_config(cls, hass: HomeAssistant, config: ConfigType) -> ConfigType:
        return cast(ConfigType, _TRIGGER_SCHEMA(config))

    def __init__(self, hass: HomeAssistant, config: TriggerConfig) -> None:
        super().__init__(hass, config)
        # None (not an empty list) means "no target set at all": match
        # every entity, same as leaving a service call's own target empty
        # means "all". An explicit, empty list is never possible here:
        # the entity picker always resolves to at least one id once
        # anything is actually selected.
        self._entity_ids = (config.target or {}).get("entity_id")

    @override
    async def async_attach_runner(
        self,
        run_action: TriggerActionRunner,
        _did_not_trigger: Callable[..., None] | None = None,
    ) -> CALLBACK_TYPE:
        @callback
        def async_handle_event(event: Event) -> None:
            if self._entity_ids is not None and event.data.get("entity_id") not in self._entity_ids:
                return
            run_action(dict(event.data), self._event_type, event.context)

        return self._hass.bus.async_listen(self._event_type, async_handle_event)


class ScheduledAutoInstallTrigger(_UpdateManagerEventTrigger):
    """Fires when an update is announced for a scheduled auto-install
    (EVENT_ANNOUNCED): the countdown starting, not the install itself."""

    _event_type = EVENT_ANNOUNCED


class InstalledTrigger(_UpdateManagerEventTrigger):
    """Fires once an update actually finishes installing (EVENT_INSTALLED),
    auto or manual alike, same "one unified place an install is
    confirmed done" an automation would otherwise have to derive itself
    from a plain update.* state change."""

    _event_type = EVENT_INSTALLED


class InstallFailedTrigger(_UpdateManagerEventTrigger):
    """Fires when an install attempt fails (EVENT_INSTALL_FAILED)."""

    _event_type = EVENT_INSTALL_FAILED


async def async_get_triggers(hass: HomeAssistant) -> dict[str, type[Trigger]]:  # noqa: ARG001
    return {
        "scheduled_auto_install": ScheduledAutoInstallTrigger,
        "installed": InstalledTrigger,
        "install_failed": InstallFailedTrigger,
    }
