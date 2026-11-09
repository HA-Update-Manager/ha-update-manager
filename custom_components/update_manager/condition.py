"""Purpose-specific automation conditions for Update Manager (conditions.yaml),
companion to trigger.py's own purpose-specific triggers: a plain `state`/
`template` condition can already ask "is this update ready", but "is this
update currently held back by the community" or "is this update's
auto-install currently postponed for a newer HA Core version" would
otherwise require hand-rolling a template against this integration's own
internal state, exactly the kind of thing a native condition exists to
avoid.

Uses homeassistant.helpers.condition.Condition, the current, forward-
looking class-based condition API (confirmed present on the stable
2026.10.0 tag, not dev/next-only, same verification trigger.py's own
docstring already did for its own Trigger API) -- the older function-
based `*_from_config` pattern still works but isn't the one to build
against going forward.
"""

from __future__ import annotations

from typing import Unpack, cast, override

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.condition import Condition, ConditionCheckParams, ConditionConfig
from homeassistant.helpers.typing import ConfigType

from .runtime_data import get_data as _get_data

# No extra options of our own (beyond the target every condition already
# gets for free, see ConditionConfig), same reasoning as trigger.py's own
# _TRIGGER_SCHEMA.
_CONDITION_SCHEMA = vol.Schema({})


class _UpdateManagerEntityCondition(Condition):
    """Base for a condition that checks one of our own per-entity facts
    right now, for every entity in the condition's own target
    (conditions.yaml's own `target: entity: domain: update`, same picker
    trigger.py's triggers already use). Requires *every* targeted entity
    to satisfy the check -- the same "AND across multiple targets"
    convention HA's own built-in state condition uses, not "any", so
    adding a second entity to the target only ever narrows the
    condition, never widens it.

    Unlike a trigger's own target (where no selection at all means "match
    everything", see trigger.py's own _UpdateManagerEventTrigger), a
    condition has nothing to check at all without a target -- an empty
    selection here means the condition can never pass, not "pass for
    everything"."""

    @classmethod
    @override
    async def async_validate_config(cls, hass: HomeAssistant, config: ConfigType) -> ConfigType:
        return cast(ConfigType, _CONDITION_SCHEMA(config))

    def __init__(self, hass: HomeAssistant, config: ConditionConfig) -> None:
        super().__init__(hass, config)
        self._entity_ids: list[str] = (config.target or {}).get("entity_id") or []

    def _check_one(self, entity_id: str) -> bool:
        raise NotImplementedError

    @override
    def _async_check(self, **_kwargs: Unpack[ConditionCheckParams]) -> bool:  # type: ignore[misc]
        # Unpack[] requires its argument to literally be a TypedDict;
        # homeassistant not being locally installed (see mypy.ini's own
        # comment) means ConditionCheckParams resolves to Any instead here,
        # a local-environment-only gap, not a real typing problem against
        # HA itself.
        return bool(self._entity_ids) and all(self._check_one(entity_id) for entity_id in self._entity_ids)


class HeldBackByCommunityCondition(_UpdateManagerEntityCondition):
    """True when every targeted update entity is currently held back by a
    problematic community verdict -- coordinator.py's own
    held_back_by_community cache field, the same single source of truth
    the panel itself reads (see announcer.py's own
    community_blocks_auto_install for the actual precedence)."""

    @override
    def _check_one(self, entity_id: str) -> bool:
        data = _get_data(self._hass)
        if data is None:
            return False
        cached = data.coordinator.cache.get(entity_id)
        return bool(cached and cached.get("held_back_by_community"))


class PostponedCondition(_UpdateManagerEntityCondition):
    """True when every targeted update entity's own pending auto-install
    is currently postponed for needing a newer HA Core version
    (install_manager.py's own postponed_for, see its own docstring)."""

    @override
    def _check_one(self, entity_id: str) -> bool:
        data = _get_data(self._hass)
        if data is None:
            return False
        return data.install_manager.postponed_for(entity_id) is not None


async def async_get_conditions(hass: HomeAssistant) -> dict[str, type[Condition]]:  # noqa: ARG001
    return {
        "held_back_by_community": HeldBackByCommunityCondition,
        "postponed": PostponedCondition,
    }
