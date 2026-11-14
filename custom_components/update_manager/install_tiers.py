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
- "firmware": device_class == "firmware" (HA's own UpdateDeviceClass enum),
  minus ZHA (see "zha_firmware" below). Dozens of real integrations use
  this device_class (WLED, Shelly, ESPHome, UniFi, Zigbee2MQTT, Z-Wave JS,
  Matter Server, and more, confirmed via a real code search) -- ordinary
  peripheral/networked device firmware, safe alongside each other *and*
  alongside "safe"-tier installs too (direct user feedback, 2026-08-24:
  nothing about an unrelated HACS integration/card install threatens an
  over-the-air device firmware flash, so gating one behind the other was
  needless waiting, not real safety). Every one of these runs its own
  flash from its own separate process -- an add-on's own container
  (Zigbee2MQTT, Z-Wave JS, Matter Server) or the device's own onboard
  flash reached directly over the network (WLED, Shelly, ESPHome, UniFi)
  -- genuinely unaffected by whatever else Home Assistant's own process is
  doing at the same moment, Core's own restart included. FIRST_GATED_RANK
  below is what actually excuses this tier (and "safe") from ever being
  held back by anything.
- "os": the whole-host update itself doesn't actually reboot anything
  (confirmed against supervisor's own real source, OSManager.update(): it
  installs the RAUC bundle, then raises a REBOOT_REQUIRED issue with an
  EXECUTE_REBOOT suggestion instead of calling sys_host.control.reboot()
  itself, leaving the real reboot to a separate, user-triggered action,
  whenever that ends up happening). Reconsidered 2026-11-14, direct user
  feedback: this install step shares no resource with Core/Supervisor/a
  ZHA transfer (a background write to the inactive partition, not a
  process restart), and the one thing that genuinely could disrupt
  something (the reboot itself) is never something this gate -- or HA's
  own job conditions on Core/Supervisor, confirmed against their real
  source too -- can protect against anyway, since it happens whenever the
  user gets to it, decoupled from any update.install call entirely.
  Keeping it in the gated group bought no real safety, only needless
  waiting, so it now sits here instead, exempt like "safe"/"firmware".
- "zha_firmware": device_class == "firmware" *and* the device is on a
  ZHA-managed Zigbee network specifically (see zigbee.py's own
  is_zha_entity) -- split out from the plain "firmware" tier above, direct
  user feedback, 2026-11-13: unlike every other firmware-class update
  listed there, ZHA is a built-in part of Home Assistant Core's own
  process, not a separate add-on or the device's own onboard flash, so a
  Core restart lands on it exactly the same way it lands on any other
  in-process state -- not "another install happening to run at the same
  moment" (the needless-waiting case "firmware" above is exempted from),
  a real risk of cutting an in-flight OTA transfer off mid-air. Zigbee2MQTT
  (its own separate add-on process) is unaffected by this and stays in
  "firmware" -- this split is ZHA-specific, not "Zigbee" in general.
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
  supervisor/homeassistant/core.py and supervisor/os/manager.py) -- a real,
  enforced dependency, not just a "least disruptive first" heuristic, and
  now additionally held to on our own side too: rollout_manager.py's own
  tier gate (_pending_supervisor_entity) holds a Core/OS request back
  whenever Supervisor itself still has a real update sitting there
  uninstalled, direct user feedback, 2026-11-14 -- dispatching either one
  anyway would just fail outright against that same job condition, a
  predictable failure this project can hold back instead of letting
  happen.
- "core": restarts Home Assistant Core's whole process.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .coordinator import home_assistant_component_for_entity
from .zigbee import is_zha_entity

TIER_ORDER = ("safe", "firmware", "os", "zha_firmware", "host_firmware", "supervisor", "core")
TIER_RANK = {tier: rank for rank, tier in enumerate(TIER_ORDER)}

# Only "zha_firmware" and up are genuinely at risk from something else
# running at the same time (a ZHA OTA transfer cut off mid-air by Core's
# own restart, the host's own EEPROM programmer, the Supervisor container,
# Core's own process); see the tier list above for why each of those
# genuinely needs to wait its turn. "safe"/"firmware"/"os" were never a
# real risk to each other (see "os"'s own entry above for why it moved
# here, 2026-11-14), so rollout_manager.py's tier gate exempts all three
# from ever being held back, however much other work is running -- "os"
# still waits on Supervisor specifically, just via its own dedicated
# _pending_supervisor_entity check, not this tier mechanism.
FIRST_GATED_RANK = TIER_RANK["zha_firmware"]


def tier_for_entity(hass: HomeAssistant, entity_id: str) -> str:
    """Server-side only -- no client-side JS counterpart exists to keep in
    sync with (an earlier version of this docstring claimed one,
    update-manager-panel.js's own updateAllTierFor, which no longer exists
    in that file; stale, corrected 2026-11-13). The actual gate this feeds
    (rollout_manager.py) is server-side and must reach the same verdict
    regardless of which panel/client happens to be connected, or none at
    all (auto-install), which is why this lives here rather than being
    derived from anything the frontend already computed. Core/Supervisor/OS
    detection itself is coordinator.py's own, not reimplemented here (see
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
        return "zha_firmware" if is_zha_entity(hass, entity_id) else "firmware"
    return "safe"
