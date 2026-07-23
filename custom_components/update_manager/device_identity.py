"""HA-dependent counterpart to hacs_identity.py's pure resolve_identity: looks
up an update entity's device_registry/entity_registry entries and turns
them into the is_hacs_entity/device_manufacturer/device_model/app_slug
arguments resolve_identity expects, for everything that needs a real hass
(confirming an entity is actually HACS-owned, plus the devices/apps
categories). Kept out of hacs_identity.py itself so that module stays free
of any homeassistant import (see its own docstring).

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
_HACS_DOMAIN = "hacs"


def is_hacs_entity(hass: HomeAssistant, entity_id: str) -> bool:
    """Whether entity_id's owning integration is HACS itself. Found live,
    2026-07-22 (real bug hit on an ESPHome device's update entity, wrongly
    identified as HACS): a plausible-looking https://github.com/... in
    release_url is not enough on its own, plenty of built-in integrations
    (ESPHome, for one) set a perfectly real GitHub release_url pointing at
    their own upstream project, nothing to do with HACS at all. Verified
    against hacs/integration's own source (custom_components/hacs/
    update.py): every genuinely HACS-installed repo's update entity is
    created by HacsRepositoryUpdateEntity, which belongs to HACS's own
    integration domain -- including repos with no backend Python component
    of their own at all (e.g. a pure Lovelace card), so this is the one
    check that covers all of them, not just some."""
    entry = er.async_get(hass).async_get(entity_id)
    return entry is not None and entry.platform == _HACS_DOMAIN

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


def resolve_full_identity(
    hass: HomeAssistant, entity_id: str, release_url: str | None, latest_version: str
) -> ResolvedIdentity | None:
    """resolve_identity, extended with the two categories that need a real
    hass (devices, apps). Tries the cheap, pure checks (home-assistant,
    hacs) first, only falling back to a single device_registry/
    entity_registry lookup (shared between the devices and apps checks
    below, found by review: they used to each re-fetch the device
    independently) when those don't already resolve it, since that's the
    common case and a registry lookup is comparatively expensive."""
    identity = resolve_identity(
        entity_id, release_url, latest_version, is_hacs_entity=is_hacs_entity(hass, entity_id)
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
        device_manufacturer=device_manufacturer,
        device_model=device_model,
        app_slug=app_slug,
    )
