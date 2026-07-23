"""Tests for the pure, HA-independent vote-issue-body construction."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# vote_issue_body.py does `from .hacs_identity import ResolvedIdentity` (both
# pure, HA-independent modules, see each one's own docstring), so this needs
# the same minimal parent package registered in sys.modules as
# test_hacs_identity.py's own workaround, for that relative import to
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


hacs_identity = _load("hacs_identity")
vote_issue_body = _load("vote_issue_body")


class TestBuildIssueBody:
    def test_hacs_healthy_vote(self):
        identity = hacs_identity.ResolvedIdentity("hacs", "1.2.3", owner_repo="owner/repo")
        body = vote_issue_body.build_issue_body(identity, "healthy", None, None, None)
        assert body == (
            "### Category\n\nhacs\n\n"
            "### Component\n\n_No response_\n\n"
            "### Owner/repo\n\nowner/repo\n\n"
            "### Manufacturer/model\n\n_No response_\n\n"
            "### App slug\n\n_No response_\n\n"
            "### Version\n\n1.2.3\n\n"
            "### Verdict\n\nhealthy\n\n"
            "### Reason category\n\n(not applicable, verdict is healthy)\n\n"
            "### Notes\n\n_No response_\n\n"
            "### Issue or changelog link\n\n_No response_\n"
        )

    def test_hacs_problematic_vote_with_all_optional_fields(self):
        identity = hacs_identity.ResolvedIdentity("hacs", "2.0.0", owner_repo="owner/repo")
        body = vote_issue_body.build_issue_body(
            identity, "problematic", "breaking change", "Broke my dashboard", "https://github.com/owner/repo/issues/5"
        )
        assert "### Verdict\n\nproblematic\n" in body
        assert "### Reason category\n\nbreaking change\n" in body
        assert "### Notes\n\nBroke my dashboard\n" in body
        assert "### Issue or changelog link\n\nhttps://github.com/owner/repo/issues/5\n" in body

    def test_home_assistant_vote_fills_component_not_owner_repo(self):
        identity = hacs_identity.ResolvedIdentity("home-assistant", "2026.7.3", component="core")
        body = vote_issue_body.build_issue_body(identity, "healthy", None, None, None)
        assert "### Component\n\ncore\n" in body
        assert "### Owner/repo\n\n_No response_\n" in body

    def test_device_vote_fills_manufacturer_model_joined(self):
        # Verified against community-votes' own vote.yml: a single
        # "manufacturer/model" field, not two separate ones.
        identity = hacs_identity.ResolvedIdentity("devices", "1.0.4", manufacturer_model="IKEA of Sweden/TRADFRI bulb E27")
        body = vote_issue_body.build_issue_body(identity, "healthy", None, None, None)
        assert "### Manufacturer/model\n\nIKEA of Sweden/TRADFRI bulb E27\n" in body
        assert "### Component\n\n_No response_\n" in body
        assert "### Owner/repo\n\n_No response_\n" in body
        assert "### App slug\n\n_No response_\n" in body

    def test_app_vote_fills_app_slug(self):
        identity = hacs_identity.ResolvedIdentity("apps", "6.5.0", app_slug="core_mosquitto")
        body = vote_issue_body.build_issue_body(identity, "healthy", None, None, None)
        assert "### App slug\n\ncore_mosquitto\n" in body
        assert "### Manufacturer/model\n\n_No response_\n" in body

    def test_healthy_reason_category_argument_ignored(self):
        # Even if a caller accidentally passes one, a "healthy" vote's own
        # reason-category field is always the fixed not-applicable text, not
        # whatever was passed in, matching the real Issue Form's own
        # required-only-when-problematic rule.
        identity = hacs_identity.ResolvedIdentity("hacs", "1.0.0", owner_repo="owner/repo")
        body = vote_issue_body.build_issue_body(identity, "healthy", "other", None, None)
        assert "### Reason category\n\n(not applicable, verdict is healthy)\n" in body
