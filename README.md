[![Made for Home Assistant](https://img.shields.io/badge/Made%20for-Home%20Assistant-blue?style=for-the-badge&logo=homeassistant)](https://www.home-assistant.io/)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Update Manager: Home Assistant helper integration

> [!NOTE]
> Very early, pre-alpha stage. This is the initial project scaffold; the actual staging logic
> described below isn't built yet.

Update Manager helps you decide when a Home Assistant update is safe to install, and optionally
automates that decision.

## Planned scope

This project is being built in phases, starting with the parts that need no external service at
all:

- **Phase 0 (in progress)**: local, semver-aware staging rules. Patch updates can show up (or
  install) immediately; minor updates wait a bit first; major updates (and anything that isn't
  clearly semver, which is common, not an edge case) always require a manual click. Device
  firmware (Zigbee/Z-Wave/Bluetooth in particular) is rolled out one device at a time rather than
  all at once. An install log keeps track of what was installed and when.
- **Phase 1**: a community backend (plain git + GitHub Actions, no hosted server) where people can
  vote on whether a given release was problem-free.
- **Phase 2**: a Home Assistant panel that shows that community verdict and lets you vote.
- **Phase 3** (maybe never): feed the community verdict into Phase 0's local rules, as an optional,
  strictly additional gate on top of them.

Showing whether an update is considered problem-free and actually automating its installation are
two separate features: the former is useful entirely on its own, even if automation is never built.

## Installation

Not yet published to HACS; this repository isn't ready to be installed by end users yet.

## Configuration

Nothing to configure yet. Setting up the integration currently just confirms it's installed.

## Contributing

Ideas, feedback, and PRs are welcome once there's more here to react to. This project intentionally
lives under its own [HA-Update-Manager](https://github.com/HA-Update-Manager) organization rather
than a personal account, precisely so it isn't tied to one person long-term.
