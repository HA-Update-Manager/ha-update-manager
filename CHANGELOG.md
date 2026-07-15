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
  ready/waiting/blocked (patch ready immediately, minor after a configurable wait, major/unknown
  always blocked pending a manual decision). Also pure and independently tested
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
