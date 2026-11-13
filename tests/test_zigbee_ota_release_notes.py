"""Tests for the pure, HA-independent zigpy-ota native-index matcher.

Fixture entries mirror real shapes sampled from zigpy-ota's own published
zigpy_v2_ota.json (release/version/stable.json's own zigpy_v2 channel,
checked 2026-11-13): manufacturer_names/model_names are list fields, most
entries have neither at all, and a model can have several real historical
entries sharing the same (manufacturer_id, image_type) slot -- confirmed
live with Sonoff's own "S60ZBTPF"/"S60ZBTPG" plug (5 successive firmwares).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "zigbee_ota_release_notes.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_zigbee_ota_release_notes", _MODULE_PATH)
zigbee_ota_release_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(zigbee_ota_release_notes)

# Real confirmed shape: one slot (manufacturer_id 4742, image_type 11), five
# successive real firmwares, each updating the same two model variants.
_SONOFF_PLUG_V1 = {
    "model_names": ["S60ZBTPF", "S60ZBTPG"],
    "manufacturer_names": ["SONOFF"],
    "manufacturer_id": 4742,
    "image_type": 11,
    "file_version": 8194,
    "release_notes": "This updates the Sonoff Plug S60ZBTPF/S60ZBTPG to firmware version 2.0.2.",
    "release_url": "https://github.com/zigpy/zigpy-ota/pull/1",
    "binary_url": "https://example.com/v1.ota",
}
_SONOFF_PLUG_V2 = {
    **_SONOFF_PLUG_V1,
    "file_version": 8195,
    "release_notes": "This updates the Sonoff Plug S60ZBTPF/S60ZBTPG to firmware version 2.0.3.",
    "release_url": "https://github.com/zigpy/zigpy-ota/pull/2",
}
_SONOFF_PLUG_V3 = {
    **_SONOFF_PLUG_V1,
    "file_version": 8451,
    "release_notes": "This updates the Sonoff Plug S60ZBTPF/S60ZBTPG to firmware version 2.1.3.",
    "release_url": "https://github.com/zigpy/zigpy-ota/pull/3",
}
_SONOFF_HISTORY = [_SONOFF_PLUG_V1, _SONOFF_PLUG_V2, _SONOFF_PLUG_V3]

_NO_MODEL_FIELD = {
    "manufacturer_id": 1310,
    "image_type": 0,
    "file_version": 17,
    "release_notes": "Some aeotec device update, no model info at all.",
}


class TestFindZigbeeOtaReleaseNotes:
    def test_returns_none_without_model_id_or_to_version(self):
        assert zigbee_ota_release_notes.find_zigbee_ota_release_notes(_SONOFF_HISTORY, "SONOFF", None, None, 8451) is None
        assert zigbee_ota_release_notes.find_zigbee_ota_release_notes(_SONOFF_HISTORY, "SONOFF", "S60ZBTPF", None, None) is None

    def test_single_exact_match_when_no_from_version(self):
        found = zigbee_ota_release_notes.find_zigbee_ota_release_notes(_SONOFF_HISTORY, "SONOFF", "S60ZBTPF", None, 8195)
        assert found == zigbee_ota_release_notes.ZigbeeOtaMatch(
            release_notes="This updates the Sonoff Plug S60ZBTPF/S60ZBTPG to firmware version 2.0.3.",
            source_url="https://github.com/zigpy/zigpy-ota/pull/2",
        )

    def test_matches_second_model_name_in_the_same_list(self):
        found = zigbee_ota_release_notes.find_zigbee_ota_release_notes(_SONOFF_HISTORY, "SONOFF", "S60ZBTPG", None, 8195)
        assert found is not None

    def test_compiles_full_range_between_from_and_to_version_newest_first(self):
        found = zigbee_ota_release_notes.find_zigbee_ota_release_notes(_SONOFF_HISTORY, "SONOFF", "S60ZBTPF", 8194, 8451)
        assert found.release_notes == (
            "This updates the Sonoff Plug S60ZBTPF/S60ZBTPG to firmware version 2.1.3.\n\n"
            "---\n\n"
            "This updates the Sonoff Plug S60ZBTPF/S60ZBTPG to firmware version 2.0.3."
        )
        assert found.source_url == "https://github.com/zigpy/zigpy-ota/pull/3"

    def test_range_excludes_from_version_itself(self):
        """from_version is what's already installed -- same "excluded, the
        reader already knows it" reasoning as compile_release_range's own
        upgrade path."""
        found = zigbee_ota_release_notes.find_zigbee_ota_release_notes(_SONOFF_HISTORY, "SONOFF", "S60ZBTPF", 8195, 8451)
        assert "2.0.3" not in found.release_notes
        assert "2.1.3" in found.release_notes

    def test_from_version_equal_or_newer_than_to_version_is_single_match_only(self):
        """A downgrade or no-op jump never expands into a range -- only the
        exact target version's own entry."""
        found = zigbee_ota_release_notes.find_zigbee_ota_release_notes(_SONOFF_HISTORY, "SONOFF", "S60ZBTPF", 8451, 8195)
        assert found.release_notes == "This updates the Sonoff Plug S60ZBTPF/S60ZBTPG to firmware version 2.0.3."

    def test_falls_back_to_binary_url_when_no_release_url(self):
        entry = dict(_SONOFF_PLUG_V1)
        del entry["release_url"]
        found = zigbee_ota_release_notes.find_zigbee_ota_release_notes([entry], "SONOFF", "S60ZBTPF", None, 8194)
        assert found.source_url == "https://example.com/v1.ota"

    def test_to_version_with_no_matching_entry_is_no_match(self):
        found = zigbee_ota_release_notes.find_zigbee_ota_release_notes(_SONOFF_HISTORY, "SONOFF", "S60ZBTPF", None, 9999)
        assert found is None

    def test_wrong_manufacturer_is_no_match_even_with_right_model_and_version(self):
        found = zigbee_ota_release_notes.find_zigbee_ota_release_notes(
            _SONOFF_HISTORY, "SomeOtherVendor", "S60ZBTPF", None, 8195
        )
        assert found is None

    def test_missing_manufacturer_names_on_entry_does_not_block_a_match(self):
        """Most real entries have no manufacturer_names/model_names at all
        -- model_id alone (when the entry does have model_names) or just
        the right slot must still work, never blocked by a field that
        simply isn't there."""
        entry = dict(_NO_MODEL_FIELD, model_names=["AEOTEC-1"])
        found = zigbee_ota_release_notes.find_zigbee_ota_release_notes([entry], "Aeotec", "AEOTEC-1", None, 17)
        assert found is not None

    def test_two_different_slots_matching_the_same_model_id_is_ambiguous(self):
        """A genuinely different (manufacturer_id, image_type) slot that
        happens to also list this model_id must never be guessed through."""
        other_slot = dict(_SONOFF_PLUG_V1, image_type=99, file_version=8194)
        found = zigbee_ota_release_notes.find_zigbee_ota_release_notes(
            [_SONOFF_PLUG_V1, other_slot], "SONOFF", "S60ZBTPF", None, 8194
        )
        assert found is None

    def test_duplicate_file_version_within_range_keeps_one_entry_not_both(self):
        """zigpy-ota's own documented specificity tie-break shape (two
        images for the same nominal version, gated to different hardware
        revisions) -- deduplicated by file_version rather than refusing
        the whole range or showing both near-identical texts."""
        tie = dict(_SONOFF_PLUG_V2, release_notes="A different hardware revision's own text for 2.0.3.")
        found = zigbee_ota_release_notes.find_zigbee_ota_release_notes(
            [_SONOFF_PLUG_V1, _SONOFF_PLUG_V2, tie, _SONOFF_PLUG_V3], "SONOFF", "S60ZBTPF", 8194, 8451
        )
        assert found is not None
        assert found.release_notes.count("2.0.3") == 1

    def test_entry_with_no_release_notes_is_not_a_match(self):
        entry = dict(_SONOFF_PLUG_V1, release_notes="")
        assert zigbee_ota_release_notes.find_zigbee_ota_release_notes([entry], "SONOFF", "S60ZBTPF", None, 8194) is None

    def test_empty_index_returns_none(self):
        assert zigbee_ota_release_notes.find_zigbee_ota_release_notes([], "SONOFF", "S60ZBTPF", None, 8194) is None
