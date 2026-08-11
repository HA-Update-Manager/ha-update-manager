"""Which disruption tier an update entity belongs to, for rollout_manager.py's
own tier-gate (see that module's own docstring for why this exists at all):
pressing "Update all" (or any combination of individual Install clicks close
together) used to fire every entity's own update.install at once, including
Home Assistant Core's own -- which restarts Core entirely, killing whatever
else was still mid-install at that exact moment.

Confirmed against home-assistant/core's own real source (hassio/update.py,
homeassistant_hardware/update.py, raspberry_pi/update.py,
homeassistant_yellow/update.py) and home-assistant/supervisor's own real
source (supervisor/homeassistant/core.py, supervisor/os/manager.py -- both
require SUPERVISOR_UPDATED as a hard job condition), not guessed:

- "safe": everything else, never blocked by anything -- ordinary integration/
  add-on/card updates, the overwhelming majority.
- "firmware": device_class == "firmware" (HA's own UpdateDeviceClass enum).
  Dozens of real integrations use this (WLED, Shelly, ESPHome, UniFi, ZHA/
  Z-Wave JS/Matter radios, and more, confirmed via a real code search) --
  ordinary peripheral/networked device firmware, safe alongside each other,
  still held back from anything below.
- "host_firmware": specifically RaspberryPiFirmwareUpdateEntity (its own
  _attr_translation_key, "rpi_firmware" -- both the standalone raspberry_pi
  integration and homeassistant_yellow's own CM4/CM5 module use this exact
  class). The literal board Home Assistant itself runs on, not a peripheral
  -- kept isolated from every *other* firmware flash too, not just
  Supervisor/Core/OS, since a hardware-level hiccup on the host's own EEPROM
  programmer while something else is also mid-flash isn't something either
  HA's own source or ours can rule out with confidence. Installing it never
  triggers an automatic reboot on its own (confirmed against its own real
  source: "The new firmware only runs after the *next* reboot"), so this
  isolation is about the flash itself, not a restart.
- "supervisor": restarts only its own container, not Home Assistant Core
  itself (confirmed: SupervisorSupervisorUpdateEntity's own docstring) --
  still enough to disrupt any other Supervisor-managed (add-on) install
  running at the same moment. Also the one every Core/OS update requires be
  current first (JobCondition.SUPERVISOR_UPDATED, confirmed in both
  supervisor/homeassistant/core.py and supervisor/os/manager.py), so this
  isn't just a "least disruptive first" heuristic, it's a real, enforced
  dependency.
- "core": restarts Home Assistant Core's whole process.
- "os": reboots the entire host, taking Core and Supervisor down with it
  regardless -- always last.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .coordinator import home_assistant_component_for_entity

TIER_ORDER = ("safe", "firmware", "host_firmware", "supervisor", "core", "os")
TIER_RANK = {tier: rank for rank, tier in enumerate(TIER_ORDER)}


def tier_for_entity(hass: HomeAssistant, entity_id: str) -> str:
    """Same detection rules as update-manager-panel.js's own
    updateAllTierFor (JS/Python can't literally share this, kept in sync by
    hand) -- checked here too, not just client-side, since the actual gate
    this feeds (rollout_manager.py) is server-side and must reach the same
    verdict regardless of which panel/client happens to be connected, or
    none at all (auto-install). Core/Supervisor/OS detection itself is
    coordinator.py's own, not reimplemented here (see
    home_assistant_component_for_entity's own docstring) -- its returned
    "core"/"supervisor"/"os" strings are exactly this module's own tier
    names, no translation needed."""
    entry = er.async_get(hass).async_get(entity_id)
    component = home_assistant_component_for_entity(hass, entity_id, entry=entry)
    if component is not None:
        return component
    if entry is not None and entry.translation_key == "rpi_firmware":
        return "host_firmware"
    state = hass.states.get(entity_id)
    if state is not None and state.attributes.get("device_class") == "firmware":
        return "firmware"
    return "safe"
