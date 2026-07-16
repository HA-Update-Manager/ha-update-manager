# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

Initial project scaffold, plus the first real piece of Phase 0: a single "Update Manager" sensor
showing how many updates are ready to install now, with the per-update breakdown (ready/waiting/
blocked, and why) as an attribute -- not one entity per update, which would mean 100+ near-useless
extra entities on a large instance. Auto-install now exists too (see below), fully opt-in and off
by default; device-firmware rollout-pacing does not yet.

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
- **Auto-install** (niveau 3, see FUTURE.md's "Auto-install (niveau 3): ontwerp" for the full design
  discussion this came out of):
  - `announcer.py`: pure decision logic (`decide_action`) for what should happen right now to an
    eligible update -- announce, execute, remove a stale/cancelled announcement, or nothing.
    Independently tested (`tests/test_announcer.py`), same pure-logic-first pattern as
    `semver.py`/`staging.py`/`rollout.py`.
  - `install_manager.py`: wires that into real behaviour. Every 5 minutes, checks every update
    against the new per-jump-type `*_auto_install` settings; once eligible, starts a cancellable
    countdown (`announce_hours`, default 24) instead of installing immediately. Only once that
    countdown elapses uncancelled does it call `update.install` -- always with `backup=true` when
    the entity's `supported_features` includes `UpdateEntityFeature.BACKUP` (not user-configurable,
    a pure safety measure with no real downside). Persisted (`Store`, survives restarts), so does the
    "user explicitly cancelled this exact target version" state, which stays quiet for that version
    without needing a settings change.
  - **Fully opt-in, no hardcoded exceptions except Core/Supervisor/HAOS**: each jump type (including
    major/unrecognized) gets its own `*_auto_install` toggle, off by default in every profile --
    consistent with Fase 0's "nothing hardcoded" staging rules, just extended to actually installing.
    Core/Supervisor/HAOS is the one deliberate, hardcoded exception (impact = the whole HA instance,
    not one integration/add-on/device) -- always manual, not instelbaar, on purpose.
  - **No HA Repair issue for the announcement** -- considered and explicitly rejected: "repair"
    implies something's broken, this is just an announcement. Instead: a `persistent_notification`
    (the right semantic: "look at this", not "something's wrong") linking to the panel, where the
    actual pending-install list and its cancel button live (Updates tab, "Geplande installaties").
    The announcement cleans itself up (no forced manual dismiss) once it's no longer relevant: the
    install happened, the update disappeared/changed, or the setting was turned back off -- only a
    genuine user cancellation needs an actual click.
  - Deliberately not wired up yet for device firmware specifically: rollout-pacing (`rollout.py`)
    needs to exist first so Zigbee/Z-Wave/Bluetooth updates don't all land on a shared mesh at once
    -- HACS integrations/add-ons have no such constraint, so they come first.
  - `update_manager/updates` now includes a `pending_install` field per entity (`to_version`/
    `execute_at`, or `null`), and a new `update_manager/cancel_pending_install` command. Diagnostics
    also expose the pending list.
- Found via live testing: with the 4 new auto-install fields, the settings form grew to 13 flat
  fields plus the profile picker in one long list -- "super onoverzichtelijk". Regrouped into one
  collapsed-by-default `ha-form` expandable section per jump type (`type: "expandable"`,
  `flatten: true` keeps the data flat, no schema restructuring needed), so only the category you
  actually want to change is open at once. Field copy was also just plain wrong on its own: "dagen
  voor 'klaar'" explained nothing outside the context of the Updates-tab status column it refers to.
  Every field now has a `computeHelper` sentence explaining what it actually does, and since each
  section's title already says which category ("Patch (kleine bugfix)" etc.), the fields inside it no
  longer repeat that prefix on every single line.
- Found via live testing right after the above: "Altijd handmatig beoordelen" and "Automatisch
  installeren" could both be turned on for the same jump type at once -- blocked meant status never
  reached "ready" at all, so auto-install silently had nothing to act on, with no indication why.
  These were never really two independent settings, they're the same "what happens once ready" choice
  FUTURE.md's three-levels model already describes. Replaced `*_blocked`/`*_auto_install` (2 booleans)
  with a single `*_mode` field per jump type (`manual`/`shown`/`auto`) everywhere: `const.py`,
  `coordinator.py`'s `rules_from_options`, `install_manager.py`'s `auto_install_rules_from_options`,
  the `save_settings` websocket schema, and the panel's select field -- structurally impossible to
  contradict now, not just documented as a footgun. No migration needed (still pre-release, per the
  README's own note, no real settings exist to carry over).
- Found via live testing, the same day: the 3-way mode field above wasn't really about "judging"
  anything, and treating "unknown version type" as needing its own no-wait special case felt
  unnecessary once said out loud. Simplified again, back to two independent settings per jump type:
  `*_wait_days` (unchanged) and `*_auto_install` (a plain boolean again) -- but this time *without*
  reintroducing the earlier contradiction, because there's no more "always blocked" state to conflict
  with it. `staging.py` itself is untouched (it still fully supports an always-blocked wait of `None`),
  only the settings model no longer ever produces one. "Unknown" gets a conservative default wait
  instead (90/60/14 days for Conservative/Balanced/Free) rather than being blocked forever by default.
- The Updates tab's status labels: "Klaar" became "Voldoet aan voorwaarden" (found via direct user
  feedback: nothing is actually "done" at that point, the wording implied otherwise) and "Handmatig"
  became "Afgeraden", reserved for a future signal (e.g. a community verdict) since nothing in today's
  local rules produces it anymore.
- The Updates tab now defaults to sorting safest first: green, then orange, then red, and oldest
  first within each group (requested directly by the user, so the longest-standing, most "proven"
  update always sinks to the top of its group). Sorting alphabetically on the status emoji itself
  would actually sort backwards (red's codepoint sorts before orange's, before green's), so a hidden
  numeric column combines status priority with the raw timestamp into one sortable key, and
  `ha-data-table`'s `valueColumn` points the visible Status column at it.
- **Renamed patch/minor/major/unknown to small/medium/big everywhere** (`semver.py`, `staging.py`,
  `const.py`, `coordinator.py`, `announcer.py`, `install_manager.py`, `websocket_api.py`, the whole
  panel): a deliberately generic scale, not semver's own vocabulary, so any version scheme's own
  classifier can map onto it -- semver, calendar versioning, and now git commit hashes (below) each
  have their own notion of "klein". There's no separate "unknown" category anymore either: anything
  `classify_version_size` can't confidently place (not strict semver, not calendar-shaped, not a
  recognizable commit hash, a downgrade, or an identical/re-announced version) is just "big", the same
  conservative-by-default treatment "unknown" used to get -- one less settings category to configure.
- `semver.py` now recognizes git commit hashes (e.g. HACS tracking a repo by commit instead of a
  release tag) as their own case: "medium" when both sides are commit-shaped, since there's no
  ordering signal at all (you can't tell which of two hashes came first without consulting git
  history), so it's deliberately not "small" but a recognized, deliberate tracking choice rather than
  truly unknown. Matches hex strings of 6 to 40 characters (git's own abbreviation length isn't fixed
  at 7, it auto-expands to stay unique in a larger repo) with at least one a-f letter, so a plain
  numeric build counter isn't mistaken for a hash just because every digit is also valid hex.
- `is_ha_core_calendar_version` renamed to `is_calendar_version`: it was always a pure shape check
  (year.month.patch), not specific to HA Core's own entity -- any integration/device could use the
  same scheme, the old name implied an exclusivity that was never actually true.
- Settings redesigned again: found via live testing that repeating "Wachttijd"/"Automatisch
  installeren" across three separate collapsed sections still felt repetitive even after the mode
  simplification above. Replaced the three `ha-form` sections with one compact table (a row per size,
  column headers explaining the two settings once instead of three times) -- plain native
  number/checkbox inputs, not `ha-form`, since a table doesn't map onto `ha-form`'s schema model
  cleanly. "Wachttijd" was also renamed to "Uitsteltermijn" (direct user feedback).
- Home Assistant Core/Supervisor/OS's own update entities are now actually recognized in code (the
  "always manual, never auto-install regardless of settings" rule was, until now, only a design
  decision in FUTURE.md, not enforced anywhere). Identified by their real, stable `unique_id`
  (`home_assistant_core_version_latest`/`home_assistant_supervisor_version_latest`/
  `home_assistant_os_version_latest`, verified against `homeassistant/components/hassio/entity.py`
  and `const.py`), not by guessing an `entity_id` string or checking `platform == "hassio"` (which
  would also catch regular add-ons, a different, actually-configurable category). A new
  `auto_install_excluded` field per update (coordinator cache, `update_manager/updates`, diagnostics)
  gates `install_manager.py` before it ever auto-installs anything -- the shown size/status stay fully
  informational either way, only the auto-install gate is hardcoded. The Updates tab now also shows
  "(altijd handmatig)" next to these three specifically.

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
- `classify_version_jump` now classifies HA Core's own calendar versions (year.month.patch) as
  "patch" (same year+month) or "minor" (year and/or month differs) instead of always "unknown" --
  but deliberately never "major": a year rollover (2026.12.x -> 2027.1.0) is just another month
  boundary in HA Core's own release cadence, not a signal of more risk than any other monthly
  release. Only kicks in when *both* sides are calendar-shaped; a mixed comparison (one side
  calendar, one not) stays "unknown", same as before.

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
- Found via live testing: some pending updates never showed up on the Updates tab at all.
  `coordinator.py`'s `async_start()` ran its initial bulk scan (which can easily take several
  seconds on a large instance -- 100+ update entities, staggered on purpose) *before* subscribing to
  `state_changed`. Any update entity whose very first state appeared in that window (e.g. an
  integration that finishes its own setup later than ours) was in neither the scan's snapshot nor
  caught by a not-yet-attached listener, and so was silently missed until something else about it
  changed later. Subscribe first, then scan -- the worst case is now a harmless redundant refresh,
  not a permanent gap.
- `homeassistant.bus.async_listen`'s `run_immediately` argument is deprecated (breaks in HA 2025.5,
  found via a real log warning) -- removed; no functional change; our listener was already a plain
  `@callback`, which is what that argument used to opt into anyway.
- Found via code review: `coordinator.py` only recomputed an update's status/remaining time when
  `state_changed` fired (or a settings save), never purely because time itself had passed. An update
  entity that reached "waiting" and then never changed state again (common -- most integrations only
  touch `installed_version`/`latest_version`, not on a timer) stayed "waiting" forever, even once its
  configured wait had long since elapsed -- so it would never become "ready" and `install_manager.py`
  would never announce/auto-install it either. Added a 15-minute periodic recheck (`_recompute_all`,
  shared with `async_update_rules`) alongside the existing `state_changed` trigger.
- Found via code review: `install_manager.py` called `update.install` with `blocking=False`, which
  meant (a) a user's cancel could race the actual install and appear to succeed even though the
  install had already been dispatched, and (b) the surrounding `try`/`except` could only ever catch
  pre-dispatch errors, never a genuine install failure -- those vanished silently instead of being
  logged with Update Manager's own context. Fixed by finalizing the pending-install removal *before*
  dispatching the install (so a cancel arriving in that window is simply too late, not a race), and
  running the actual `update.install` call as its own task with `blocking=True` so a real failure
  raises and gets logged there, without blocking the 5-minute tick from evaluating other entities.
- Found via code review: the persistent_notification announcing a pending auto-install was always
  Dutch text regardless of `hass.config.language`, inconsistent with the panel (already fixed to
  follow `hass.language`). Now follows the same convention, EN/NL.
