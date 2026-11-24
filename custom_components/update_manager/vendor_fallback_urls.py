"""Static, per-manufacturer release-notes URLs: a last-resort fallback for
the existing "Open release announcement" link row (buildReleaseUrlLinkRow
in update-manager-panel.js), used only once every other, more specific
source has already come back empty (native notes, GitHub-compiled range,
zigpy-ota index, and release_url/corrected_release_url itself). Not a new
UI concept: this reuses the exact same release_url slot Reolink's own
static, non-version-specific release_url already occupies today.

Keyed purely by device.manufacturer, read directly off the device registry
for the entity's own device (zigbee.py's device_for_entity) -- not
restricted to Zigbee devices specifically. Confirmed live, 2026-11-23:
UniFi's own update entities set manufacturer="Ubiquiti Networks" via a
plain DeviceInfo, the same registry field a ZHA/Zigbee2MQTT device's real
vendor lands in (device_identity.py's own resolve_device_manufacturer_model
restricts itself to Zigbee specifically for a different reason, the
community-votes "devices" identity category, not relevant here), so one
single table, keyed the same way for every entity, covers both.

Cross-checked against Zigbee2MQTT's own frontend, 2026-11-24
(zigbee2mqtt-frontend's vendor-links.tsx, its own OTALink component) --
not reusable as code (a separate React project, a different language and
runtime entirely), but the exact same kind of hand-maintained per-vendor
table this module already is, so worth aligning with directly rather than
maintaining two independently-researched versions of the same facts:
- IKEA of Sweden: Zigbee2MQTT's own ww8.ikea.com/ikeahomesmart/releasenotes/
  releasenotes.html was considered as a replacement for this module's own
  releases.homesmart.ikea.com (the latter loads but returns an empty body
  to a plain fetch, found live, 2026-11-24) -- direct user feedback,
  2026-11-24: keep the original anyway, so this module's own entry is
  unchanged. Possibly a client-rendered page a plain fetch can't see
  through, not necessarily actually empty for a real browser.
- Philips/Signify: Zigbee2MQTT's own OTALink splits "lamps" vs
  "accessories" by whether the device exposes a light feature -- confirmed
  live, 2026-11-24, both pages are real and current (lamps: light
  firmware; accessories: sensors/switches/dimmers), so this module now
  makes the same split instead of always pointing non-light Hue devices
  (a motion sensor, a dimmer switch) at the lamps page.
- Inovelli and Ubisys added, both confirmed live, 2026-11-24, against
  Zigbee2MQTT's own URLs for them -- vendors this module had no entry for
  at all before.

Each entry verified live against a real device/page, 2026-11-23 unless
noted above as re-verified/replaced on 2026-11-24:
- Philips/Signify: a real Hue bulb reached via Zigbee2MQTT reports
  manufacturer="Philips" even for a current-generation product (seen on a
  real device, "Hue white ambiance ceiling light Enrave S"), not just
  older ones -- both strings are kept since which one a given device/
  integration combination reports isn't fully predictable.
- Ubiquiti Networks: community.ui.com/releases, not per-device but the
  only reliable single URL found.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .hacs_identity import corrected_release_url
from .zigbee import device_for_entity

_STATIC_MANUFACTURER_URLS = {
    "ikea of sweden": "https://releases.homesmart.ikea.com/",
    "ubiquiti networks": "https://community.ui.com/releases",
    "inovelli": "https://help.inovelli.com/en/articles/8503774-what-is-the-latest-firmware-version-for-your-device",
}

# Zigbee's own model_id, not the generic model description -- same
# model/model_id distinction firmware_version_discovery.py's own docstring
# explains, here because Ubisys' own URL is built from it (a dash-stripped,
# lowercased model slug, e.g. "S2" -> "change-logs-s2"), and the generic
# description is more likely to be ambiguous or contain extra words a
# model_id doesn't.
_UBISYS_CHANGE_LOG_URL = "https://www.ubisys.de/en/support/firmware/change-logs-{model_slug}/"


def _is_light_device(hass: HomeAssistant, device_id: str) -> bool:
    """Whether device_id has at least one entity in the light domain --
    mirrors Zigbee2MQTT's own OTALink component, which picks its Philips
    "lamps" vs "accessories" release-notes page the same way (does this
    device's own exposes list a light feature)."""
    registry = er.async_get(hass)
    return any(
        entry.domain == "light" for entry in er.async_entries_for_device(registry, device_id)
    )


def vendor_fallback_release_url(hass: HomeAssistant, entity_id: str) -> str | None:
    """A generic, non-version-specific vendor release-notes URL for
    entity_id's own device, or None if it has no device at all, the device
    has no manufacturer set, or that manufacturer isn't covered. Callers
    only use this once every more specific source has already come back
    empty, see this module's own docstring."""
    device = device_for_entity(hass, entity_id)
    if device is None or not device.manufacturer:
        return None
    manufacturer = device.manufacturer.strip().lower()

    if manufacturer in ("philips", "signify netherlands b.v."):
        page = "lamps" if _is_light_device(hass, device.id) else "accessories"
        return f"https://www.philips-hue.com/en-us/support/release-notes/{page}"

    if manufacturer == "ubisys" and device.model:
        model_slug = device.model.replace("-", "").lower()
        return _UBISYS_CHANGE_LOG_URL.format(model_slug=model_slug)

    return _STATIC_MANUFACTURER_URLS.get(manufacturer)


def release_url_for_entity(
    hass: HomeAssistant, entity_id: str, native_release_url: str | None, version: str
) -> str | None:
    """The one release_url to actually show, for any caller building a
    user-facing display of it: corrected_release_url's own entity-specific
    fix-ups (Core's own always-latest native URL chief among them) first,
    this module's own static per-manufacturer fallback once that still
    comes back empty. Three call sites (coordinator.py's own
    _async_cache_active/_cache_skipped, __init__.py's own install-log
    capture) used to each repeat this exact `corrected_release_url(...) or
    vendor_fallback_release_url(...)` pair by hand (found by /simplify) --
    one shared place for "the" release-url decision instead, so a future
    call site can't forget this fallback tier the way a copy-pasted `or`
    chain risks."""
    return corrected_release_url(entity_id, native_release_url, version) or vendor_fallback_release_url(
        hass, entity_id
    )
