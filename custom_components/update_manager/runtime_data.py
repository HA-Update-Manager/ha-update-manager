"""The single dataclass entry.runtime_data holds for this integration's one
config entry (config_flow enforces single-instance, see websocket_api.py's
own docstring) -- replaces hass.data[DOMAIN], closing quality_scale.yaml's
own runtime-data gap. A separate module, not defined in __init__.py itself:
every platform (sensor.py/switch.py/diagnostics.py) and websocket_api.py all
need this same type for their own annotations, and __init__.py already
imports from websocket_api, so defining it there would be circular.
"""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .community_verdict import CommunityVerdictManager
from .coordinator import UpdateManagerCoordinator
from .github_auth import GitHubAuthManager
from .install_log import InstallLog
from .install_manager import InstallManager
from .my_votes import MyVotesManager
from .rollout_manager import RolloutManager
from .staging_skip import StagingSkipManager


@dataclass
class UpdateManagerData:
    coordinator: UpdateManagerCoordinator
    install_log: InstallLog
    install_manager: InstallManager
    staging_skip_manager: StagingSkipManager
    rollout_manager: RolloutManager
    community_verdict_manager: CommunityVerdictManager
    github_auth_manager: GitHubAuthManager
    my_votes_manager: MyVotesManager
    # manifest.json's own version (str(Integration.version)), fetched once in
    # __init__.py's async_setup_entry -- device.py's own device_info reads
    # this for the device info page's own "Software version" (sw_version),
    # direct user feedback, 2026-08-07: "Ik mis bij service info ook de
    # versie van de integratie". Not re-fetched on every device_info() call
    # (unlike panel.py's own always-fresh read, see that function's own
    # docstring for why *it* deliberately doesn't cache): device_info() is
    # a plain sync function, called from several entities' own __init__
    # (sensor.py/switch.py), not just this async setup -- caching once here
    # keeps it sync-callable everywhere without threading an async fetch
    # through every entity constructor, and a version only actually changes
    # across a reload/restart anyway, exactly when this cache is rebuilt.
    integration_version: str


UpdateManagerConfigEntry = ConfigEntry[UpdateManagerData]
