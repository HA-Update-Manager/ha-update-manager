# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

Initial project scaffold, plus the first real piece of Phase 0: every `update.*` entity now gets a
matching sensor classifying its pending version jump (patch/minor/major/unknown). No staging,
wait-time, or auto-install behavior yet -- this only shows the classification.

### Added
- Bare custom_component skeleton (`manifest.json`, `const.py`, `__init__.py`, a single-instance
  confirm-only `config_flow.py`), `hacs.json`, GitHub Actions (`validate.yml`, `hassfest.yaml`,
  `dependabot.yml`), README, LICENSE.
- `semver.py`: strict semver parsing and version-jump classification, deliberately failing (not
  guessing) on anything that isn't strict semver, and treating Home Assistant Core's own calendar
  versioning (e.g. `2026.7.1`) as its own excluded category rather than misreading it as a major
  bump. First test suite (`tests/test_semver.py`).
- `sensor.py`: auto-discovers every `update.*` entity and creates a "version jump" sensor for it,
  using `semver.py` against that entity's `installed_version`/`latest_version` attributes.
