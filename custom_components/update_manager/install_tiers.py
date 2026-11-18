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
  add-on/card updates, the overwhelming majority. A Marketplace-backed
  entity specifically is still the one exception running the other
  direction: Core's own install waits briefly for one already installing
  (its own download/extract shares Core's process, the exact same risk as
  "zha_firmware" below), via rollout_manager.py's own
  _pending_marketplace_entity, capped rather than open-ended (see that
  constant's own comment). The "safe" entity itself is still never held
  back by anything, only Core's own install defers to it, briefly.
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
  whenever that ends up happening). This install step shares no resource
  with Core/Supervisor/a ZHA transfer (a background write to the
  inactive partition, not a process restart), and the one thing that
  genuinely could disrupt something (the reboot itself) is never
  something this gate, or HA's own job conditions on Core/Supervisor
  (confirmed against their real source too), can protect against anyway,
  since it happens whenever the user gets to it, decoupled from any
  update.install call entirely. Exempt like "safe"/"firmware".
- "host_firmware": specifically RaspberryPiFirmwareUpdateEntity (its own
  _attr_translation_key, "rpi_firmware"; both the standalone
  raspberry_pi integration and homeassistant_yellow's own CM4/CM5 module
  use this exact class). Same reasoning as "os" above, confirmed against
  its own real source (homeassistant_hardware/util.py): the install call
  itself only writes the new firmware (delegated to Supervisor, the same
  bootloader-EEPROM path OS's own RAUC write already uses, not anything
  inside Core's own process), the actual effect only takes hold after the
  next reboot, and Supervisor raises its own REBOOT_REQUIRED issue the
  same way it does for OS. An earlier version of this module isolated
  this tier from every other firmware flash out of caution for a
  hardware-level EEPROM conflict that never actually appears in the real
  source, and that caution couldn't even have covered every
  installation's own host firmware consistently in the first place (only
  Raspberry Pi/Yellow are detected here at all). Exempt like "os".
- "supervisor": restarts only its own container, not Home Assistant Core
  itself (confirmed against supervisor's own real source, supervisor.py's
  own update(): the sys_core.stop() it calls there is Supervisor's own
  internal lifecycle orchestrator, a same-named but unrelated class to
  HomeAssistantCore, confirmed by reading both. Core's own container is
  never touched unless it was already missing when the new Supervisor
  comes back up). The one remaining real risk this could still pose
  (disrupting another Supervisor-managed add-on install already running)
  was never actually covered by this tier mechanism anyway, since an
  ordinary add-on update is "safe"-tier, exempt from this gate regardless
  of what tier Supervisor itself sits at. What Supervisor genuinely does
  require, confirmed against Core's/OS's own real job conditions
  (JobCondition.SUPERVISOR_UPDATED on both): itself being current before
  either one can even attempt to update at all, a real, enforced
  dependency rather than a "least disruptive first" heuristic, held to
  on our own side too via rollout_manager.py's own
  _pending_supervisor_entity, which holds a Core/OS request back
  whenever Supervisor itself still has a real update sitting there
  uninstalled (dispatching either one anyway would just fail outright
  against that same job condition). That check is independent of this
  tier mechanism entirely, so "supervisor" needs no gated-tier membership
  of its own for it to keep working. Exempt like "os"/"host_firmware".
- "zha_firmware": device_class == "firmware" *and* the device is on a
  ZHA-managed Zigbee network specifically (see zigbee.py's own
  is_zha_entity), split out from the plain "firmware" tier above:
  unlike every other firmware-class update listed there, ZHA is a
  built-in part of Home Assistant Core's own process, not a separate
  add-on or the device's own onboard flash, so a Core restart lands on it
  exactly the same way it lands on any other in-process state, a real
  risk of cutting an in-flight OTA transfer off mid-air. Zigbee2MQTT (its
  own separate add-on process) is unaffected by this and stays in
  "firmware". This split is ZHA-specific, not "Zigbee" in general. Two
  ZHA transfers at once aren't a concern this tier needs to cover either:
  rollout_manager.py's own separate Zigbee-network pacing already serializes
  any two Zigbee devices on the same network, ZHA or Zigbee2MQTT alike,
  regardless of tier.
- "core": restarts Home Assistant Core's whole process. The only other
  tier genuinely at risk from something else running at the same moment
  is "zha_firmware" above (both share Core's own process). After
  reconsidering every other pairing against its real, confirmed
  behavior, none of "os"/"host_firmware"/"supervisor" turned out to
  share a real resource with Core, or with each other, so "core" and
  "zha_firmware" are the only two tiers FIRST_GATED_RANK below actually
  needs to cover. A Marketplace-backed entity shares that same resource
  too, despite sitting in "safe", see that tier's own entry above for why
  it's handled as its own, separate, capped check instead of a third
  member of this gated group.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .coordinator import home_assistant_component_for_entity
from .zigbee import is_zha_entity

TIER_ORDER = ("safe", "firmware", "os", "host_firmware", "supervisor", "zha_firmware", "core")
TIER_RANK = {tier: rank for rank, tier in enumerate(TIER_ORDER)}

# "zha_firmware" and "core" are the only two tiers left in the gated
# group, the only pair confirmed to genuinely share a resource (Core's
# own process). See each tier's own entry above for the full reasoning
# behind every other tier, including "os"/"host_firmware"/"supervisor",
# landing below this cutoff instead, exempt from ever being held back by
# rollout_manager.py's tier gate, however much other work is running.
# "os"/"core" still wait on Supervisor specifically when it has a real
# update pending, and any two Zigbee devices on the same network still
# pace one at a time, but both of those are separate mechanisms
# (_pending_supervisor_entity, the Zigbee-network queue), not this one.
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
