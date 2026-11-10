"""HA-dependent counterpart to hacs_identity.py's pure resolve_identity: looks
up an update entity's device_registry/entity_registry entries and turns
them into the is_hacs_entity/device_manufacturer/device_model/app_slug/
blueprint_source_url arguments resolve_identity expects, for everything
that needs a real hass (confirming an entity is actually HACS-owned, the
devices/apps categories, and reading a Spook blueprint's own source_url
off disk for the blueprint category). Kept out of hacs_identity.py itself
so that module stays free of any homeassistant import (see its own
docstring).

Verified against home-assistant/core's stable release tag 2026.7.3 (not
dev), homeassistant/components/hassio/entity.py: HassioAddonEntity sets
DeviceInfo(identifiers={(DOMAIN, addon.addon.slug)}) with hassio's own
DOMAIN ("hassio"), directly embedding the add-on slug in the device
registry. The same DOMAIN is also used, with fixed literal values (not real
slugs), by Core/Supervisor/OS/host/mount's own hassio-side devices
(HassioCoreEntity et al, same file) -- those three update entities are
already claimed by hacs_identity.py's fixed entity_id map before this
module is ever consulted, but _NOT_A_REAL_ADDON_SLUG guards against it
defensively anyway, in case that map ever misses a case.

"hassio" is hardcoded here rather than imported from
homeassistant.components.hassio.const: that component isn't installed at
all on a Core-only (non-Supervisor) install, so importing it would break
this module there. Same reasoning zigbee.py already uses for hardcoding
"zha" instead of importing homeassistant.components.zha.
"""
from __future__ import annotations

from typing import NamedTuple
from urllib.parse import quote

from homeassistant.components.automation import automations_with_blueprint
from homeassistant.components.blueprint import DOMAIN as _BLUEPRINT_DOMAIN
from homeassistant.components.script import scripts_with_blueprint
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .hacs_identity import ResolvedIdentity, resolve_identity
from .zigbee import device_for_entity, zigbee_network_id

_HASSIO_DOMAIN = "hassio"

# HACS's own integration domain (verified against hacs/integration's real
# source, custom_components/hacs/const.py: DOMAIN = "hacs"). Hardcoded
# rather than imported: HACS isn't a dependency of this integration and
# isn't guaranteed to be installed at all, same reasoning as "hassio"/"zha"
# being hardcoded elsewhere in this module/zigbee.py.
#
# HA 2026.11 replaces HACS with a core "marketplace" integration; existing
# HACS-installed update entities keep their entity_id but their
# entity_registry entry's platform changes from "hacs" to "marketplace".
# Both domains are checked so this keeps working across that migration
# instead of silently losing every HACS-identified entity the moment a
# user updates past 2026.11.
_HACS_DOMAIN = "hacs"
_MARKETPLACE_DOMAIN = "marketplace"


def is_hacs_entity(hass: HomeAssistant, entity_id: str) -> bool:
    """Whether entity_id's owning integration is HACS itself (or, since HA
    2026.11, its successor integration, Marketplace, see _MARKETPLACE_DOMAIN
    above). Found live, 2026-07-22 (real bug hit on an ESPHome device's
    update entity, wrongly identified as HACS): a plausible-looking
    https://github.com/... in release_url is not enough on its own, plenty
    of built-in integrations (ESPHome, for one) set a perfectly real GitHub
    release_url pointing at their own upstream project, nothing to do with
    HACS at all. Verified against hacs/integration's own source
    (custom_components/hacs/update.py): every genuinely HACS-installed
    repo's update entity is created by HacsRepositoryUpdateEntity, which
    belongs to HACS's own integration domain, including repos with no
    backend Python component of their own at all (e.g. a pure Lovelace
    card), so this is the one check that covers all of them, not just
    some."""
    entry = er.async_get(hass).async_get(entity_id)
    return entry is not None and entry.platform in (_HACS_DOMAIN, _MARKETPLACE_DOMAIN)


# Spook's own integration domain (verified against frenck/spook's real
# source, custom_components/spook/const.py: DOMAIN = "spook"). Hardcoded,
# same reasoning as _HACS_DOMAIN/_HASSIO_DOMAIN above: Spook isn't a
# dependency of this integration and isn't guaranteed to be installed.
_SPOOK_DOMAIN = "spook"

# Spook's own unique_id prefixes for its blueprint-update entities
# (custom_components/spook/ectoplasms/blueprint/update.py's own
# _unique_id(): f"blueprint_{blueprint_domain}_{blueprint_path}", only ever
# "automation" or "script" for blueprint_domain). entry.platform alone
# isn't enough to tell this apart from any of Spook's own other update
# entities (its own integration self-update, for one). This prefix is
# what's actually specific to the blueprint feature.
_SPOOK_BLUEPRINT_UNIQUE_ID_PREFIXES = {
    "automation": "blueprint_automation_",
    "script": "blueprint_script_",
}

# Both dashboards share one query-param module between them (confirmed
# against home-assistant/frontend's real source, stable tag 20261028.5:
# src/common/url/automations-query-params.ts and scripts-query-params.ts
# are identical in shape, both reading/writing a "blueprint" key the same
# way), so the same ?blueprint=<path> filtering this module's own
# blueprint_path already matches works for either domain, just under a
# different dashboard path.
_SPOOK_BLUEPRINT_DASHBOARD_PATH = {
    "automation": "/config/automation/dashboard",
    "script": "/config/script/dashboard",
}

# automations_with_blueprint/scripts_with_blueprint (verified against
# home-assistant/core's real source, stable tag 2026.10.0): plain,
# synchronous @callback helpers, each returning the entity_ids of every
# automation/script currently using a given blueprint path, exactly the
# same fact the dashboard's own ?blueprint= filter (see
# _SPOOK_BLUEPRINT_DASHBOARD_PATH above) shows as a list, just as a count
# here. No extra I/O: both just walk that domain's already-loaded
# entities in memory.
_SPOOK_BLUEPRINT_COUNTERS = {
    "automation": automations_with_blueprint,
    "script": scripts_with_blueprint,
}


class SpookBlueprintInfo(NamedTuple):
    source_url: str | None
    list_url: str | None
    # Not named count: tuple's own built-in .count(value) method already
    # claims that name, which mypy correctly flags as a real type
    # conflict (a NamedTuple field named count would need to be the
    # method's own Callable type, not a plain int).
    usage_count: int
    # "automation" or "script": the panel needs this to label its own
    # menu item correctly (Automations vs Scripts), not just to build
    # list_url/usage_count above.
    blueprint_domain: str


async def async_spook_blueprint_info(hass: HomeAssistant, entity_id: str) -> SpookBlueprintInfo | None:
    """What Spook's own blueprint-update feature (see
    https://spook.boo/blueprint/) knows about entity_id, or None if it
    isn't one of Spook's own blueprint-update entities at all.

    source_url: the blueprint's real source address. Spook deliberately
    never puts this in the entity's own state (its own release_url stays
    empty, confirmed live 2026-11-08). This re-derives it the same way
    Spook's own update entity itself does, straight from the blueprint
    file on disk, via the automation/script component's own already-loaded
    DomainBlueprints instance (not a second, hand-rolled YAML parser here:
    that would also need to handle blueprints' own `!input` tag, which
    this gets for free this way).

    list_url: the automations/scripts dashboard, pre-filtered to whatever
    currently uses this exact blueprint (automations_with_blueprint/
    scripts_with_blueprint's own frontend counterpart). Needs nothing
    beyond blueprint_path itself, already known before source_url's own
    file read even starts, so this is set even if that read fails.

    usage_count: len() of that same automations_with_blueprint/
    scripts_with_blueprint call, not a second, separate lookup."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.platform != _SPOOK_DOMAIN or entry.unique_id is None:
        return None
    blueprint_path = None
    blueprint_domain = None
    for candidate_domain, prefix in _SPOOK_BLUEPRINT_UNIQUE_ID_PREFIXES.items():
        if entry.unique_id.startswith(prefix):
            blueprint_domain = candidate_domain
            blueprint_path = entry.unique_id[len(prefix) :]
            break
    if blueprint_path is None:
        return None
    # Always set together, in the same loop iteration above, just not
    # something mypy's own flow analysis follows from one loop back out
    # to here.
    assert blueprint_domain is not None
    list_url = f"{_SPOOK_BLUEPRINT_DASHBOARD_PATH[blueprint_domain]}?blueprint={quote(blueprint_path)}"
    usage_count = len(_SPOOK_BLUEPRINT_COUNTERS[blueprint_domain](hass, blueprint_path))
    source_url = None
    domain_blueprints = hass.data.get(_BLUEPRINT_DOMAIN, {}).get(blueprint_domain)
    if domain_blueprints is not None:
        try:
            blueprint = await domain_blueprints.async_get_blueprint(blueprint_path)
        except Exception:  # noqa: BLE001 - best-effort UI hint, never worth failing the dialog over
            blueprint = None
        if blueprint is not None:
            candidate = blueprint.metadata.get("source_url")
            source_url = candidate if isinstance(candidate, str) else None
    return SpookBlueprintInfo(
        source_url=source_url, list_url=list_url, usage_count=usage_count, blueprint_domain=blueprint_domain
    )


# Real, literal identifier values hassio's own entity.py uses for its
# non-add-on devices (Core/Supervisor/OS/host/mount), never a real add-on
# slug. See this module's own docstring. Verified against hassio's own
# update.py (2026.7.3): it only ever creates update entities for
# core/supervisor/os/add-ons, so these are the only non-slug values that
# could ever reach an update entity's device at all; host/mount_* are kept
# as a defensive, currently-unreachable extra guard anyway, cheap insurance
# against a future hassio update entity for one of those.
_NOT_A_REAL_ADDON_SLUG = {"core", "supervisor", "OS", "host"}


def resolve_device_manufacturer_model(hass: HomeAssistant, device: dr.DeviceEntry) -> tuple[str, str] | None:
    """(manufacturer, model) if this device is genuine, vendor-issued
    firmware -- currently only real Zigbee device firmware (ZHA or
    Zigbee2MQTT, via zigbee.py's own already-verified detection), the same
    firmware regardless of which of those two manages the device. None for
    anything else, including self-compiled/user-flashed firmware
    (ESPHome, Tasmota): those aren't comparable across installs by
    manufacturer/model alone, so they're deliberately never identified here
    (approved scope decision, 2026-07-22). Z-Wave and other device
    ecosystems aren't covered yet either, not verified this session, a
    later, separate extension rather than a guess."""
    if zigbee_network_id(hass, device) is None:
        return None
    if not device.manufacturer or not device.model:
        return None
    return device.manufacturer, device.model


def resolve_app_slug(device: dr.DeviceEntry) -> str | None:
    """The Supervisor add-on slug backing this device, or None if it isn't a
    Supervisor add-on device at all (or is one of hassio's own non-add-on
    devices, see _NOT_A_REAL_ADDON_SLUG)."""
    for domain, value in device.identifiers:
        if domain == _HASSIO_DOMAIN and value not in _NOT_A_REAL_ADDON_SLUG and not value.startswith("mount_"):
            return value
    return None


async def resolve_full_identity(
    hass: HomeAssistant, entity_id: str, release_url: str | None, latest_version: str, installed_version: str
) -> ResolvedIdentity | None:
    """resolve_identity, extended with the two categories that need a real
    hass (devices, apps), plus the one that needs an async blueprint-file
    read (blueprint). Tries the cheap, pure checks (home-assistant, hacs)
    first, then the one async check (blueprint, gated on entity_registry's
    own platform field inside async_spook_blueprint_info, so this is a fast
    reject for the overwhelming majority of entities that aren't Spook's),
    only falling back to a single device_registry/entity_registry lookup
    (shared between the devices and apps checks below, found by review:
    they used to each re-fetch the device independently) when none of
    those already resolve it, since that's the common case and a registry
    lookup is comparatively expensive.

    installed_version is passed straight through to resolve_identity (see
    that function's own docstring for the normalization it applies) --
    callers are expected to have already treated a missing/unknown
    installed_version as "can't identify this at all", same as a missing
    release_url, so this takes a plain str, not Optional."""
    spook_info = await async_spook_blueprint_info(hass, entity_id)
    identity = resolve_identity(
        entity_id,
        release_url,
        latest_version,
        installed_version,
        is_hacs_entity=is_hacs_entity(hass, entity_id),
        blueprint_source_url=spook_info.source_url if spook_info is not None else None,
    )
    if identity is not None:
        return identity

    device = device_for_entity(hass, entity_id)
    if device is None:
        return None

    # Whichever category this device resolves to (if any), resolve_identity
    # is called exactly once more, with that one category's own kwargs --
    # found by review: this used to call it again for the devices check,
    # then again for the apps check on top of that, silently re-running the
    # already-failed home-assistant/hacs checks a second (or third) time.
    device_manufacturer: str | None = None
    device_model: str | None = None
    app_slug: str | None = None
    manufacturer_model = resolve_device_manufacturer_model(hass, device)
    if manufacturer_model is not None:
        device_manufacturer, device_model = manufacturer_model
    else:
        app_slug = resolve_app_slug(device)

    if device_manufacturer is None and app_slug is None:
        return None
    return resolve_identity(
        entity_id,
        release_url,
        latest_version,
        installed_version,
        device_manufacturer=device_manufacturer,
        device_model=device_model,
        app_slug=app_slug,
    )
