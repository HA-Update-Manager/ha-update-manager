# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

**Adds community voting**
Link your GitHub account (a new Community card in Settings, via device flow: a short code entered on
GitHub's own site, no password shared with Update Manager, no separate app to install), then vote on a
specific version from either the Updates tab or the History tab. The two read differently on purpose:
a still-*pending* update (Updates tab) only offers reporting an issue that's knowable before installing
at all, straight from the release notes (a breaking change, a dev/pre-release build, requiring a newer
HA version), no "healthy" button, since nobody's actually run it yet; an *installed* (or downgraded-to)
version, opened from the History tab, gets the full healthy/problematic vote, with "problematic" adding
two more, only-after-running reasons ("broken functionality", "other"). Every vote dialog asks which
version it's about in plain language ("How's version X treating you?"), and a successful vote shows an
immediate, optimistic confirmation rather than waiting on community-votes' own processing to reflect it.
Covers every update category community-votes has a schema for: HACS (only entities actually installed
through HACS itself, verified against its own entity registry, not just anything whose release_url
happens to look like a GitHub link -- a real, live mix-up hit with an ESPHome device otherwise), Home
Assistant Core/Supervisor/OS, real vendor device firmware (Zigbee, via ZHA or Zigbee2MQTT, regardless
of which one manages the device), and Supervisor add-ons. Self-compiled/user-flashed firmware (ESPHome,
Tasmota) is deliberately never identifiable this way: two installs' "same board" can run completely
different, incomparable firmware there. Anything not covered gets a clear "can't be identified yet"
message (or no vote controls at all) instead of a silent failure.

**Adds Zigbee/ZHA rollout pacing**
Firmware installs across identical Zigbee devices (ZHA or Zigbee2MQTT, same model and target
version) are now paced one at a time instead of all at once, protecting mesh stability. A queue only
ever appears once a second device from the same group is asked to install while one is already in
flight; there's no manual override to jump the line, whether from the dialog's Install button,
auto-install, or Update All. Survives a restart: an install genuinely in flight gets re-dispatched, one
that actually finished while Home Assistant was down advances immediately.

**Adds a community verdict badge**
Pending updates for identifiable entities (see community voting above for which ones) now show a badge
with the community's healthy/problematic vote counts on the Updates tab. Sourced from the new
[HA-Update-Manager/community-votes](https://github.com/HA-Update-Manager/community-votes) repo. No
settings toggle: always on, nothing is ever sent just by looking.

**Adds a trusted-voter auto-install override**
A new "Trusted voters" setting (Auto-update card, a list of GitHub usernames) lets someone whose
judgement you trust more than your own size-based rules override auto-install for a specific version,
in either direction: if any of them rated it healthy, it auto-installs regardless of your own
wait/toggle rules for that size; if any of them rated it problematic, auto-install is blocked outright,
even if your own rules would otherwise allow it. If more than one is listed and they disagree on the
same version, a problematic vote always wins. A still-pending update blocked this way now says so
directly, in its own dialog ("Auto-install held back: @username reported this version as
problematic."), and every History entry now shows a full audit trail once expanded: when the update
became available, when it was announced (if at all), when it was actually installed, and how (manual,
your own rules, or a trusted vote, naming who).

**Redesigns the Settings and History pages**
Settings now groups the master switch and visibility toggle into one General card up top, the
Small/Medium/Big rules collapse by default, and repeated or oversized explanatory text has been
trimmed throughout. The Auto-update card (announcement notice, always-manual entities, trusted voters)
is now always visible, not only once some size's own auto-install toggle is on. History (both the tab
and the per-entity dialog) groups entries into relative date sections, and every entry is now fully
expandable, showing its changelog (if any), a release-page link (if any), and the audit-trail facts
above -- regardless of whether it has a changelog to show at all.

**Fixes updates losing their wait progress after a restart**
`available_since` is now persisted instead of recomputed from a recorder lookup on every refresh, so
a restart, a brief unavailability, or an integration reload can no longer quietly reset how long an
update has been waiting.

**Adds an Enabled switch entity**
The master pause switch is now also a real `switch` entity, not only a Settings-page toggle, so it can
be controlled from a dashboard or an automation. Both stay in sync with each other.

### Added
- GitHub account linking (`github_auth.py`): a "Link GitHub account" button in Settings using OAuth
  device flow, no client secret involved anywhere.
- Community voting (`community_vote.py`, `vote_issue_body.py`, `device_identity.py`): vote buttons in
  the update dialog's own Community section, scoped to the exact version being viewed (a pending
  update's own latest version, or a specific History entry's), submitted as a community-votes issue
  using the linked account. Identity resolution now covers all four community-votes categories:
  HACS/Core/Supervisor/OS (HACS gated on the entity actually being HACS-owned via entity_registry, not
  release_url's shape alone), plus real vendor Zigbee device firmware (manufacturer/model, via
  ZHA/Zigbee2MQTT) and Supervisor add-ons (via the add-on's own device-registry slug).
- Zigbee/ZHA rollout pacing (`zigbee.py`, `rollout_manager.py`): one-at-a-time device install queues,
  surfaced on the Updates tab as their own "queue" section per network, reactive only (no queue shown
  for a lone device).
- A community verdict badge (`community_verdict.py`, `hacs_identity.py`): shows healthy/problematic
  vote counts from the new community-votes repo on the Updates tab, for any identifiable pending
  update.
- A `switch.update_manager_enabled`-style entity mirroring the master pause switch, staying in sync
  with the Settings page's own toggle either way.
- A distinct "Update failed" notification when an auto-install actually fails, instead of only a log
  entry with nothing user-visible at all.
- Recognizes your own past vote (`my_votes.py`): the verdict line reads "You [and N others] reported
  this version as..." instead of a bare count when it matches your own vote, and re-voting on a version
  you already rated now shows "Vote updated to..." instead of the usual first-time confirmation.
- A trusted-voter auto-install override (`CONF_TRUSTED_VOTERS`, `effective_auto_install_state` in
  `announcer.py`, aggregated in `community_verdict.py`): a configurable list of GitHub usernames whose
  own vote on a specific version overrides your own size-based rules for that exact version, healthy
  overriding an otherwise-off/still-waiting auto-install, problematic blocking one that would otherwise
  go ahead. Any trusted problematic vote wins outright over any trusted healthy one among the same list.
- A full audit trail on every History entry (`install_log.py`'s new `auto_install_reason`,
  `trusted_voter_usernames`, `announced_at`, `available_since` fields): expanding an entry now shows
  when it became available, when it was announced (if it ever was), when it was actually installed, and
  whether that install was manual, driven by your own rules, or a trusted vote (naming who).
- An "Auto-install held back" alert on a still-pending update's own dialog, shown whenever a trusted
  voter rated that exact version problematic, naming them directly instead of leaving the block
  unexplained.

### Changed
- "Update all" now dispatches each entity through the same `update_manager/install` path as the
  dialog's own Install button, instead of one raw batched `update.install` service call, so it respects
  the rollout queue too.
- The "balanced" profile's default wait days: medium 7 → 1, big 30 → 3 (small stays 0).
- "Hide postponed updates" now defaults to on instead of off.
- Settings page: merged the master-switch and visibility cards into one "General" card, made the
  per-size sections collapsible by default, and trimmed several oversized or repeated explanations.
  The Small/Medium/Big size descriptions now show the real current year/month in their calendar-version
  examples instead of a fixed date.
- History tab and dialog: entries are grouped into cards with a consistent width/grid matching the
  other two tabs, and every entry is now fully expandable (changelog if any, release-page link if any,
  and the audit-trail facts above), instead of a mix of separate small links, toggles, and one
  external-navigation-only case for a changelog-less entry.
- The auto-install "this was automatic" indicator is now icon-only with a tooltip, instead of an icon
  plus a repeated text label on every row; the tooltip itself now names the specific reason (your own
  rules, or a trusted vote from whoever) instead of a generic "Automatically updated".
- The Settings page's Community verdict section spacing/proportions were tightened, and its "not yet
  rated" copy now reads "by others" instead of "by the community" (direct user feedback: read more
  naturally once your own past vote is recognized separately).

### Fixed
- Identity resolution for a HACS vote used whatever version was embedded in `release_url`'s own tag
  instead of the version the vote/verdict lookup was actually for, so a vote cast for one version could
  silently land under a different one whenever `release_url` didn't happen to match (found live: a
  HACS entity's release_url isn't guaranteed to be *for* the exact version being voted on, e.g. it can
  still point at the newest available release while resolving an older, already-installed History
  entry). The requested version now always wins; `release_url` is only ever used to find the owner/repo.
- After a successful vote, the button's own spinner kept spinning forever instead of settling: verified
  against `ha-progress-button`'s real source, `actionSuccess()`/`actionError()` only ever show a
  temporary 2-second checkmark/alert, they never reset `progress` themselves, and every other caller of
  this pattern happened to rebuild/replace its own button within that window so nobody had noticed.
- The dialog's Community section's "hidden until identifiable" logic never actually took effect:
  `.dialog-community-section`'s own CSS rule (`display: flex`) had the exact same specificity as the
  browser's built-in `[hidden]` rule and came later in the cascade, so it silently won regardless of the
  element's own `hidden` attribute. Every unidentifiable entity (e.g. an ESPHome device, self-flashed
  firmware never intended to be votable) kept showing the "not yet rated" placeholder text forever, with
  no vote controls underneath it -- looking identifiable without actually being so. Same underlying
  cause for a stray gap of empty space in front of the verdict text once a real verdict *did* exist:
  `ha-svg-icon`'s own shadow-DOM styles set `display: inline-flex` unconditionally too, so its `hidden`
  attribute never collapsed it either, just left an empty, icon-sized box sitting there. Fixed by
  scoping the section's own CSS to `:not([hidden])` and by only ever creating the icon element once
  there's a real badge to show, instead of relying on `hidden` for either of them.
- The sidebar panel only ever registered itself once per Home Assistant process: the panel's own
  cache-busting `module_url` (a hash of the JS file's current contents, added specifically so browsers
  don't keep serving a stale cached copy after an edit) was captured on that first registration and
  never recomputed afterward, since `panel_custom`'s own registration helper raises if called again for
  the same URL. Every JS change made after that first registration kept being served from the browser's
  cache regardless of a reload or even a hard refresh, only a full Home Assistant restart ever picked
  it up. Registers directly against `frontend.async_register_built_in_panel` with `update=True` now, so
  a plain integration reload (not just a full restart) refreshes it.
- An auto-install already in flight (dispatched, not yet resolved) could be evaluated again on the
  next tick and dispatched a second time, occasionally misattributing a genuine auto-install as manual
  in the install log when the redundant attempt's own failure cleared the original attempt's record.
- The `InstallManager`'s own periodic tick had no lock against overlapping runs, unlike
  `staging_skip.py`'s equivalent, which could very rarely duplicate an announcement.
- The sidebar panel showed a back arrow instead of the menu (hamburger) icon, since `mainPage` was
  never set on `hass-tabs-subpage`.
- The community verdict lookup only matched `release_url`'s canonical `releases/tag/<tag>` shape,
  missing the shorter `releases/<tag>` form some update entities (including this project's own) use, and
  didn't normalize a leading `v` in the tag, so a real vote cast without the prefix never matched.
- A "not yet rated" result was cached until the entity's own version changed, the same as
  `available_since`, but unlike that fact, a vote count can keep climbing while a device is still sitting
  on the same pending version: the cache is now time-based (an hour) instead.
- A queued (not yet dispatched) Zigbee rollout device had its pending-install record cleared without
  ever being marked in flight, so it was silently re-announced with a fresh notification on every
  subsequent cycle until its actual turn in the queue came.
- A failed install for a queued Zigbee device left the whole rollout group stuck forever (every sibling
  device behind it blocked too), with no failure notification anywhere; it's now caught, logged, and
  surfaces the same "Update failed" notification a plain auto-install failure already gets.
- An exception while checking the Zigbee rollout queue during auto-install could abort the whole
  evaluation tick before its dirty state was saved; now caught and logged per entity instead.
- The community verdict lookup filed every entity under the `hacs` category regardless of what kind of
  update it actually was, so a Home Assistant Core/Supervisor/OS update's real GitHub release URL would
  have been looked up under the wrong path instead of the category community-votes reserves for it.
- The community verdict badge/dialog section had no disclaimer text anywhere in the UI, only in the
  separate community-votes repo's own README.
- The community verdict lookup was awaited inline during each entity's staging-status computation,
  serializing a real network round-trip into Update Manager's own startup scan; it's now fetched in the
  background and patched in once resolved, and its own cache write no longer hits disk on every single
  lookup.

## [0.1.0] - 2026-07-17

Update Manager's first release: helps you decide *when* to install a Home Assistant update, and can
optionally handle the installing for you. Waiting a bit before installing isn't caution for its own
sake; it gives a broken release time to be noticed and fixed before you commit to it.

**Staging rules**: updates are grouped by how big a jump they are (a small bugfix vs. a bigger,
possibly breaking change), each with its own configurable waiting period before it counts as ready.

**Auto-install**: fully opt-in, off by default. Once eligible, an update isn't installed instantly;
it's announced first with a cancellable countdown, and a backup is taken automatically when
supported. A master switch pauses all of this at once if you ever need to, without touching any
other setting.

**Sidebar panel**: an Updates tab (with live install progress, an "update all" button, and an option
to hide still-postponed updates from Home Assistant's own sidebar count), a History tab with
changelogs for everything installed, and a Settings tab that autosaves as you edit.

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
- **Master pause switch**: one toggle at the top of the Instellingen tab (`enabled`, on by default)
  pauses every autonomous action Update Manager itself takes -- announcing, executing an auto-install,
  and hiding postponed updates (below) -- without touching any other setting. `coordinator.py` owns
  the single shared flag (`master_enabled`); `install_manager.py` and `staging_skip.py` both read it
  directly rather than each keeping an independent copy, so the two can't silently disagree about
  whether Update Manager is paused. Turning it back on resumes an in-flight auto-install announcement
  from the exact same `execute_at` it already had, instead of restarting a fresh `announce_hours`
  countdown -- `announcer.py`'s `decide_action` treats the pause as "freeze in place" (untouched, not
  removed), a deliberate change after seeing an active countdown jump forward a full day the moment
  the switch was toggled off and on again.
- **Hide postponed updates from Home Assistant's own update count**: opt-in (Instellingen tab). While
  an update is still "waiting" (Fase 0's staging, not yet ready), Update Manager marks it skipped via
  HA's own real `update.skip` service, so it disappears from the sidebar's update count and any other
  native "updates available" surface, not just from this panel -- automatically un-skipped again once
  it actually becomes ready. The one real risk this exists to avoid: HA's `skipped_version` has no
  memory of *why* it was set, so blindly un-skipping everything seen skipped would just as happily
  clear a skip the user set themselves. Every skip/unskip this feature performs is recorded in its own
  persisted store first, and it only ever acts on an entity/version pair it recorded there itself --
  the panel's own "Skipped" group only ever shows a real, user-initiated skip; a postponed update this
  feature is hiding still just reads as "Postponed". A new `hidden_by_update_manager` field per update
  (summary sensor, `update_manager/updates`) makes that distinction directly inspectable instead of
  only reachable by reading the internal `is_own_skip` logic.
- **Live install progress**: the detail dialog shows a real progress bar (percentage-based when the
  entity reports one, otherwise indeterminate) while an update is actually installing, in the same
  spot HA's own more-info dialog puts it, with the status text saying "Installing…" and the
  Skip/Cancel/Clear skipped buttons disabled for the duration, all updating live as the entity's own
  state streams in -- not just when the dialog happens to be open, the Updates list itself shows the
  same spinner/percentage ring in place of its trailing chevron, matching `/config/updates` row for
  row. Installing a postponed or skipped update (a new `update_manager/install` command) clears that
  status immediately rather than waiting for the install to actually finish.
- **"Update all" button** on the Ready-to-update group, matching `/config/updates`'s own
  implementation exactly: a single batched `update.install` call covering every entity in the group
  that isn't already installing (not a loop of individual calls -- HA's own services already support
  a list target for `entity_id`), same disabled condition and error-message entity-id-to-friendly-name
  substitution as the real one.
- Settings now autosave (debounced) instead of requiring a separate Save button -- every edit is
  written a moment after you stop typing/toggling, with a toast confirming it saved.
- Countdowns throughout the panel (auto-install timing, postponement) now read as an absolute clock
  time ("Today 14:06", "Tomorrow", a short date further out) instead of a relative "in 4 hours" --
  respects both `hass.language` (not the browser's own OS locale, which can disagree) and the user's
  own Home Assistant time-format preference (`hass.locale.time_format`: 12h/24h/system/language),
  matching HA's own `useAmPm()` logic.
- "Install" renamed to "Update" throughout the panel (buttons, dialog, translations), matching HA's
  own real update-entity button wording, verified against source rather than guessed.
- History dialog entries are now their own card per install, showing whether it was an automatic or
  manual install, with the short release summary shown inline and the full changelog behind a
  collapsed-by-default expansion panel -- the flat list this replaced showed neither of those things.

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
- The detail dialog no longer closes itself after Cancel/Skip/Clear skipped -- it reloads and rebuilds
  in place instead, so the confirmation that the action actually happened stays visible instead of
  being hidden behind a closed dialog (found live: it looked like nothing happened until a manual
  page refresh).

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
- Found via live testing: the tab bar never showed which tab was actually active when opening the
  panel on its bare URL. `set route`'s own redirect to the Updates tab corrected the visible browser
  URL and the panel's own internal tab state, but never corrected the `route` object itself handed
  down to `hass-tabs-subpage` -- its own active-tab matching compares `route.prefix + route.path`
  against each tab's full path, so the still-empty `path` never matched anything. Two earlier fix
  attempts (forcing a fresh `route` object reference, an extra re-push after load) didn't touch this
  and so didn't help; correcting the stored path itself on that same redirect did.
- Found via live testing: the panel's own JS file was served from a fixed URL with no cache-busting,
  and HA's static-path registration for it already sends long-lived cache headers -- the browser could
  keep serving an old cached copy indefinitely after any code change, with no way to tell short of a
  hard refresh. `module_url` now includes a short hash of the file's own current content, so any
  change to it automatically produces a new URL.
