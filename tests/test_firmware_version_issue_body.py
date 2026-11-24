"""Tests for the pure, HA-independent firmware-version-issue-body construction."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# firmware_version_issue_body.py does `from .vote_issue_body import _field`
# (both pure, HA-independent modules, see each one's own docstring), so this
# needs the same minimal parent package registered in sys.modules as
# test_vote_issue_body.py's own workaround, for that relative import to
# resolve.
_PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "update_manager"
_PKG_NAME = "update_manager_test_pkg"
if _PKG_NAME not in sys.modules:
    _pkg = types.ModuleType(_PKG_NAME)
    _pkg.__path__ = [str(_PKG_DIR)]
    sys.modules[_PKG_NAME] = _pkg


def _load(module_name):
    spec = importlib.util.spec_from_file_location(f"{_PKG_NAME}.{module_name}", _PKG_DIR / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


vote_issue_body = _load("vote_issue_body")
firmware_version_issue_body = _load("firmware_version_issue_body")


class TestBuildIssueBody:
    def test_builds_every_field_in_order(self):
        body = firmware_version_issue_body.build_issue_body("Philips", "LCT024", 16786436, "1.164.2", "3.4.0")
        assert body == (
            "### Manufacturer\n\nPhilips\n\n"
            "### Model\n\nLCT024\n\n"
            "### Raw OTA version\n\n16786436\n\n"
            "### Real firmware version\n\n1.164.2\n\n"
            "### Reported by Update Manager version\n\n3.4.0\n"
        )

    def test_raw_version_rendered_as_plain_integer_text(self):
        body = firmware_version_issue_body.build_issue_body("IKEA of Sweden", "TRADFRI bulb E27", 16788224, "2.3.0", "3.4.0")
        assert "### Raw OTA version\n\n16788224\n" in body
