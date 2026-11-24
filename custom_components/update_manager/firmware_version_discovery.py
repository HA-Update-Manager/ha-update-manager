"""Decides, for a single Zigbee update entity, what real (human-readable)
firmware version strings are known for its installed/latest raw OTA
integers, and whether a newly-observed pairing is worth submitting to
community-votes. Needs a real hass (device registry lookups), so -- same as
zigbee.py/device_identity.py -- this has no dedicated unit tests, consistent
with this project's established test scope.

Deliberately split from firmware_version_registry.py (the HTTP-fetch/cache
module): this only ever does a synchronous, no-network peek
(FirmwareVersionManager.peek_cached_versions) against whatever that module
already has cached, it never fetches anything itself -- safe to call from a
hot path. Takes the manager itself (not a pre-sliced table) since this is
also the one place that resolves which (manufacturer, model_id) a given
entity's table even is -- resolving that twice (once here, once again in a
caller that tried to pre-slice its own table) would be the only alternative.

Keyed by model_id, not HA's own generic, human-readable model description
-- see device_identity.py's own resolve_zigbee_manufacturer_model_id
docstring for why: that description can be ambiguous across genuinely
different hardware (two real Hue motion-sensor models, confirmed live,
2026-11-24), each with its own, separate raw-OTA-version numbering.

Display (what's shown to the user) almost always reads the shared
community-votes table and nothing else -- a device's own live sw_version is
never trusted on its own, since a live read reflects whatever the device
happens to report at that one moment, not a necessarily stable fact (found
live, 2026-11-24: showing it unconditionally produced a genuinely
inconsistent result for the exact same raw integer across different
History entries for the same device). The one exception is the entity's
own *currently installed* raw integer, right now (real_versions_for_entity
below, never backfill_real_versions_for_entry's own historical from/to):
shown from that same live sw_version immediately, ahead of the table,
precisely because it's already passed the identical trustworthiness check
(_sw_version_is_trustworthy) a submission of it would -- not a different,
less-checked fact shown early, exactly what submitting it would eventually
write to that same table anyway (direct user feedback, 2026-11-24), just
without first waiting on the submit/process/re-fetch round trip. Once a
device has moved past a given raw integer, only the table can speak for it
again -- its own live sw_version only ever describes what it's running
*right now*.
"""
from __future__ import annotations

import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .device_identity import resolve_zigbee_manufacturer_model_id
from .firmware_version_registry import FirmwareVersionManager
from .zigbee import device_for_entity, is_zigbee2mqtt_device
from .zigbee_ota_release_notes import parse_zigbee_ota_version

# (manufacturer, model_id, raw_version, real_version)
SubmissionCandidate = tuple[str, str, int, str]

# Kept in sync, by hand, with community-votes' own process-firmware-version.yml
# shape check (2-4 numeric components, optional suffix -- deliberately not
# strict 3-part semver, other vendors may differ from Hue's own 3-part
# scheme). Applied here too, not just server-side: direct user feedback,
# 2026-11-24 ("als we er niks mee kunnen moet het niet eens op GitHub
# belanden") -- a submission this integration can already tell would be
# rejected shouldn't ever be sent at all, not sent-then-rejected.
_REAL_VERSION_RE = re.compile(r"^\d+(\.\d+){1,3}(-.+)?$")


def _looks_like_real_version(value: str, raw_version: int) -> bool:
    """False for anything community-votes' own workflow would reject
    outright (not version-shaped, or literally identical to the raw
    integer -- not a real mapping at all, just an echo)."""
    return bool(_REAL_VERSION_RE.match(value)) and value != str(raw_version)


def _sw_version_is_trustworthy(sw_version: str, raw_version: int, cached_table: dict[str, str]) -> bool:
    """Whether a device's own live sw_version is worth submitting as
    raw_version's own real version -- only ever used for that discovery
    decision now, never for display (see this module's own docstring).
    False for anything _looks_like_real_version already rejects, or --
    the stronger, live-data-driven check -- whenever sw_version is already
    the table's own value for a *different* raw integer. Zigbee2MQTT's own
    sw_version can get stuck across several real OTA installs when it
    hasn't re-interviewed the device since (confirmed live, 2026-11-24: the
    exact same real string attached to three different raw integers in a
    row for the same entity, each one a genuinely distinct, independently
    completed install) -- without this check, that same stuck string would
    get submitted as if it were this new raw integer's own real version
    too, corrupting the shared table for every other instance with this
    exact model. Direct user feedback, 2026-11-24 ("het moet dan toch niet
    kunnen dat die bij andere versies tegelijk staat").

    Only catches this once the table already has at least one *other*
    raw integer's own distinct value to compare against -- a model's very
    first-ever submission has nothing to disagree with yet, so this can't
    be a complete guarantee, only a cheap, high-value check against the
    most common real case (a later jump for the same model/device)."""
    if not _looks_like_real_version(sw_version, raw_version):
        return False
    return all(raw == str(raw_version) or real != sw_version for raw, real in cached_table.items())


def _real_version_for_raw(raw_version: int | None, cached_table: dict[str, str]) -> str | None:
    """The shared table's own real version for one specific raw OTA
    integer -- the only source display ever uses (see this module's own
    docstring), so the same raw integer always resolves to the same
    result everywhere it's looked up, regardless of which side of which
    jump it's on or when it's checked."""
    if raw_version is None:
        return None
    return cached_table.get(str(raw_version))


def same_value_for_different_raw(
    raw_a: int | None, real_a: str | None, raw_b: int | None, real_b: str | None
) -> bool:
    """True when two genuinely different raw integers would show the
    *same* real version. Almost always a sign the table itself still
    holds a stale entry from before process-firmware-version.yml's own
    matching reject existed (same reasoning as _sw_version_is_trustworthy
    above), not a real fact -- a defense-in-depth display-time check, kept
    even though display is now table-only throughout, in case either side
    ever updates its own cache slightly ahead of the other. Direct user
    feedback, 2026-11-24: in a case this unclear, don't show either side
    with false confidence rather than guess which one, if either, is
    right."""
    return raw_a is not None and raw_b is not None and raw_a != raw_b and real_a is not None and real_a == real_b


def _resolve_model_table(
    hass: HomeAssistant, entity_id: str, firmware_version_manager: FirmwareVersionManager | None
) -> tuple[dr.DeviceEntry, str, str, dict[str, str]] | None:
    """(device, manufacturer, model_id, cached_table) for entity_id's own
    device, or None if firmware_version_manager isn't available yet, the
    entity has no device, or it isn't a Zigbee device at all -- the one
    shared resolution step both real_versions_for_entity and
    backfill_real_versions_for_entry need before they can do anything
    else."""
    if firmware_version_manager is None:
        return None
    device = device_for_entity(hass, entity_id)
    if device is None:
        return None
    manufacturer_model_id = resolve_zigbee_manufacturer_model_id(hass, device)
    if manufacturer_model_id is None:
        return None
    manufacturer, model_id = manufacturer_model_id
    cached_table = firmware_version_manager.peek_cached_versions(manufacturer, model_id)
    return device, manufacturer, model_id, cached_table


def _display_reals(
    version_a: str | None, version_b: str | None, cached_table: dict[str, str]
) -> tuple[str | None, str | None]:
    """(real_a, real_b) for two raw-OTA-version strings -- installed/
    latest for a live entity, or a History entry's own from/to -- always
    the shared table's own value for each (see _real_version_for_raw),
    nulled out together if they'd show an identical real version for two
    genuinely different raw integers (see same_value_for_different_raw)."""
    raw_a = parse_zigbee_ota_version(version_a)
    raw_b = parse_zigbee_ota_version(version_b)
    real_a = _real_version_for_raw(raw_a, cached_table)
    real_b = _real_version_for_raw(raw_b, cached_table)
    if same_value_for_different_raw(raw_a, real_a, raw_b, real_b):
        return None, None
    return real_a, real_b


def real_versions_for_entity(
    hass: HomeAssistant,
    entity_id: str,
    installed_version: str | None,
    latest_version: str | None,
    firmware_version_manager: FirmwareVersionManager | None,
) -> tuple[str | None, str | None, SubmissionCandidate | None]:
    """(installed_version_real, latest_version_real, submission_candidate).

    The first two always come from the shared table alone (see this
    module's own docstring) -- nobody knows a pending target's real
    string firsthand before it's actually installed somewhere, and a
    device's own live sw_version is deliberately never shown directly,
    only ever consulted below for submission_candidate.

    submission_candidate is only ever set from that live sw_version, and
    only when the table has genuinely no entry at all yet for this exact
    raw integer -- never when one already exists but disagrees (that's a
    conflict, not a new discovery; community-votes' own workflow would
    reject it outright rather than overwrite it, so this never even
    attempts it, direct user feedback, 2026-11-24), and never when
    sw_version isn't trustworthy (see _sw_version_is_trustworthy above).
    Submitting only ever happens in reaction to a genuine install
    completing (see coordinator.py's own install listener), never from a
    general per-tick scan -- this function itself has no opinion on when
    it's called, it just answers "would this be worth submitting right
    now".
    """
    resolved = _resolve_model_table(hass, entity_id, firmware_version_manager)
    if resolved is None:
        return None, None, None
    device, manufacturer, model_id, cached_table = resolved

    installed_raw = parse_zigbee_ota_version(installed_version)
    latest_raw = parse_zigbee_ota_version(latest_version)
    installed_version_real = _real_version_for_raw(installed_raw, cached_table)
    latest_version_real = _real_version_for_raw(latest_raw, cached_table)
    # Validated once, shared by both the submission decision below and
    # installed_version_real's own live preference right after -- found
    # live, 2026-11-24, checking the real data already submitted before
    # this guard existed -- several Zigbee2MQTT-managed devices
    # (Aqara/Lidl among them) report their own sw_version as Zigbee2MQTT's
    # own bridge version string ("Zigbee2MQTT 2.14.3", not a per-device OTA
    # version at all) whenever Z2M hasn't actually learned one for that
    # specific device yet, and a handful of devices briefly report a
    # literal "-1" installed_version (an update entity's own "not yet
    # known" sentinel, not a real OTA integer). Neither is this device's
    # own real firmware version. _looks_like_real_version's own shape check
    # already rejects the bridge-version string (it doesn't start with a
    # digit); installed_raw > 0 additionally rejects the sentinel (a real
    # Zigbee OTA file_version is an unsigned 32-bit value, never negative
    # or zero).
    sw_version = device.sw_version if is_zigbee2mqtt_device(hass, device) else None
    sw_version_valid = (
        bool(sw_version)
        and installed_raw is not None
        and installed_raw > 0
        and _sw_version_is_trustworthy(sw_version, installed_raw, cached_table)
    )
    # Shown immediately, ahead of the shared table, only once it's passed
    # the exact same trustworthiness gate a submission of it would -- it's
    # not a *different*, less-checked fact being shown early, it's exactly
    # what submitting it would eventually write to that same table anyway
    # (direct user feedback, 2026-11-24), just without first waiting on
    # the submit/process/re-fetch round trip. Never applied to a History
    # entry's own from/to (see backfill_real_versions_for_entry below): the
    # device backing a past entry has long since moved past whichever raw
    # integer that entry names, so its live sw_version can't attest to it
    # at all anymore, only to whatever it's running *right now*.
    if sw_version_valid:
        installed_version_real = sw_version

    submission_candidate = (
        (manufacturer, model_id, installed_raw, sw_version)
        if sw_version_valid and str(installed_raw) not in cached_table
        else None
    )

    if same_value_for_different_raw(installed_raw, installed_version_real, latest_raw, latest_version_real):
        installed_version_real = None
        latest_version_real = None
        submission_candidate = None

    return installed_version_real, latest_version_real, submission_candidate


def backfill_real_versions_for_entry(
    hass: HomeAssistant,
    entity_id: str,
    from_version: str | None,
    to_version: str | None,
    firmware_version_manager: FirmwareVersionManager | None,
) -> tuple[str | None, str | None]:
    """(from_version_real, to_version_real) for an already-logged History
    entry's own from/to raw integers -- same table-only lookup as
    real_versions_for_entity's own display values above, nothing specific
    to a historical entry needed anymore now that display never reads a
    device's own live sw_version (see this module's own docstring)."""
    resolved = _resolve_model_table(hass, entity_id, firmware_version_manager)
    if resolved is None:
        return None, None
    _, _, _, cached_table = resolved
    return _display_reals(from_version, to_version, cached_table)
