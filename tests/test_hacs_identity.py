"""Tests for the pure, HA-independent GitHub release URL identity extraction."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# hacs_identity.py does `from .semver import strip_version_prefix` (both are
# pure, HA-independent modules, see each one's own docstring), so unlike
# semver.py's/staging.py's own tests this needs a real, if minimal, parent
# package registered in sys.modules for that relative import to resolve --
# a bare spec_from_file_location (no package) can't satisfy it.
_PKG_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "update_manager"
_PKG_NAME = "update_manager_test_pkg"
if _PKG_NAME not in sys.modules:
    _pkg = types.ModuleType(_PKG_NAME)
    _pkg.__path__ = [str(_PKG_DIR)]
    sys.modules[_PKG_NAME] = _pkg

_spec = importlib.util.spec_from_file_location(f"{_PKG_NAME}.hacs_identity", _PKG_DIR / "hacs_identity.py")
hacs_identity = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = hacs_identity
_spec.loader.exec_module(hacs_identity)


class TestExtractHacsIdentity:
    def test_basic(self):
        url = "https://github.com/HA-Update-Manager/ha-update-manager/releases/tag/1.2.3"
        assert hacs_identity.extract_hacs_identity(url) == ("HA-Update-Manager", "ha-update-manager", "1.2.3")

    def test_v_prefix_stripped(self):
        url = "https://github.com/owner/repo/releases/tag/v2.0.0"
        assert hacs_identity.extract_hacs_identity(url) == ("owner", "repo", "2.0.0")

    def test_short_form_without_tag_segment(self):
        # Found live 2026-07-22 against ha-update-manager's own update
        # entity: GitHub accepts this shorter form as a real, working URL
        # too, not every integration's release_url uses the canonical
        # releases/tag/<tag> shape.
        url = "https://github.com/HA-Update-Manager/ha-update-manager/releases/v0.1.0"
        assert hacs_identity.extract_hacs_identity(url) == ("HA-Update-Manager", "ha-update-manager", "0.1.0")

    def test_no_v_prefix_left_untouched(self):
        url = "https://github.com/owner/repo/releases/tag/1.2.3"
        assert hacs_identity.extract_hacs_identity(url) == ("owner", "repo", "1.2.3")

    def test_version_starting_with_a_literal_v_word_not_stripped(self):
        # Only a "v"/"V" immediately followed by a digit counts as a
        # version-tag prefix -- a real (if unusual) version that happens to
        # start with a word beginning in v isn't mangled.
        url = "https://github.com/owner/repo/releases/tag/vNext-2026.1"
        assert hacs_identity.extract_hacs_identity(url) == ("owner", "repo", "vNext-2026.1")

    def test_none_input(self):
        assert hacs_identity.extract_hacs_identity(None) is None

    def test_empty_string(self):
        assert hacs_identity.extract_hacs_identity("") is None

    def test_non_github_url(self):
        assert hacs_identity.extract_hacs_identity("https://example.com/changelog") is None

    def test_github_url_wrong_shape(self):
        assert hacs_identity.extract_hacs_identity("https://github.com/owner/repo") is None
        assert hacs_identity.extract_hacs_identity("https://github.com/owner/repo/issues/5") is None

    def test_missing_owner_or_repo(self):
        assert hacs_identity.extract_hacs_identity("https://github.com//repo/releases/tag/1.0.0") is None


class TestResolveIdentity:
    def test_hacs_entity(self):
        url = "https://github.com/owner/repo/releases/tag/1.2.3"
        identity = hacs_identity.resolve_identity(
            "update.some_integration", url, "1.2.3", "1.0.0", is_hacs_entity=True
        )
        assert identity.category == "hacs"
        assert identity.owner_repo == "owner/repo"
        assert identity.component is None
        assert identity.to_version == "1.2.3"
        assert identity.from_version == "1.0.0"
        assert identity.to_version_path == "hacs/owner/repo/1.2.3"
        # release_url is kept as-is (not reconstructed/normalized) so
        # vote_issue_body.py can link straight to it -- callers are already
        # responsible for passing one that matches this exact version (see
        # websocket_api.py's own _release_url_for_version).
        assert identity.release_url == url

    def test_github_shaped_release_url_ignored_when_not_a_hacs_entity(self):
        # Found live, 2026-07-22 (real bug hit on an ESPHome device's update
        # entity): a genuinely real https://github.com/... release_url --
        # ESPHome's own upstream project releases, nothing to do with HACS
        # -- must not be enough on its own to resolve as "hacs". Only
        # device_identity.py's own is_hacs_entity check (entity_registry's
        # platform == "hacs") may set this True.
        url = "https://github.com/esphome/esphome/releases/tag/2026.7.0"
        assert hacs_identity.resolve_identity("update.some_esphome_device", url, "2026.7.0", "2026.6.0") is None

    def test_home_assistant_core_not_misfiled_as_hacs(self):
        # Found by review, 2026-07-22: Core's own release_url matches the
        # generic HACS regex just as readily as a real HACS integration
        # would, so this must be checked by entity_id first, not by shape.
        # Passed-in url is a decoy here (Core's own real release_url attribute
        # is "https://www.home-assistant.io/latest-release-notes/", never a
        # github.com one) -- see test_home_assistant_core_release_url_built
        # below for the actual link Core gets.
        url = "https://www.home-assistant.io/latest-release-notes/"
        identity = hacs_identity.resolve_identity(
            "update.home_assistant_core_update", url, "2026.7.3", "2026.7.2"
        )
        assert identity.category == "home-assistant"
        assert identity.component == "core"
        assert identity.owner_repo is None
        assert identity.from_version == "2026.7.2"
        assert identity.to_version_path == "home-assistant/core/2026.7.3"

    def test_home_assistant_core_release_url_built(self):
        # Core's own release_url attribute is never used (it's always
        # "latest-release-notes", not version-specific -- see the class
        # comment on ResolvedIdentity.release_url and hacs_identity.py's own
        # comment above this branch). Built instead from home-assistant/
        # core's own GitHub releases, verified live (2026-07-31) that every
        # tagged release there -- stable and beta alike -- uses the version
        # string verbatim as its tag, across 4 real releases spanning
        # 2024.1.0 through the 2026.8.0b3 beta.
        identity = hacs_identity.resolve_identity(
            "update.home_assistant_core_update", None, "2026.7.4", "2026.7.3"
        )
        assert identity.release_url == "https://github.com/home-assistant/core/releases/tag/2026.7.4"

    def test_home_assistant_core_beta_release_url_built(self):
        identity = hacs_identity.resolve_identity(
            "update.home_assistant_core_update", None, "2026.8.0b3", "2026.7.4"
        )
        assert identity.release_url == "https://github.com/home-assistant/core/releases/tag/2026.8.0b3"

    def test_home_assistant_core_dev_build_has_no_release_url(self):
        # Dev builds are never tagged on home-assistant/core at all
        # (confirmed live: a 404) -- linking to releases/tag/<dev-version>
        # here would be a broken link, so this is left None instead, same
        # graceful-degradation treatment as an older install_log entry with
        # no captured release_url at all.
        identity = hacs_identity.resolve_identity(
            "update.home_assistant_core_update", None, "2026.8.0.dev20260728", "2026.7.4"
        )
        assert identity.release_url is None

    def test_home_assistant_os_release_url_kept(self):
        url = "https://github.com/home-assistant/operating-system/releases/tag/14.2"
        identity = hacs_identity.resolve_identity(
            "update.home_assistant_operating_system_update", url, "14.2", "13.0"
        )
        assert identity.release_url == url

    def test_home_assistant_supervisor_release_url_kept(self):
        url = "https://github.com/home-assistant/supervisor/releases/tag/2026.07.1"
        identity = hacs_identity.resolve_identity(
            "update.home_assistant_supervisor_update", url, "2026.07.1", "2026.06.1"
        )
        assert identity.release_url == url

    def test_home_assistant_supervisor(self):
        identity = hacs_identity.resolve_identity(
            "update.home_assistant_supervisor_update", None, "2026.07.1", "2026.06.1"
        )
        assert identity.to_version_path == "home-assistant/supervisor/2026.07.1"

    def test_home_assistant_os_uses_latest_version_not_release_url(self):
        # No release_url at all (or one that doesn't match a GitHub shape)
        # still resolves correctly for these three, since the version comes
        # from latest_version directly, not release_url.
        identity = hacs_identity.resolve_identity(
            "update.home_assistant_operating_system_update", None, "v14.2", "13.0"
        )
        assert identity.to_version_path == "home-assistant/os/14.2"

    def test_installed_version_v_prefix_normalized_same_as_latest_version(self):
        # Found by review, 2026-07-24: installed_version most often comes
        # straight off an update entity's own attribute, just as likely to
        # carry a stray "v" prefix as latest_version -- skipping this
        # normalization would silently split what's actually the same jump
        # into two different community-votes entries.
        identity = hacs_identity.resolve_identity(
            "update.home_assistant_operating_system_update", None, "14.2", "v13.0"
        )
        assert identity.from_version == "13.0"

    def test_hacs_entity_uses_latest_version_not_release_urls_own_tag(self):
        # Found live, 2026-07-22 (real bug hit voting on expander-card): a
        # HACS entity's release_url isn't guaranteed to be *for* the exact
        # version this call is about (e.g. it can still point at the
        # newest available release while resolving an older, already-
        # installed History entry) -- latest_version must win, only
        # owner/repo may come from release_url.
        url = "https://github.com/owner/repo/releases/tag/7.1.10"
        identity = hacs_identity.resolve_identity(
            "update.some_integration", url, "7.1.9", "7.1.8", is_hacs_entity=True
        )
        assert identity.owner_repo == "owner/repo"
        assert identity.to_version == "7.1.9"
        assert identity.to_version_path == "hacs/owner/repo/7.1.9"

    def test_unidentifiable_entity(self):
        assert hacs_identity.resolve_identity("update.some_integration", None, "1.2.3", "1.0.0") is None

    def test_device_identity(self):
        # device_manufacturer/device_model are pre-resolved by
        # device_identity.py (needs a real hass, not unit-tested here, see
        # its own docstring), passed through as plain strings.
        identity = hacs_identity.resolve_identity(
            "update.some_zigbee_bulb_firmware",
            None,
            "1.0.4",
            "1.0.3",
            device_manufacturer="IKEA of Sweden",
            device_model="TRADFRI bulb E27",
        )
        assert identity.category == "devices"
        assert identity.manufacturer_model == "IKEA of Sweden/TRADFRI bulb E27"
        assert identity.to_version_path == "devices/IKEA of Sweden/TRADFRI bulb E27/1.0.4"

    def test_app_identity(self):
        identity = hacs_identity.resolve_identity(
            "update.mosquitto_broker_update", None, "6.5.0", "6.4.0", app_slug="core_mosquitto"
        )
        assert identity.category == "apps"
        assert identity.app_slug == "core_mosquitto"
        assert identity.to_version_path == "apps/core_mosquitto/6.5.0"

    def test_home_assistant_checked_before_device_or_app_kwargs(self):
        # A fixed home-assistant entity_id always wins, even if a caller
        # (incorrectly) also passed device/app kwargs alongside it.
        identity = hacs_identity.resolve_identity(
            "update.home_assistant_core_update",
            None,
            "2026.7.3",
            "2026.7.2",
            device_manufacturer="should not be used",
            device_model="should not be used",
        )
        assert identity.category == "home-assistant"

    def test_jump_key_combines_to_version_path_and_from_version(self):
        identity = hacs_identity.resolve_identity(
            "update.some_integration",
            "https://github.com/owner/repo/releases/tag/1.2.3",
            "1.2.3",
            "1.0.0",
            is_hacs_entity=True,
        )
        assert identity.jump_key == "hacs/owner/repo/1.2.3::1.0.0"


class TestCorrectedReleaseUrl:
    def test_core_gets_a_real_version_specific_github_url(self):
        # Not Core's own native release_url ("always latest"), a real
        # per-version github.com/.../releases/tag/<version> one instead.
        assert hacs_identity.corrected_release_url(
            "update.home_assistant_core_update",
            "https://www.home-assistant.io/latest-release-notes/",
            "2026.7.3",
        ) == "https://github.com/home-assistant/core/releases/tag/2026.7.3"

    def test_core_v_prefix_stripped(self):
        assert hacs_identity.corrected_release_url(
            "update.home_assistant_core_update", None, "v2026.7.3"
        ) == "https://github.com/home-assistant/core/releases/tag/2026.7.3"

    def test_core_dev_build_falls_back_to_native(self):
        # Never tagged on GitHub at all -- linking there would be a 404.
        native = "https://www.home-assistant.io/latest-release-notes/"
        assert hacs_identity.corrected_release_url(
            "update.home_assistant_core_update", native, "2026.8.0.dev20260701"
        ) == native

    def test_supervisor_and_os_pass_through_unchanged(self):
        # Their own native release_url is already a real, version-specific
        # GitHub releases URL -- nothing to correct.
        native = "https://github.com/home-assistant/supervisor/releases/tag/2026.07.3"
        assert hacs_identity.corrected_release_url(
            "update.home_assistant_supervisor_update", native, "2026.07.3"
        ) == native

    def test_non_home_assistant_entity_passes_through_unchanged(self):
        native = "https://github.com/owner/repo/releases/tag/1.2.3"
        assert hacs_identity.corrected_release_url("update.some_integration", native, "1.2.3") == native

    def test_none_native_release_url_for_non_core_stays_none(self):
        assert hacs_identity.corrected_release_url("update.some_integration", None, "1.2.3") is None
