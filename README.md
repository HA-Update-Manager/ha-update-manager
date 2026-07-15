[![Made for Home Assistant](https://img.shields.io/badge/Made%20for-Home%20Assistant-blue?style=for-the-badge&logo=homeassistant)](https://www.home-assistant.io/)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Update Manager: Home Assistant helper integration

> [!NOTE]
> Very early, pre-alpha stage. Phase 0 (below) mostly works and has been tested against a real
> instance, but this repository isn't ready to be installed by end users yet -- no release has
> been cut, and there's no auto-install or rollout-pacing (also below) at all yet.

Update Manager helps you decide when a Home Assistant update is worth installing. It never installs
anything on its own: it only tells you, per pending update, whether it's worth a look right now.

## Planned scope

This project is being built in phases, starting with the parts that need no external service at
all:

- **Phase 0 (mostly done)**: local, semver-aware staging rules. Patch updates show up as "ready"
  immediately; minor updates wait a bit first; major updates (and anything that isn't clearly
  semver, which is common, not an edge case) always need a manual look. Every wait -- including for
  major/unrecognized versions -- is fully configurable, not hardcoded. An install log keeps track of
  what was installed and when, with release notes where available. Not yet built: pacing a group of
  devices sharing the same firmware update one at a time (`rollout.py`'s queue logic exists and is
  tested, but isn't wired to real devices yet -- it only makes sense once Update Manager can act on
  an update at all, see Phase 3).
- **Phase 1**: a community backend (plain git + GitHub Actions, no hosted server) where people can
  vote on whether a given release was problem-free.
- **Phase 2 (in progress)**: a Home Assistant sidebar panel. Currently: read-only Updates and
  Historie tabs, and an Instellingen tab for the Phase 0 staging rules. Later: the community verdict
  from Phase 1, and a vote button.
- **Phase 3** (direction decided, not yet designed): actually installing updates -- the end goal is
  for Update Manager to manage updates, which eventually means automating installation too, not just
  advising. This needs its own careful design (which categories, cooldown periods, backup
  requirements, confirmation UX, fail-closed behavior) before any of it is built.

Showing whether an update is worth a look and actually automating its installation are two separate
features: the former is useful entirely on its own, even before the latter exists.

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
