"""Shared DeviceInfo for Update Manager's own entities.

A single virtual device (DeviceEntryType.SERVICE -- this is a pure helper
integration with no physical hardware of its own), so every entity groups
onto one device page instead of floating free in the entity list, direct
user feedback, 2026-08-07: "Nu heeft de integratie slechts entities. Moet
dat niet onder een virtual device komen te hangen?"

__init__.py's own async_setup_entry registers this exact device (via
device_registry.async_get_or_create, unpacking this same function's
return value) before any platform is set up; every entity then attaches
to it via its own device_info property, calling this function again --
one definition, so the identifiers/name can never drift between the two.
Single-instance integration (config_flow enforces it, see
websocket_api.py's own docstring), so entry.entry_id alone is already a
stable, unique identifier -- no separate device-level id of our own to
invent or persist."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN
from .panel import PANEL_URL_PATH
from .runtime_data import UpdateManagerConfigEntry


def device_info(entry: UpdateManagerConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Update Manager",
        entry_type=DeviceEntryType.SERVICE,
        # manufacturer/sw_version -- direct user feedback, 2026-08-07: "Ik
        # mis bij service info ook de versie bijvoorbeeld van de
        # integratie." Confirmed against real core source,
        # homeassistant/components/backup/entity.py (another
        # DeviceEntryType.SERVICE device): it sets manufacturer="Home
        # Assistant"/model="Home Assistant Backup"/sw_version=HA_VERSION.
        # We're not core, so "Home Assistant" as manufacturer would be
        # misleading -- "Update Manager" itself instead, same
        # self-referential convention this project's own sibling
        # ha-last-time-tracker already uses (manufacturer="Last Time
        # Tracker"). No separate `model`: unlike last_time_tracker (one
        # device per "topic", model distinguishes the kind), this is a
        # single-instance integration with only ever one device, so a
        # second field just repeating "Update Manager" wouldn't add
        # anything. integration_version is entry.runtime_data's own cached
        # str(Integration.version) (see runtime_data.py's own docstring
        # for why this is cached once rather than fetched fresh here) --
        # entry.runtime_data is always already set by the time this
        # function runs, both from __init__.py's own device-registration
        # call right after it's assigned, and every entity's own __init__
        # further below that.
        manufacturer="Update Manager",
        sw_version=entry.runtime_data.integration_version,
        # The device info page's own "Visit" link -- direct user feedback,
        # 2026-08-07. `homeassistant://<path>` is HA's own scheme for
        # linking configuration_url at an internal frontend path instead of
        # an external device/service's own web UI (confirmed against the
        # same backup/entity.py source above:
        # `configuration_url="homeassistant://config/backup"`, no leading
        # slash after the scheme). Points at the Updates tab specifically
        # (not the panel's bare root), the same page install_manager.py's
        # own pending-install notifications already link to.
        configuration_url=f"homeassistant://{PANEL_URL_PATH}/updates",
    )
