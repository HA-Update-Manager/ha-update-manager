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
- `available_since` in each update's cache entry (visible via diagnostics/the sensor's `updates`
  attribute): when the recorder lookup thinks the current `latest_version` first appeared. Previously
  only usable indirectly (through `status`/`remaining_seconds`); exposing it directly makes the
  recorder lookup itself something you can actually check by eye.
- `release_summary` and full `release_notes` in each install log entry, alongside `release_url` --
  found via live testing that `release_url` alone is often `null` even when an entity's more-info
  dialog does show notes: the full text isn't a plain state attribute, it's fetched on demand via
  the update entity's own `async_release_notes()` (the same thing HA's own more-info dialog and its
  `update/release_notes` websocket command call), so the install log now does the same, best-effort.
- **Update Manager's own sidebar panel** (Phase 2, see FUTURE.md), registered via `panel.py`
  (`panel_custom`) and served as a single plain JS file (`panel/update-manager-panel.js`, no build
  step, same convention as this project family's Lovelace cards) -- three tabs:
  - **Updates**: read-only table of every pending update (status, version jump, available-since,
    whether it's even installable), from `update_manager/updates`.
  - **Historie**: the install log (old -> new version, when, release notes), from
    `update_manager/install_log`.
  - **Instellingen**: replaces the options flow -- same profile picker + 8 staging-rule fields
    (via `ha-form`, same pattern already used by this project family's card editors), reading/saving
    through two new websocket commands, `update_manager/get_settings` and
    `update_manager/save_settings`. Saving still just writes the config entry's options, exactly what
    the options flow did, so nothing about how rules are stored changed, only how they're edited.
  - Deliberately no install button anywhere: Update Manager still doesn't call `update.install` in
    any form, see FUTURE.md's "Volgorde-correctie" note on why that's a separate, later discussion.
  - Page chrome is `hass-tabs-subpage`, the same layout component `/config/devices` and HACS's own
    panel use -- real per-tab URLs under `/update-manager/...` (own back/refresh/direct-link
    behavior), not just in-memory tab state, per direct user feedback that a hand-rolled toolbar/tabs
    felt inconsistent with the rest of HA.
  - Updates/Historie use `ha-data-table`, the same table component `/config/devices`,
    `/config/entities` and HACS's own panel use -- real sorting/filtering/column widths, not a
    hand-rolled approximation, per direct user feedback that the tables didn't look like HA's own.
    The whole row is clickable and opens HA's real more-info dialog for that entity
    (`hass-more-info` event, plus `clickable`/`row-click`, both built into `ha-data-table` already)
    -- so working with a pending update here feels like working with the actual entity, not a
    separate copy of its data. Entity names drop a trailing "Update" (baked into most update
    entities' own `friendly_name`, e.g. "Matter Server Update") since it's redundant on a page
    that's entirely about updates. One accepted limitation: a per-row entity icon, a colored status
    badge, and a clickable release-notes link all need a `template` returning a real Lit
    `TemplateResult` to render inside `ha-data-table` -- not achievable without importing Lit, which
    every other file in this project deliberately avoids (see `TODO-CLAUDE.md`); plain text for now.
  - `installed_version`/`latest_version` added to the coordinator's per-update cache (previously only
    the version-jump classification was exposed, not the actual versions).
  - Instellingen is one `ha-form` covering both the profile picker (a select *selector*, not a plain
    `<select>`) and the 8 detail fields, and the whole thing sits in an `ha-card` with a
    `ha-progress-button` save action -- the same building blocks (and `.card-content`/`.card-actions`
    layout) `/config/general`'s own settings cards use, verified against that page's actual source.
    Text throughout the panel uses the same `--ha-font-*` typography tokens this project family's
    other cards already migrated to, instead of arbitrary pixel values.
  - Found via live testing: the Updates/Historie tables looked like a floating card rather than the
    page itself -- `ha-data-table` already has its own default border (see `ha-data-table.ts`), and
    the surrounding centered/padded wrapper (meant for the settings card) turned that into a boxed-in
    look `/config/devices` doesn't have there. Tables now fill the content area edge-to-edge; only the
    settings card keeps the centered/padded treatment.
  - `available_since`/`installed_at` show as relative time ("3 dagen geleden") instead of an absolute
    timestamp -- the same idea as HA's own `ha-relative-time`, computed once per render rather than
    ticking up live since that component can't be embedded in an `ha-data-table` cell either (same
    Lit-template limitation as the icon/badge/link).
  - "Patch"/"Minor"/"Major"/"Onbekend" (both on the Updates tab and the 8 settings fields) now include
    a plain-language explanation ("Patch (kleine bugfix)", "Major (grote wijziging, mogelijk
    breaking)", etc.) -- semver terms mean nothing to someone who doesn't already know semver, found
    via direct user feedback on exactly the page where that distinction is supposed to help.

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

### Removed
- The options flow (profile + 8-field details screen): superseded by the panel's Instellingen tab
  above, per FUTURE.md's "Tussenstap" note -- that screen was always meant to move once a real panel
  existed, not to keep existing alongside it as a second settings surface. `config_flow.py` is back
  to just the minimal single-instance confirmation step.

### Fixed
- Found via live testing on a real instance (194 update entities): every already-up-to-date entity
  (the normal, steady-state case for nearly all of them) was being counted as "blocked", because
  `sensor.py` compared `installed_version`/`latest_version` itself instead of first checking the
  update entity's own `state` ("on" = update available, "off" = up to date, always exactly one of
  the two). Equal versions classified as "unknown" fed straight into "blocked", so on a real
  instance almost everything showed up as blocked rather than just the entities with a genuine
  pending update.
- Found via live testing: clicking a panel tab navigated to the site root (e.g. `/updates`) instead
  of staying under the panel (`/update-manager/updates`). `hass-tabs-subpage` matches/links tabs
  using the *full* absolute path (`route.prefix + route.path`), not a path relative to the panel --
  `tabs[].path` was wrongly given just the relative tail.
