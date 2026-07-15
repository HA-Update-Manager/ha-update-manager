# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

Initial project scaffold, plus the first real piece of Phase 0: a single "Update Manager" sensor
showing how many updates are ready to install now, with the per-update breakdown (ready/waiting/
blocked, and why) as an attribute -- not one entity per update, which would mean 100+ near-useless
extra entities on a large instance. No auto-install or rollout-pacing behavior yet.

### Added
- Bare custom_component skeleton (`manifest.json`, `const.py`, `__init__.py`, a single-instance
  confirm-only `config_flow.py`), `hacs.json`, GitHub Actions (`validate.yml`, `hassfest.yaml`,
  `dependabot.yml`), README, LICENSE.
- `semver.py`: strict semver parsing and version-jump classification, deliberately failing (not
  guessing) on anything that isn't strict semver, and treating Home Assistant Core's own calendar
  versioning (e.g. `2026.7.1`) as its own excluded category rather than misreading it as a major
  bump. First test suite (`tests/test_semver.py`).
- `staging.py`: given a version-jump classification and how long the update has existed, decides
  ready/waiting/blocked. Every jump type -- including major/unknown -- has its own independently
  configurable wait (or `None` for "always blocked"); the defaults are patch immediately, minor
  after 7 days, major/unknown always blocked, but nothing is hardcoded: a user can give major or
  unknown a real wait too if they explicitly choose to. Also pure and independently tested
  (`tests/test_staging.py`).
- `sensor.py`: a single summary sensor covering every `update.*` entity, combining both of the
  above per update. "How long has this update existed" comes from a best-effort recorder history
  lookup (same 30-day-lookback pattern already used by previous-state-tracker), falling back to
  "just now" (the conservative choice) when that history isn't available -- and skipped entirely
  for major/unknown jumps, where it wouldn't change the answer anyway, to keep the number of
  recorder queries down on instances with many updates. Only the one update entity that actually
  changed is ever re-queried, not the whole set, and the initial bulk scan at startup is lightly
  staggered rather than firing every lookup at once.
- `rollout.py`: paces a group of devices sharing the same pending update one at a time, with a
  minimum wait between each. Pure queue logic only so far and independently tested
  (`tests/test_rollout.py`) -- grouping devices by model and actually triggering installs isn't
  wired up yet.

- `installable` attribute per update: whether the entity's `supported_features` bitmask includes
  `UpdateEntityFeature.INSTALL` (value `1`). Some update entities (e.g. firmware that must be
  flashed manually) can only report that a newer version exists, with no install action available
  at all -- found via live testing. Doesn't change ready/waiting/blocked (still meaningful for "is
  this a sensible version to move to"), but must gate any future auto-install: never call
  `update.install` on an entity that doesn't support it.
- Options flow: a "profile" screen (Conservative/Balanced/Free/Custom) followed by a details screen
  with all 8 settings (wait days + "always require a manual decision" per jump type) always visible
  and editable, whichever profile was picked -- a profile only pre-fills starting values, it never
  hides anything. Changing options reloads the entry so the new rules take effect immediately.
- `coordinator.py`: the ready/waiting/blocked refresh logic that used to live directly in the sensor
  moved into a shared `UpdateManagerCoordinator`, so it has exactly one owner instead of being
  duplicated once the future panel needs to read it too. The sensor is now a thin, read-only view on
  top of it -- and deliberately stays that way, see below.
- `install_log.py`: records every completed update (entity, old version, new version, when, release
  notes link) to its own `Store` file (`.storage/`), regardless of what triggered the install --
  Update Manager doesn't call `update.install` itself yet, so this is purely observational. Genuinely
  new data, unlike the ready/waiting/blocked status, which is always recomputed and never stored.
- `websocket_api.py`: two read-only commands, `update_manager/updates` and `update_manager/install_log`,
  exposing the coordinator's cache and the install log. This -- not the summary sensor's attributes --
  is meant to be what Phase 2's future panel actually reads from.
- `diagnostics.py`: the same two lists (updates + install log), reachable with a few clicks (Settings ->
  Devices & Services -> Update Manager -> Download diagnostics) -- no browser console needed to check
  that the install log or the status feed is actually working before Phase 2's panel exists.

### Changed
- The summary sensor is a cheap debug view (Developer Tools -> States), not the source of truth or
  the foundation for Phase 2's panel -- that distinction wasn't explicit before this refactor. See
  FUTURE.md's "Entities zijn niet de fundering voor Fase 2's paneel" note for the reasoning. No
  behavior change for the sensor itself.
- Found via live testing: the options flow's wording read as if these settings triggered some
  automatic action ("wait before it counts as ready", "always require a manual decision"), which
  doesn't exist -- Update Manager doesn't call `update.install` or take any action on an update
  yet, anywhere. Reworded to make clear these settings only change the ready/waiting/needs-review
  label shown on the summary sensor; you still install updates yourself, the normal Home Assistant
  way.

### Fixed
- Found via live testing on a real instance (194 update entities): every already-up-to-date entity
  (the normal, steady-state case for nearly all of them) was being counted as "blocked", because
  `sensor.py` compared `installed_version`/`latest_version` itself instead of first checking the
  update entity's own `state` ("on" = update available, "off" = up to date, always exactly one of
  the two). Equal versions classified as "unknown" fed straight into "blocked", so on a real
  instance almost everything showed up as blocked rather than just the entities with a genuine
  pending update.
