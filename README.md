[![Made for Home Assistant](https://img.shields.io/badge/Made%20for-Home%20Assistant-blue?style=for-the-badge&logo=homeassistant)](https://www.home-assistant.io/)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Update Manager: Home Assistant helper integration

> [!NOTE]
> Very early, pre-alpha stage. Phase 0 and auto-install (below) mostly work and have been tested
> against a real instance, but this repository isn't ready to be installed by end users yet -- no
> release has been cut, and device-firmware rollout-pacing isn't wired up yet (also below).

Update Manager helps you decide when a Home Assistant update is worth installing, and can optionally
install it for you -- never silently: an eligible update is always announced first, with time to
cancel, before anything actually happens.

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
  heads-up notification. A backup is requested automatically when the entity supports it. Not yet
  wired up for device firmware specifically -- that needs rollout-pacing (above) first, so Zigbee/
  Z-Wave/Bluetooth updates don't all land on a shared mesh at once.
- **Phase 1**: a community backend (plain git + GitHub Actions, no hosted server) where people can
  vote on whether a given release was problem-free.
- **Phase 2 (in progress)**: a Home Assistant sidebar panel. Currently: Updates (incl. any pending
  auto-installs) and Historie tabs, and an Instellingen tab for the staging/auto-install rules. Later:
  the community verdict from Phase 1, and a vote button.
- **Phase 3** (mostly not needed anymore): feeding the community verdict into the local rules as an
  extra, optional gate on top of auto-install -- see FUTURE.md for the parts (a fixed cooldown, a
  quorum requirement) not yet decided.

Showing whether an update is worth a look and actually installing it are two separate features: the
former is useful entirely on its own, even for someone who never turns auto-install on.

## Installation

Not yet published to HACS; this repository isn't ready to be installed by end users yet.

## Configuration

Confirm the single-instance setup, then open the **Update Manager** entry in the Home Assistant
sidebar to review pending updates, browse the install history, and adjust the staging rules
(Instellingen tab) -- there's nothing to configure during setup itself.

## Contributing

Ideas, feedback, and PRs are welcome once there's more here to react to. This project intentionally
lives under its own [HA-Update-Manager](https://github.com/HA-Update-Manager) organization rather
than a personal account, precisely so it isn't tied to one person long-term.
