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


UpdateManagerConfigEntry = ConfigEntry[UpdateManagerData]
