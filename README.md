[![Made for Home Assistant](https://img.shields.io/badge/Made%20for-Home%20Assistant-blue?style=for-the-badge&logo=homeassistant)](https://www.home-assistant.io/)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Update Manager: Home Assistant helper integration

> [!NOTE]
> Early stage. Phase 0 and auto-install (below) work and have been tested against a real instance;
> device-firmware rollout-pacing and the community layer (Phase 1-3) aren't built yet.

Update Manager helps you decide when to install a Home Assistant update, and can optionally install
it for you -- never silently: an eligible update is always announced first, with time to cancel,
before anything actually happens.

## Planned scope

This project is being built in phases, starting with the parts that need no external service at
all:

- **Phase 0 (mostly done)**: local, semver-aware staging rules. Patch updates show up as "ready"
  immediately; minor updates wait a bit first; major updates (and anything that isn't clearly
  semver, which is common, not an edge case) always need a manual look. Every wait -- including for
  major/unrecognized versions -- is fully configurable, not hardcoded. An install log keeps track of
  what was installed and when, with release notes where available. Not yet built: pacing a group of
  devices sharing the same firmware update one at a time (`rollout.py`'s queue logic exists and is
  tested, but isn't wired to real devices yet).
- **Auto-install (mostly done)**: per version-jump type (patch/minor/major/unrecognized), optionally
  let Update Manager actually install an update once it's "ready" -- off by default everywhere, one
  independent on/off switch per type, no hardcoded exceptions (major updates can be auto-installed
  too, if you explicitly turn that on). The only hard exception is Core/Supervisor/HAOS, which always
  stays manual. Nothing installs the instant it's eligible: it's announced first (a configurable,
  cancellable wait, default 24 hours), visible and cancellable on the panel's Updates tab, with a
  heads-up notification. A backup is requested automatically when the entity supports it. A single
  master switch pauses all of this (and the postponed-update-hiding below) at once, without touching
  any other setting; resuming continues an in-flight countdown from where it left off. Not yet wired
  up for device firmware specifically -- that needs rollout-pacing (above) first, so Zigbee/Z-Wave/
  Bluetooth updates don't all land on a shared mesh at once.
- **Hiding postponed updates from Home Assistant's own update count (mostly done)**: opt-in. While an
  update is still postponed, Update Manager marks it skipped via HA's own real `update.skip` service,
  so it disappears from the sidebar's update count until it's actually ready -- automatically
  un-skipped again at that point. Never touches a skip you set yourself for your own reason: only a
  genuine, user-initiated skip ever shows as "Skipped" on the panel.
- **Phase 1**: a community backend (plain git + GitHub Actions, no hosted server) where people can
  vote on whether a given release was problem-free.
- **Phase 2 (in progress)**: a Home Assistant sidebar panel. Currently: Updates (with live install
  progress and an "update all" button) and Historie tabs, and a settings tab for the staging/
  auto-install rules (autosaving, no separate Save button). Later: the community verdict from Phase
  1, and a vote button.
- **Phase 3** (mostly not needed anymore): feeding the community verdict into the local rules as an
  extra, optional gate on top of auto-install -- see FUTURE.md for the parts (a fixed cooldown, a
  quorum requirement) not yet decided.

Showing whether an update is worth a look and actually installing it are two separate features: the
former is useful entirely on its own, even for someone who never turns auto-install on.

## Installation

Not yet in the HACS default store. Add this repository as a custom repository in HACS
(Integration), or install the [latest release](https://github.com/HA-Update-Manager/ha-update-manager/releases)
manually under `custom_components/update_manager`.

## Configuration

Confirm the single-instance setup, then open the **Update Manager** entry in the Home Assistant
sidebar to review pending updates, browse the install history, and adjust the staging rules
(Instellingen tab) -- there's nothing to configure during setup itself.

## Contributing

Ideas, feedback, and PRs are welcome once there's more here to react to. This project intentionally
lives under its own [HA-Update-Manager](https://github.com/HA-Update-Manager) organization rather
than a personal account, precisely so it isn't tied to one person long-term.
