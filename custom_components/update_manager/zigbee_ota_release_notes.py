"""Matches a device's pending firmware update against zigpy-ota's own native
index (zigpy_v2_ota.json -- the same one zigpy/ZHA itself consumes, see
zigbee_ota_index.py's own module docstring for why this one was chosen over
the also-published Zigbee2MQTT-compatible z2m_v1_ota.json), as a last-resort
fallback when nothing else has anything to show. Zigbee2MQTT is the practical
beneficiary today (confirmed against its real source, lib/extension/
homeassistant.ts: it never surfaces its own OTA check's release_notes/source
fields through the generic MQTT update entity, only latest_version/
installed_version), but nothing here is Zigbee2MQTT-specific -- see
websocket_api.py's own call site for the full reasoning.

Deliberately conservative about *which* entries this is willing to show at
all, even though it now also compiles a range (every real firmware version
between installed_version and latest_version, not just the last one -- see
this module's own CHANGELOG entry/conversation for why this was initially
left out and then reconsidered): manufacturer_names/model_names are list
fields ("for device matching", confirmed against zigpy-ota's own README),
so model_id must appear in model_names literally, and manufacturer must
appear in manufacturer_names whenever the entry actually has one (most
single-version entries don't; a multi-version group's entries always do in
practice). Every candidate must also belong to the exact same
(manufacturer_id, image_type) OTA slot -- two genuinely different slots that
happen to both list this model_id is an ambiguity this never guesses through.
latest_version must match some real entry's own file_version exactly before
anything is shown at all; a from_version lower than that entry's own expands
the result to every entry strictly in between, newest first, same read order
compile_release_range already uses for a GitHub range. Two entries sharing
the exact same file_version within that compiled range (zigpy-ota's own
documented `specificity` tie-break scenario, for images gated to different
hardware revisions of the same model) keeps just one of them rather than
duplicating near-identical text for the same nominal version -- the same
irreducible hardware-revision risk already applies to every other entry in
the range too (no hardware_version is available from a device's exposed
MQTT info at all), so this one rung isn't treated any more strictly than
the rest of the ladder.

fileVersion is Zigbee's own raw OTA image version integer, no inherent
semver meaning (vendor-defined, confirmed to vary in format even between two
firmwares of the same manufacturer), but Zigbee2MQTT's own
`update.latest_version`/`installed_version` are confirmed (against their
real otaUpdate.ts source) to be that exact same raw integer, not a formatted
string -- so this is a literal equality check throughout, never a decoded or
guessed one.
"""
from __future__ import annotations

from typing import Any, NamedTuple


def parse_zigbee_ota_version(value: Any) -> int | None:
    """value as an int, or None whenever it isn't one (missing, or a
    non-Zigbee-OTA entity's own version string, e.g. a semver) -- shared
    by both real callers (websocket_api.py's own
    _handle_zigbee_ota_release_notes, services.py's own
    _async_zigbee_ota_fallback), found by /simplify review: each had
    defined its own identical local helper for exactly this."""
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class ZigbeeOtaMatch(NamedTuple):
    release_notes: str
    # The newest compiled entry's own release_url (the zigpy-ota PR/issue
    # the image and its notes were submitted through) when present, else
    # its own binary_url -- either way, somewhere real to point a "source"
    # link at, never fabricated.
    source_url: str | None


def find_zigbee_ota_release_notes(
    index: list[dict[str, Any]],
    manufacturer: str | None,
    model_id: str | None,
    from_version: int | None,
    to_version: int | None,
) -> ZigbeeOtaMatch | None:
    """See this module's own docstring for the full matching/compilation
    rule. model_id or to_version missing entirely (not a real device, or
    its update entity hasn't published a usable value yet) short-circuits
    to None before even looking -- same "nothing to add" treatment as
    every other release-notes enrichment in this project."""
    if not model_id or to_version is None:
        return None
    manufacturer_lower = manufacturer.lower() if manufacturer else None
    candidates = []
    for entry in index:
        model_names = entry.get("model_names") or []
        if not any(str(name) == model_id for name in model_names):
            continue
        manufacturer_names = entry.get("manufacturer_names")
        if manufacturer_names and (
            not manufacturer_lower or not any(str(name).lower() == manufacturer_lower for name in manufacturer_names)
        ):
            continue
        if not entry.get("release_notes"):
            continue
        candidates.append(entry)
    if not candidates:
        return None
    slots = {(entry.get("manufacturer_id"), entry.get("image_type")) for entry in candidates}
    if len(slots) != 1:
        return None
    if not any(entry.get("file_version") == to_version for entry in candidates):
        return None
    if from_version is not None and from_version < to_version:
        selected = [entry for entry in candidates if from_version < entry.get("file_version", -1) <= to_version]
    else:
        selected = [entry for entry in candidates if entry.get("file_version") == to_version]
    if not selected:
        return None
    # One entry per file_version, first one encountered wins -- see this
    # module's own docstring for why a tie here doesn't abort the whole
    # range.
    by_version: dict[int, dict[str, Any]] = {}
    for entry in selected:
        by_version.setdefault(entry["file_version"], entry)
    selected = sorted(by_version.values(), key=lambda entry: entry["file_version"], reverse=True)
    notes = "\n\n---\n\n".join(entry["release_notes"] for entry in selected)
    newest = selected[0]
    return ZigbeeOtaMatch(release_notes=notes, source_url=newest.get("release_url") or newest.get("binary_url"))
