[![Made for Home Assistant](https://img.shields.io/badge/Made%20for-Home%20Assistant-blue?style=for-the-badge&logo=homeassistant)](https://www.home-assistant.io/)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Update Manager: Home Assistant helper integration

Update Manager helps you decide when to install a Home Assistant update, and can optionally install
it for you. Waiting a bit before installing isn't caution for its own sake: it gives a broken release
time to be noticed and fixed before you commit to it.

---

## Features

* **Staging rules:** updates are grouped by how big a jump they are, each with its own configurable
  waiting period before it counts as ready.
* **Auto-install, opt-in:** announced first with a cancellable countdown before anything installs,
  with an automatic backup when supported. Core, Supervisor, and OS updates always stay manual.
* **Master pause switch:** pauses all of Update Manager's automatic behavior at once, also available
  as a real switch entity for dashboards and automations.
* **Hide postponed updates:** optionally keeps still-waiting updates out of Home Assistant's own
  sidebar update count until they're actually ready.
* **Zigbee rollout pacing:** identical Zigbee devices (ZHA or Zigbee2MQTT) update one at a time instead
  of all at once, protecting mesh stability.
* **Community verdict and voting:** link your GitHub account to see whether other users found a
  specific update version healthy or problematic, and cast your own vote from the Updates or History
  tab. Covers HACS integrations, Home Assistant Core/Supervisor/OS, real vendor Zigbee device firmware,
  and Supervisor add-ons.
* **Sidebar panel:** an Updates tab with live install progress and an "update all" button, a History
  tab with changelogs, and an autosaving Settings tab.

---

## Installation

This integration isn't in the HACS default store yet, so add it as a custom repository.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HA-Update-Manager&repository=ha-update-manager&category=integration)

1. In HACS, add `https://github.com/HA-Update-Manager/ha-update-manager` as a custom repository
   (category: Integration).
2. Install "Update Manager" and restart Home Assistant.

---

## Configuration

[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=update_manager)

1. Navigate to **Settings > Devices & Services**, add **Update Manager**, and confirm the
   single-instance setup.
2. Open the **Update Manager** entry in the sidebar to review updates and adjust the rules (Settings
   tab).
