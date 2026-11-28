"""Tests for the pure, HA-independent AI safety check instructions builder."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "update_manager" / "ai_safety_check_prompt.py"
)
_spec = importlib.util.spec_from_file_location("update_manager_ai_safety_check_prompt", _MODULE_PATH)
ai_safety_check_prompt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ai_safety_check_prompt)


class TestBuildAiSafetyCheckInstructions:
    def test_includes_update_name_and_version_jump(self):
        instructions = ai_safety_check_prompt.build_ai_safety_check_instructions(
            "Hue Bridge", "1.93.7", "1.94.0", "Some release notes."
        )
        assert "Hue Bridge" in instructions
        assert "1.93.7 -> 1.94.0" in instructions

    def test_includes_the_release_text_verbatim(self):
        instructions = ai_safety_check_prompt.build_ai_safety_check_instructions(
            "Hue Bridge", "1.93.7", "1.94.0", "Fixes a serious startup regression."
        )
        assert "Fixes a serious startup regression." in instructions

    def test_states_the_blocking_criteria(self):
        instructions = ai_safety_check_prompt.build_ai_safety_check_instructions(
            "Hue Bridge", "1.93.7", "1.94.0", "Some release notes."
        )
        assert "breaking change" in instructions
        assert "data loss" in instructions

    def test_states_vague_caution_is_not_sufficient(self):
        instructions = ai_safety_check_prompt.build_ai_safety_check_instructions(
            "Hue Bridge", "1.93.7", "1.94.0", "Some release notes."
        )
        assert "vague" in instructions

    def test_asks_for_a_short_reason(self):
        instructions = ai_safety_check_prompt.build_ai_safety_check_instructions(
            "Hue Bridge", "1.93.7", "1.94.0", "Some release notes."
        )
        assert "one short, plain sentence" in instructions

    def test_asks_for_a_notable_flag_separate_from_reason(self):
        instructions = ai_safety_check_prompt.build_ai_safety_check_instructions(
            "Hue Bridge", "1.93.7", "1.94.0", "Some release notes."
        )
        assert "notable must be true" in instructions
        assert "Always fill this in" in instructions

    def test_without_messages_has_no_messages_section(self):
        instructions = ai_safety_check_prompt.build_ai_safety_check_instructions(
            "Hue Bridge", "1.93.7", "1.94.0", "Some release notes."
        )
        assert "developer warnings" not in instructions.lower()

    def test_with_messages_includes_each_one_with_its_severity(self):
        instructions = ai_safety_check_prompt.build_ai_safety_check_instructions(
            "Hue Bridge",
            "1.93.7",
            "1.94.0",
            "Some release notes.",
            messages=[
                {"severity": "warning", "message": "Do not interrupt power during this update."},
                {"severity": "info", "message": "This update may take several minutes."},
            ],
        )
        assert "[warning] Do not interrupt power during this update." in instructions
        assert "[info] This update may take several minutes." in instructions

    def test_handles_a_multi_version_jump_the_same_way(self):
        instructions = ai_safety_check_prompt.build_ai_safety_check_instructions(
            "Hue Bridge", "1.90.0", "1.94.0", "Combined notes for 1.91.0, 1.92.0, 1.93.0, and 1.94.0."
        )
        assert "1.90.0 -> 1.94.0" in instructions
        assert "multi-version jump" in instructions
