[![Made for Home Assistant](https://img.shields.io/badge/Made%20for-Home%20Assistant-blue?style=for-the-badge&logo=homeassistant)](https://www.home-assistant.io/)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Update Manager: Home Assistant helper integration

Update Manager helps you decide when to install a Home Assistant update, and can optionally install
it for you. Waiting a bit before installing isn't caution for its own sake: it gives a broken release
time to be noticed and fixed before you commit to it.

---

## Features

* **Staging rules:** every pending update is grouped by how big a jump it is (a small bugfix vs. a
  bigger, possibly breaking change), each with its own configurable waiting period before it counts
  as ready. You decide the wait per category; nothing is a fixed rule you can't change.
* **Auto-install, fully opt-in:** turn it on per category if you want Update Manager to install a
  ready update for you. Nothing installs the instant it's eligible: it's announced first with a
  cancellable countdown and a heads-up notification, and a backup is taken automatically when the
  entity supports it. Home Assistant's own Core, Supervisor, and OS updates always stay manual, no
  matter what.
* **Master pause switch:** pauses all of Update Manager's own automatic behavior at once, without
  touching any other setting; resuming continues an in-flight countdown from where it left off.
* **Hide postponed updates from Home Assistant's own update count:** opt-in. While an update is still
  waiting, Update Manager can mark it skipped via Home Assistant's own real skip mechanism, so it
  disappears from the sidebar's update count until it's actually ready, automatically un-skipping it
  again at that point. Never touches a skip you set yourself for your own reason.
* **A sidebar panel:** an Updates tab with live install progress and an "update all" button, a
  History tab logging what was installed and when with changelogs attached, and a Settings tab that
  autosaves as you edit.

---

## Installation

This integration isn't in the HACS default store yet, so add it as a custom repository.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HA-Update-Manager&repository=ha-update-manager&category=integration)

1. In HACS, add `HA-Update-Manager/ha-update-manager` as a custom repository (category: Integration).
2. Install "Update Manager" and restart Home Assistant.

---

## Configuration

[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=update_manager)

1. Navigate to **Settings > Devices & Services**.
2. Click **Add Integration** and search for **Update Manager**.
3. Confirm the single-instance setup; there's nothing to configure during setup itself.
4. Open the **Update Manager** entry in the Home Assistant sidebar to review pending updates, browse
   the install history, and adjust the staging/auto-install rules (Settings tab).

---

## Removal

1. Navigate to **Settings > Devices & Services**.
2. Find **Update Manager** and click it.
3. Click the trash-can icon, then confirm.

This also clears any pending auto-install announcements and postponed-update skips it was tracking;
the updates themselves are unaffected.

---

## Known limitations

- Device-firmware updates (Zigbee, Z-Wave, Bluetooth) aren't paced one at a time yet, so auto-install
  treats them the same as any other update category.
- No community layer yet: there's no way to see or contribute a crowd-sourced verdict on whether a
  given release was problem-free.

---

## Contributing

Ideas, feedback, and PRs are welcome. This project intentionally lives under its own
[HA-Update-Manager](https://github.com/HA-Update-Manager) organization rather than a personal account,
precisely so it isn't tied to one person long-term.
