# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [0.5.1] - 2026-08-01

**Vote issues now link to the exact release being voted on**
Every vote submitted to community-votes includes a real, working link to the exact release it's about (a new "Release" field), for hacs integrations, Home Assistant OS/Supervisor, and Home Assistant Core alike. No more guessing which release a vote was actually referring to.

**A "you voted" state that got stuck now fixes itself**
Deleting your own vote directly on community-votes used to leave the panel permanently showing "you voted", with no way to vote again. It now notices within a few minutes and lets you vote again.

**Also in this release:**
- A stale "Restart of Home Assistant required" alert no longer lingers in History long after the restart it warned about already happened.
- A couple of small spacing fixes around History's changelog/release-link section.
- Marking your own release as healthy now says so plainly in the confirmation toast, instead of a generic message that read as if the vote had vanished.
- The panel's own JavaScript file is no longer read with a blocking call on every setup/reload, found during this integration's own [HACS default-repo submission review](https://github.com/hacs/default/pull/9584#pullrequestreview-4834751826).

### Added
- A vote issue now always includes a working link to the exact release being voted on (a new "Release" field), not just when you happen to fill in the optional "Issue or changelog link" field yourself: hacs entries and Home Assistant OS/Supervisor reuse their own real `release_url` (install_log's own snapshot for a History vote, the entity's live state for a still-pending one, never a stale/wrong version). Home Assistant Core doesn't have a usable one of its own (its `release_url` attribute is a fixed "latest release notes" page, not tied to any specific version), so its link is built instead from home-assistant/core's own GitHub releases, verified live against 4 real releases (stable and beta) spanning 2024.1.0 through the current beta: every one uses the version string verbatim as its tag. A dev build isn't tagged there at all, so those get no link rather than a broken one. "Release" has no counterpart in community-votes' own vote.yml, safe anyway since that repo's process-vote.yml only ever reads specific known fields back out by name and leaves anything else untouched; unlike "Owner/repo" or "To version", which get split/used verbatim to build the per-version storage path and can't safely carry anything extra.

### Fixed
- **The History tab could permanently show a red "Restart of Home Assistant required" alert on an
  already-completed install**, direct user feedback after seeing it on this integration's own update
  entry. `release_summary` is meant as a short, durable blurb (that's how HA Core's own update entity uses
  it), but HACS-managed entities repurpose the same attribute for something else entirely -- confirmed
  against HACS's own `update.py` source: it's just `repository.pending_restart` rendered as an HTML
  snippet, true only for the brief window right after an install, before HA gets restarted. Freezing that
  into History at install time (when it's almost always still true) meant it kept showing as if still
  outstanding long after the restart it warned about had already happened. History no longer has this
  fallback at all; the real, durable `release_notes` changelog is unaffected. The live pending-update view
  (where this attribute is actually accurate, read fresh off the entity each time) is unaffected too.
- A History entry's own changelog/release-link block ran straight into the "History" heading below it
  (in the pending-update dialog) with no divider between them -- direct user feedback.
- A History entry with neither a changelog nor a release link showed one trailing divider too many below
  its Community section, with nothing left for it to separate -- direct user feedback, screenshot. That
  divider is now only added when there's actually a changelog or release link following it.
- Deleting your own vote directly on community-votes left the panel permanently showing "you voted" with no way to vote again, since your local, on-device record of it was never re-checked against live data once it existed at all. It's now cross-checked against the same live fetch the dialog already makes for the "N others" count (no extra request), and forgotten if community-votes genuinely no longer confirms it. A vote cast in roughly the last 5 minutes is still trusted unconditionally either way, since community-votes' own processing of a freshly submitted vote can itself lag by a few seconds, and treating that normal delay as "deleted" would have undone the very thing this local record exists for. Any vote remembered from before this change is migrated to the new shape automatically the first time it's loaded.
- The panel's ~227KB JavaScript file was read with a blocking call directly on Home Assistant's event loop on every single setup/reload, briefly stalling it (worse on slower storage) -- found in code review ahead of this integration's HACS default-repo submission ([hacs/default#9584](https://github.com/hacs/default/pull/9584#pullrequestreview-4834751826)). That read now happens off the loop.

### Changed
- **Marking your own release as "healthy" now says so plainly, instead of a generic confirmation.**
  community-votes' own process-vote.yml deliberately gives a maintainer's own "healthy" vote zero weight
  (approving your own release isn't independent verification) -- found live, direct user feedback: the
  GitHub-side confirmation showed "0 healthy" right after "Thanks for your vote!" with no explanation,
  reading as if the vote had vanished. The panel now mirrors that same rule and says so in its own
  confirmation toast too, instead of only the GitHub issue's reply comment knowing about it.

## [0.5.0] - 2026-07-29

Opening an update's details now hands the actual "Install" action off to Home Assistant's own update dialog, complete with its real install button, live progress, and backup option, instead of Update Manager's own copy. Update Manager's own dialog now focuses purely on the decision: staging status, community verdict, and auto-install scheduling.

### Changed
- **The per-entity dialog no longer mimics HA's own more-info-update dialog for the actual install
  action.** Its own Install button and live install-progress bar are gone; a new "Open update" button
  (replacing the old separate "More info" button too, for a pending update) opens Home Assistant's real
  more-info dialog for that entity instead, where the actual Install button, live progress, and backup
  checkbox already live natively. Direct user feedback: our own copy was "namaak," not a real addition,
  and re-implementing it was exactly what both real bugs found earlier this session (`release_summary`
  rendering raw HTML as literal text, a `[hidden]` CSS-specificity bug) had in common. Changelog/release-
  notes rendering stays as it was (low duplication risk, already delegating to the same `ha-markdown`
  component and `update/release_notes` data HA's own dialog uses, and central to spotting a breaking
  change before deciding), as does Cancel/Unskip, "Update all," and the Zigbee rollout queue (none of
  those are HA-dialog duplication in the first place). A queued Zigbee rollout device still can't jump
  the line via this button either, same "Waiting for X" disabled state the old Install button had, now
  carried over. `appearance="accent"` (the genuinely strong/primary look, confirmed against `ha-button`'s
  own real source: "filled" is deliberately the softer fill, "accent" the loud one meant for a page's one
  primary action) only once the update is actually `ready`; otherwise `appearance="plain"`, since
  encouraging a manual install with the loudest button in the dialog would work against the whole point
  of staging while still waiting/skipped/blocked.
- **Skip is now only shown when the exact jump has a reported problem** (`community_verdict.problematic
  _count > 0`), not unconditionally. Shown with no reason attached, Skip was the same kind of
  undifferentiated duplication of HA's own generic skip capability Install was -- it earns its place in
  this dialog specifically as a reaction to a negative community vote, not as a bare convenience (HA's
  own dialog, reachable via "Open update," already offers Skip too). Not gated the same way the
  "held back" alert is (which also checks `auto_install_excluded`/a trusted-healthy override): Skip is a
  personal choice independent of whether auto-install would have run anyway.
- **"Clear skipped" moved out of the status alert into the dialog's own footer**, next to Skip -- turning
  postponement-hiding on and off for an update now lives in one consistent place. Cancel stays exactly
  where it was, in the alert's own `slot="action"`, right next to the "will update automatically at X"
  message it actually cancels (direct user feedback, after briefly trying both the footer and a plain
  sibling element instead: both lost the context that mattered, "die moet gewoon in de alert die aangeeft
  wanneer de auto update gepland staat"), just toned down to `appearance="plain"` instead of the bolder
  `"accent"` default `ha-progress-button` uses when left unset. That change on its own turned out to have a
  real WCAG problem: `appearance="plain"`'s own text color (`--wa-color-on-normal`, a webawesome design
  token) isn't adapted to sit on a colored background at all, unlike `ha-alert`'s own legacy `--mdc-theme-
  primary` mechanism for MWC-era action-slot buttons, which this newer button component never reads --
  blue text on the alert's green wash, "hele slechte wcag/contrast." Fixed before this ever shipped by
  overriding that same custom property to `--primary-text-color` instead (confirmed against `ha-button`'s
  real source), getting the same "readable on any alert color" result `ha-alert` always intended.
- **The status alert itself is now skipped entirely when it would only repeat the header's own bare
  status word** (e.g. a plain "Skipped" or "Ready to update" with nothing else to add) -- direct user
  feedback: "die alert mag wel weg. want de status is al skipped en clear skipped staat in de footer."
  Never silently drops a real Cancel button in the process: a genuine pending/projected auto-install
  always makes the alert's own text richer than the bare word to begin with.
- **"Report a known issue"/"Report as problematic" is now a filled button, not a plain text link** --
  direct user feedback: this is an action genuinely worth encouraging, and a soft-background button
  reads as more inviting/actionable than a bare link, matching the "Mark as healthy" button's own visual
  weight right next to it.

### Fixed
- A "waiting" update with a projected auto-install time *and* a negative community vote showed a
  contradiction: "will update automatically at X" (with a working Cancel button) right next to "Auto-
  install held back," even though the community block means it was never actually going to run. The
  status alert (and Cancel) is now suppressed whenever genuinely held back by the community, for any
  status this happens to be in -- not just the narrower "ready + held back" case fixed earlier this
  session. The header's own brief status value (e.g. "Ready to update," "Skipped") always shows the plain
  current status regardless of what the alert says, unaffected either way -- direct user feedback, after a
  follow-up screenshot showed "Skipped" twice, briefly led to hiding the header instead (the wrong fix for
  the wrong problem; the real fix was to stop showing a now-redundant alert, not to hide the header).
- Casting a vote in an earlier session and reopening the dialog later still showed "Mark as healthy" as
  an option even after already voting healthy -- `_buildVoteControls` never checked your own already-cast
  verdict before building it. Omitted now once already healthy (nothing left to add by repeating the
  exact same content-free vote); "Report as problematic" stays available regardless of your current vote,
  since a problematic vote always has real fields (reason/notes/link) worth revisiting or updating, even
  without changing the verdict itself.
- Plain `<a>` links this panel builds by hand (release-announcement, a reported reason's link, the
  GitHub-link verification URL) fell back to the browser's own default link color (blue) instead of HA's
  own -- confirmed against `more-info-update.ts`'s real source: its own `a` rule sets color only, the
  underline stays exactly as the browser draws it by default.
- The status alert showed "success" green for a scheduled auto-install ("Will update automatically at
  X"), even though that's a scheduled fact, not an accomplishment -- direct user feedback: "het is info
  en geen success toch?" Now "info" (blue) whenever there's an actual countdown to show, regardless of
  which underlying status (most often "ready," but not exclusively) happens to have it.
- **A Zigbee rollout-group member that wasn't yet queued could bypass rollout pacing entirely** by handing
  off to HA's own dialog and installing there (`update.install` directly, invisible to
  `rollout_manager.py`) instead of through `update_manager/install`, the only path that actually consults
  it -- found by `/code-review`: two identical devices could then reflash simultaneously, exactly the mesh
  instability rollout pacing exists to prevent. Disabling the button while queued was never the whole
  fix; any rollout-group member now installs through the coordinated path directly instead of opening
  HA's dialog at all, regardless of queue position.
- **Your own problematic vote's reason could silently vanish from `my_reason`** if 5 or more other people
  had voted more recently on the same jump -- found by `/code-review`: the reason list was capped to the 5
  most recent *before* your own entry was searched for, so it could already be gone by the time that
  search ran. Your own reason is now found with its own direct, cap-independent lookup; only the generic
  "other people's reasons" list is capped, and now correctly excludes yours before capping rather than
  after.
- **The Updates-tab list's own "will auto-install at X" pill could disagree with that same entity's
  dialog**, which correctly shows "held back" -- found by `/code-review`: the pill's own projection never
  checked the community verdict at all. Now mirrors the same trusted-vote/problematic-count priority the
  dialog and the real backend decision both already use.
- **`entry.runtime_data` was never reset after unloading the integration**, unlike the `hass.data.pop(...)`
  it replaced -- found by `/code-review`: a websocket call arriving in that window could silently operate
  on already-stopped managers instead of hitting the normal "not set up" guard. Diagnostics gained a
  matching `None` guard for the same reason, degrading gracefully instead of raising `AttributeError`.
- The "Open update" button could still show its loudest, primary styling for a `ready` update the
  community had actually flagged as a problem -- found by `/code-review`: the accent/plain choice never
  checked `heldBackByCommunity` at all, so it kept inviting the exact manual install the warning right
  above it was discouraging.

## [0.4.1] - 2026-07-29

Small fixes to the Community section and auto-install messaging added in 0.4.0:
- Fixed a rare case where the Community section could show contradictory information at once ("No one's
  reported" next to "N people reported").
- Your own reported reason no longer shows up a second time, unattributed, in the reasons list.
- A trusted voter's own reason is now clearly labeled as such, instead of blending in anonymously.
- The Settings tab's "Trusted voters" explanation now matches actual behavior: blocking a problematic
  update doesn't require a trusted voter at all.

### Fixed
- The Community section could show a contradictory pileup: "No one's reported on this jump yet." right
  above "N people reported this jump as healthy/problematic." and a trusted-vote line for the same jump.
  Same root cause as an already-fixed sibling bug in `.dialog-community-section` (found 2026-07-22): a
  bare `.dialog-community-verdict-line { display: flex; ... }` CSS rule ties the browser's own `[hidden]`
  rule in specificity and wins by coming later in the cascade, so `verdictRow.hidden = true` (set when you
  have no vote of your own but others do, since the aggregate row below already covers that case) silently
  never actually hid the row. Its stale "not yet rated" placeholder text (set at build time, before the
  real fetch resolves) stayed visible, contradicting the aggregate/trusted-vote rows correctly rendered
  right below it. Fixed the same way as the sibling bug: `.dialog-community-verdict-line:not([hidden])`.
- Dutch `community_verdict_mixed` ("N meldden dit gezond, M problematisch", shown when you haven't voted
  yourself but others gave a mixed verdict) always used the plural verb form ("melden"), even for a count
  of exactly 1 healthy vote, unlike its own `others`-perspective sibling which already conjugated
  correctly. Found while auditing every Community-section scenario after the bug above.
- Your own problematic vote's own reported reason showed up a second time, unattributed, in the generic
  "Reported reasons" list right below "You reported this jump as problematic," reading as if someone else
  independently reported the exact same thing. Split server-side (the linked GitHub username was already
  resolved there anyway) into its own `my_reason`, shown attached to your own vote line instead; the
  generic list now only ever lists *other* people's reasons.
- A reason from a configured trusted voter was indistinguishable from anyone else's in that same list,
  with no link back to the separate "Trusted vote: @name..." line already shown above it, even though
  it's the exact same vote. Now labeled "Trusted voter: <reason>".
- The Settings tab's own "Trusted voters" helper text still described its pre-0.4.0 behavior ("problematic
  always blocks auto-install"), reading as if blocking required a trusted voter at all. Reworded to lead
  with what naming someone actually still uniquely does (a healthy vote force-installs), and to state that
  blocking already works for anyone's problematic vote regardless of this list; the "Auto-install" card's
  own intro line gained the same clarification.

## [0.4.0] - 2026-07-29

**Auto-install now stops itself when the community reports a problem**
A pending update is now held back from auto-installing the moment anyone reports it as problematic for
your exact version jump, no minimum number of votes needed. Previously, only a specifically trusted
voter's own vote could do this; with no trusted voters configured, a completely negative community
verdict had no effect on auto-install at all. A trusted voter's own "healthy" vote still overrides this,
exactly as before, and the dialog now explains itself whenever this happens.

**A repair notification when your GitHub link needs refreshing**
If the GitHub account you linked for community voting can no longer be refreshed (revoked, or unused for
6 months), Update Manager now shows a repair notification in Settings > System > Repairs asking you to
re-link it. It clears itself automatically once you do.

**Also in this release:**
- Each reported problem now shows its own reason (and any notes/link the reporter added), instead of only
  a bare count.
- Clearing the "Excluded entities" or "Trusted voters" field down to nothing now saves correctly, instead
  of failing silently.
- A version jump missing just its patch number (e.g. 0.36.2 to 0.37) is now classified correctly instead
  of always landing on the cautious "big" size.

### Added
- **Any problematic community vote now blocks auto-install for that exact jump**, not just a configured
  trusted voter's vote. Direct user report: a 100% negative community verdict was still queued for
  auto-install, because `effective_auto_install_state` only ever consulted `trusted_vote`, so with no
  trusted voters configured (the default), the wider crowd's own verdict had zero effect on auto-install
  whatsoever. No quorum or percentage needed: a single problematic vote, however small a minority, is
  enough to block, the same reasoning `FUTURE.md`'s own "point 5" already worked out before trusted voters
  existed (quorum only ever mattered for trusting the crowd enough to force an install, a feature that
  doesn't exist yet). A configured trusted voter's own "healthy" vote still overrides this and forces
  install regardless, confirmed with the user ("wat hebben we dan nog aan een trusted voter?"), since
  naming someone as trusted would otherwise be pointless if any random untrusted report could override
  them anyway. The Updates-tab dialog's "Auto-install held back" alert (previously trusted-voter-only) now
  also fires for this general case, with a count-based message when it's not specifically a trusted
  voter's own vote. When this alert applies to a "ready" update, the plain green "Ready to update" status
  alert above it is skipped rather than shown right next to a warning saying the opposite, since the
  header above already states "Ready to update" on its own and the two together read as contradictory
  clutter rather than two different facts.
- **A problematic vote's own reported reason is now visible.** `reason_category`/`notes`/`link` were
  already collected on submission and persisted per-voter upstream, but no code here ever read them back,
  so a vote's reason was write-only from this integration's perspective. The per-entity dialog's Community
  section now lists each problematic voter's reported reason category, free-text notes, and an optional
  link, capped at the 5 most recent. Not attributed to a specific username (including your own, if you're
  one of them): the reason itself is the useful part, and your own vote is already named separately right
  above ("You reported this jump as problematic").
- **Known limitation, documented rather than fixed**: a vote (and this new block) is scoped to the exact
  version jump, not to any known issue somewhere along the way. A negative verdict on 1.0.0 to 1.0.1 has
  no bearing at all on a direct 1.0.0 to 1.0.2 jump (a separate file, separate `jumps` entry upstream).
  Fixing this would need reasoning about every intermediate version silently skipped over, a much larger
  change than this one; see the README's own Known limitations section.
- A repair issue ("Update Manager's GitHub link has expired") now appears in Settings -> System ->
  Repairs when the linked GitHub account (used for community voting) can no longer be refreshed -- either
  the refresh token itself expired after 6 months unused, or GitHub explicitly rejected it (e.g. a revoked
  token). Not raised for a plain network hiccup on the refresh call, only for a failure that actually needs
  you to re-link via the panel's Settings tab. Clears itself automatically the moment you do.

### Internal
- Migrated off `hass.data[DOMAIN]` onto `ConfigEntry.runtime_data` (a new `UpdateManagerData` dataclass in
  `runtime_data.py`), closing `quality_scale.yaml`'s own `runtime-data` gap. `websocket_api.py`'s
  handlers (the one place with no `ConfigEntry` of their own, since websocket commands are registered
  globally, not per-entry) resolve it through a small `_get_data(hass)` helper that reads the one entry
  this single-instance integration ever has -- the same lookup `_handle_get_settings`/`_handle_save_settings`
  already did by hand, now shared instead of duplicated a third time.
- `install_manager.py`'s auto-install `reason` ("rules" or "trusted_voter") is now a real
  `Literal["rules", "trusted_voter"]` type (`announcer.py`'s new `AutoInstallReason`) instead of a bare
  `str`, so a future third reason value (or a typo comparing against one) would be caught by type-checking
  instead of silently doing nothing.

### Changed
- README trimmed for conciseness throughout, and the "Automation examples" section removed entirely
  (direct user feedback, 2026-07-29); `quality_scale.yaml`'s `docs-examples` reverted from done to todo to
  reflect that, since those examples were its only content. Easy to add back later if ever wanted.
- The default wait days used before the Settings tab has ever been saved: small 0 → 1, medium 1 → 3,
  big 3 → 7. Only affects a config entry that's never had its own settings saved yet -- an
  already-configured instance is unaffected. Also dropped the last remnants of a "profile" picker
  (conservative/balanced/free) that was removed from the panel a while back: only the one set of numbers
  above was still actually read anywhere, so const.py's own `PROFILE_PRESETS` (and the unused
  conservative/free presets inside it) is gone, replaced by a single `DEFAULT_WAIT_DAYS`.
- The "Update Manager Enabled" switch now has `entity_category: config` (it toggles the integration's own
  automatic behavior, not a primary control) and shows a distinct icon while paused (`mdi:update-off`).
- Added `quality_scale.yaml` tracking this project against Home Assistant's own integration quality
  checklist, and closed most of the easy gaps it surfaced: both entities now use `has_entity_name` +
  translated names/icons instead of hardcoded strings, and the README gained Removal, Configuration
  parameters, Use cases, How data updates, Automation examples, Known limitations, and Troubleshooting
  sections. A handful of larger items (test coverage, a GitHub-token reauth flow, migrating off
  `hass.data`) are tracked as open, not silently marked done -- see the file itself.

### Fixed
- The config-flow's own English description mixed in a stray Dutch word ("Instellingen") instead of
  saying "Settings".
- The History tab's empty state ("No updates logged yet.") was a bare line of text with no card around
  it, inconsistent with both every real History entry (always its own card) and the Updates tab's own
  empty state. It now uses the exact same card treatment as that one.
- The Settings tab's cards were spaced 16px apart, while Updates and History both space theirs (or their
  date sections) 24px apart, the same value real HA itself uses on the equivalent page. All three tabs
  now use the same 24px rhythm.
- The release-notes link said "Release announcement" (pending update) or "Release page" (History entry),
  neither matching real HA's own wording for this exact link ("Read release announcement"). Both now say
  the same thing HA itself does.
- A jump between a full semver version and one missing just its patch number (e.g. "0.36.2" -> "0.37")
  was misclassified as "big": it fell through both the same-shape short-semver and full-semver checks,
  landing on the conservative default even though the minor-version change (36 -> 37) was perfectly
  ordinary and detectable. The missing patch is now just treated as 0, same as it already is when both
  sides are short.
- Clearing the "Excluded entities" or "Trusted voters" field down to nothing failed to save at all
  ("required key not provided... Got None"): ha-form's own multi-value selector sends `null` once the
  last chip is removed, not an empty list, and that null was passed straight through to the save
  payload instead of being treated as "none".
- Casting a vote in the dialog updated your own "You reported this jump as..." row, but left the
  aggregate "N others reported..." row right below it stuck on its pre-vote perspective and count
  (still counting your own just-cast vote) until the whole dialog was reopened.
- Setup briefly showed a wrong (empty/stale) community verdict for whichever entities the startup scan
  reached before the community-verdict cache had finished loading from disk -- an efficiency change
  earlier this session gathered that load concurrently with the scan itself instead of awaiting it
  first, quietly reintroducing the exact kind of startup race an earlier fix (for a different cache) had
  already been written to avoid.

### Internal
- Found by a `/code-review` pass: the per-entity dialog's community-verdict fetch and your-own-vote
  fetch ran as two sequential awaits instead of concurrently, needlessly doubling the dialog's network
  latency on first open; `async_start`'s two independent Store reads were sequential for the same reason.
  Both now run concurrently.
- The healthy/problematic-to-icon choice was independently re-derived at five separate call sites in the
  panel; consolidated into one `verdictIcon()` helper. `verdictBadge` also no longer needs a synthetic
  `{ community_verdict: ... }` wrapper object built just to satisfy its own signature.
- The coordinator's plain (no-argument) listener loop was duplicated across three call sites; extracted
  into one shared `_fire_listeners()`, mirroring the install-listener loop that was already deduplicated
  the same way earlier.

## [0.3.0] - 2026-07-27

**Community voting redesigned: clearer, more complete information**
The Community section no longer opens with a question. It now shows plain facts in order: your own vote
first (shown even when everyone else disagrees, which used to hide it), then everyone else's votes (both
healthy and problematic counts when opinions are mixed), and a clear "No one's reported on this jump
yet." when there's nothing at all. It also shows when one of your trusted voters has voted, since that's
what changes auto-install behavior. A few related display bugs are fixed too: a double divider, the
section appearing after long release notes instead of before them, and a stale "not yet rated" message
next to your own just-submitted vote.

**HA Core updates now appear on the History page**
Installing Core requires a full restart, so the update was never logged before. It's now recorded
retroactively once Home Assistant is back up.

**Also in this release:**
- The manual refresh button now also pulls in the latest community-vote data, not a cached version up to
  an hour old.
- Installing an update from its own dialog now refreshes that dialog once the install finishes.
- Updates already scheduled to auto-install now sort by how soon that happens, not by how long they've
  been available.
- A same-month update (e.g. 2026.07.3 to 2026.07.4) is now correctly classified as small instead of big.
- Fixed the Zigbee/Z2M rollout-queue cards rendering full-width instead of matching every other card.

### Added
- The panel's own manual refresh button now also pulls in the latest community-votes data for every
  pending update, instead of only reflecting whatever was cached (up to an hour old). Everything else
  it already did (updates/history/settings) is unchanged.
- The dialog's Community section now also shows when a configured trusted voter is among the people who
  voted on the exact jump being viewed (not just your own vote), since that's exactly the fact that
  changes auto-install behavior for it. Backed by a new `trusted_vote`/`trusted_voters_matched` pair on
  the `verdict_for_version` websocket response.

### Changed
- The Community section no longer asks "How's this update treating you?" before showing the verdict.
  It's now a short stack of plain facts, shown in priority order: your own vote (if any, shown even when
  it disagrees with everyone else, which used to make it disappear from the sentence entirely), then
  everyone else's votes (both healthy and problematic counts shown when genuinely mixed, instead of only
  ever surfacing the more cautious one), then "No one's reported on this jump yet." if there's truly
  nothing at all. Identical wording for a still-pending update and an already-installed History entry;
  only the vote controls below still differ between the two.

### Fixed
- HA Core (and likely Supervisor/OS) updates never appeared on the History page at all: installing them
  requires a full HA restart, so the installed_version transition happened across that restart boundary,
  which the coordinator's live state-change listener could never observe. It now persists each tracked
  entity's own last-known installed_version and detects the transition retroactively at startup.
- The verdict/badge wording said "this version" ("deze versie") instead of "this jump" ("deze sprong"),
  even though voting has been scoped to the exact from/to jump since 2026-07-24.
- Opening the dialog from the Updates tab (or a rollout-queue row) also auto-expanded the entity's most
  recent History entry, even though the pending update's own Community section already had the point.
  History entries only auto-expand now when opened directly from the History tab, or when the entity has
  no pending update of its own.
- An expanded History entry's own Community section rendered two divider lines stacked on top of each
  other, with too little spacing above them.
- An expanded History entry's own Community section rendered *after* its changelog/release notes,
  easy to miss on an entry with long release notes even though spotting a reported problem before
  reading them is the whole point. It now sits right after the entry's plain facts, before the
  changelog, each separated by its own divider.
- Opening the dialog from the History tab for one specific past install also pulled in the entity's
  entire, unrelated *current* pending update (progress bar, status alert, Cancel/Skip/Install actions,
  its own Community section, its own changelog) above the entry that was actually clicked. That block no
  longer renders at all when a specific History entry was opened directly; it's still there in full when
  opened from the Updates tab or a rollout-queue row.
- "Ready to update" no longer sorted entities with an active scheduled auto-install (`pending_install`)
  by how soon that install will actually happen; it sorted by how long the update had been available
  instead, like every other ready entity.
- A same-month calendar-version jump (e.g. "2026.07.3" -> "2026.07.4") was misclassified as "big" instead
  of "small": the zero-padded month ("07") matched neither the calendar-version shape nor strict semver.
- Installing an update from the dialog itself left the dialog showing its stale pending-update facts and
  an enabled Install button indefinitely, even after the install had actually finished. It now reopens
  itself in place once the install completes, the same way it already does for Cancel/Skip/Unskip.
- Casting a vote left the "No one's reported on this jump yet." line untouched right next to the vote's
  own confirmation message, reading as a contradiction. It now shows your own vote immediately, the same
  optimistic, local update the confirmation message itself already relies on.
- The Zigbee/Z2M rollout-queue cards (and the "all caught up" empty state) rendered full-width and
  flush left on the Updates tab instead of the same capped, centered 600px column every other card gets,
  since the shared width rule only matched cards nested one level deeper than these actually are.

## [0.2.0] - 2026-07-25

## Community voting

See how other users rated a specific update before you install it, and share your own verdict once
you have. Link your GitHub account (a quick one-time step: enter a short code on GitHub's own site, no
password shared with Update Manager), then vote healthy or problematic on any update, from either the
Updates tab (still pending) or the History tab (already installed).

A vote is about the exact jump you're taking, not just the version you land on: going from an old
version to a brand-new one carries different risk than a small step from the version right before it,
so both are tracked separately, and you can see how other jumps to the same version went too. Every
History entry can be expanded to vote on it directly, with the most recent one already open.

Covers HACS integrations, Home Assistant Core/Supervisor/OS, real vendor Zigbee device firmware, and
Supervisor add-ons. Self-flashed firmware (ESPHome, Tasmota) isn't covered: there's no reliable way to
compare installs of those. A community verdict badge (healthy/problematic counts) also shows up right
on the Updates tab for anything votable.

**Trusted voters**: name one or more GitHub usernames whose verdict on a specific update overrides your
own auto-install rules, in either direction. If they rated it healthy, it installs regardless of your
own rules; if problematic, it's held back even if your rules would otherwise allow it.

**Also in this release:**

**Zigbee/ZHA rollout pacing**
Firmware installs across identical Zigbee devices now happen one at a time instead of all at once,
protecting your mesh from the traffic spike of updating everything simultaneously.

**Redesigned Settings and History pages**
Settings groups related options together more clearly, and History now shows a full audit trail for
every install: when it became available, when it was announced, when it was installed, and why (your
own rules, a trusted vote, or a manual click).

**Fixes updates losing their wait progress after a restart**
A postponed update no longer forgets how long it's been waiting after a restart, brief unavailability,
or reload.

**Adds an Enabled switch entity**
The master pause switch is now also a real switch entity, so it can be controlled from a dashboard or
automation.

### Added
- GitHub account linking (`github_auth.py`): a "Link GitHub account" button in Settings using OAuth
  device flow, no client secret involved anywhere.
- Community voting (`community_vote.py`, `vote_issue_body.py`, `device_identity.py`): vote buttons in
  the update dialog's own Community section, scoped to the exact version jump being viewed (a pending
  update's own installed-to-latest jump, or a specific History entry's from/to pair), submitted as a
  community-votes issue using the linked account. Identity resolution now covers all four community-votes
  categories: HACS/Core/Supervisor/OS (HACS gated on the entity actually being HACS-owned via
  entity_registry, not release_url's shape alone), plus real vendor Zigbee device firmware
  (manufacturer/model, via ZHA/Zigbee2MQTT) and Supervisor add-ons (via the add-on's own device-registry
  slug).
- Shows other jumps landing on the same destination version, if any, right below your own jump's verdict
  in the dialog (`other_jumps` in `community_verdict.py`/`community_verdict_payload.py`) -- your own jump
  is always primary, other jumps are purely supplementary context, sorted by vote count and capped at 5.
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
  own vote on a specific version jump overrides your own size-based rules for that exact jump, healthy
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
- Community voting now lives inside each History entry's own card, not a single fixed section elsewhere
  in the dialog -- any past version jump for an entity is directly votable, not just whichever one the
  dialog happened to open with. The most recent entry expands by default so its own vote section is
  visible immediately; each entry's vote data is only fetched the first time its own card is expanded,
  not eagerly for every entry when the dialog opens.
- The auto-install "this was automatic" indicator is now icon-only with a tooltip, instead of an icon
  plus a repeated text label on every row; the tooltip itself now names the specific reason (your own
  rules, or a trusted vote from whoever) instead of a generic "Automatically updated".
- The Settings page's Community verdict section spacing/proportions were tightened, and its "not yet
  rated" copy now reads "by others" instead of "by the community" (direct user feedback: read more
  naturally once your own past vote is recognized separately).
- community-votes' own on-disk schema (`votes/<category>/.../<to-version>.json`): one file per
  destination version now holds every rated jump landing on it (`{"jumps": {"<from-version>": {...}}}`),
  instead of one file per destination version alone. The vote Issue Form gained a required "From
  version" field alongside the renamed "To version" (was "Version"). `process-vote.yml`'s own
  read-modify-write now retries (with a small randomized delay) on a conflicting concurrent write,
  since two different people voting on two different jumps to the same destination can now genuinely
  race on the same file, which was never possible under the old one-file-per-voter layout.

### Fixed
- A two-component major.minor version (no patch at all, e.g. "18.0" -> "18.1") was always classified as
  "big" impact, the same conservative default any genuinely unrecognized version shape gets, since
  `classify_version_size` only ever recognized strict three-part semver, HA Core's calendar versioning,
  and git commit hashes. Now recognized as its own scheme (found live: an update entity reporting a real
  minor-only jump showed as "Big" impact) -- a major-component change stays "big", a minor-component
  change is "medium".
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
