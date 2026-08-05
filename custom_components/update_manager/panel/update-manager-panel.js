/**
 * Update Manager: HA sidebar panel (Phase 2, see FUTURE.md)
 *
 * Registered by panel.py via panel_custom, served as a plain ES module --
 * no build step, same convention as this project family's Lovelace cards
 * (cover-media-card.js etc.): a single file, HTMLElement + shadow DOM, no
 * bundler/npm dependency. Uses HA's own frontend components directly via
 * document.createElement + property assignment (no import needed -- they're
 * already globally registered custom elements by the time any panel loads,
 * the same reason a plain Lovelace card can use <ha-icon> unimported):
 * hass-tabs-subpage for the page chrome (the exact component /config/devices
 * and HACS's own panel use -- real per-tab URLs under this panel's own path,
 * not just in-memory tab state) and ha-form for the settings screen.
 *
 * Read-only Updates/Historie tabs, backed by websocket_api.py's
 * update_manager/updates + update_manager/install_log. Instellingen
 * replaces the interim options flow (update_manager/get_settings +
 * update_manager/save_settings) -- see FUTURE.md's "Tussenstap" note.
 *
 * Auto-install (see FUTURE.md's "Auto-install (niveau 3): ontwerp") never
 * installs anything the instant it becomes eligible: install_manager.py
 * announces it first (a cancellable countdown), and this panel is where
 * that countdown and its cancel button actually live -- deliberately not a
 * HA Repair issue, this isn't a problem to fix. Still no direct "install
 * now" button anywhere: that would be a fully separate, undiscussed step
 * beyond what was agreed.
 */

// Real HA sub-routes (not just in-memory tab state): each tab gets its own
// URL under the panel's own path (e.g. /update-manager/history), navigated
// via hass-tabs-subpage the same way /config/devices etc. do -- so the
// back button, direct links, and page refresh all behave the way you'd
// expect from any other HA settings page (direct user feedback).
//
// hass-tabs-subpage's own tabs[].path must be the *full* absolute path
// (matched directly against route.prefix + route.path, and used as-is for
// the tab <a href>, see hass-tabs-subpage.ts) -- not a path relative to the
// panel, which was the bug found via live testing: tabs navigated to the
// site root (e.g. /updates) instead of /update-manager/updates.
const PANEL_PATH = "/update-manager";
// Raw MDI SVG path data, not an icon name -- hass-tabs-subpage's tabs
// render via ha-svg-icon (.path=), unlike <ha-icon icon="mdi:...">
// elsewhere in this file, which resolves a name to a path itself at
// runtime. Copied verbatim from @mdi/js (mdiUpdate/mdiHistory/mdiCog) since
// importing that package would need a build step, same reasoning as
// avoiding Lit everywhere else in this project.
const ICON_UPDATE =
  "M21,10.12H14.22L16.96,7.3C14.23,4.6 9.81,4.5 7.08,7.2C4.35,9.91 4.35,14.28 7.08,17C9.81,19.7 14.23,19.7 16.96,17C18.32,15.65 19,14.08 19,12.1H21C21,14.08 20.12,16.65 18.36,18.39C14.85,21.87 9.15,21.87 5.64,18.39C2.14,14.92 2.11,9.28 5.62,5.81C9.13,2.34 14.76,2.34 18.27,5.81L21,3V10.12M12.5,8V12.25L16,14.33L15.28,15.54L11,13V8H12.5Z";
const ICON_HISTORY =
  "M13.5,8H12V13L16.28,15.54L17,14.33L13.5,12.25V8M13,3A9,9 0 0,0 4,12H1L4.96,16.03L9,12H6A7,7 0 0,1 13,5A7,7 0 0,1 20,12A7,7 0 0,1 13,19C11.07,19 9.32,18.21 8.06,16.94L6.64,18.36C8.27,20 10.5,21 13,21A9,9 0 0,0 22,12A9,9 0 0,0 13,3";
const ICON_COG =
  "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5M19.43,12.97C19.47,12.65 19.5,12.33 19.5,12C19.5,11.67 19.47,11.34 19.43,11L21.54,9.37C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27C19.54,5.05 19.27,4.96 19.05,5.05L16.56,6.05C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05C4.73,4.96 4.46,5.05 4.34,5.27L2.34,8.73C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11C4.53,11.34 4.5,11.67 4.5,12C4.5,12.33 4.53,12.65 4.57,12.97L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73C4.46,18.95 4.73,19.03 4.95,18.95L7.44,17.94C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58L14.87,18.93C15.5,18.67 16.04,18.34 16.56,17.94L19.05,18.95C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.97Z";
// Verified against the real @mdi/js package (mdiAutoDownload/mdiClockOutline),
// same approach as the tab icons above -- used on the trailing timer
// badge/pill (see timerBadge), not the ICON_* tab set. mdiAutoDownload, not
// the plain mdiDownload this used to be: every use of this icon means
// specifically "Update Manager's own auto-install did/will do this", not
// just "a download happened": direct user feedback, the generic download
// glyph didn't actually say "automatic" at a glance.
const ICON_AUTO_DOWNLOAD =
  "M22 17V19H11V17H22M19 4.5V9.5H22L16.5 15L11 9.5H14V4.5H19M10.7 15H8.8L8.1 13H4.9L4.2 15H2.3L5.5 6H7.5L10.7 15M7.65 11.65L6.5 8L5.35 11.65H7.65Z";
const ICON_CLOCK_OUTLINE =
  "M12,20A8,8 0 0,0 20,12A8,8 0 0,0 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20M12,2A10,10 0 0,1 22,12A10,10 0 0,1 12,22C6.47,22 2,17.5 2,12A10,10 0 0,1 12,2M12.5,7V12.25L17,14.92L16.25,16.15L11,13V7H12.5Z";
// mdiChevronDown: the history dialog's own "expand this entry" chevron
// (see _openDetailDialog), rotated 180deg via .open instead of relying on
// ha-expansion-panel's own built-in one: that component's row looked
// visually distinct from the plain ha-list-item-button used elsewhere in
// this same timeline, which read as inconsistent sitting side by side.
// Direct user feedback. Every history entry now expands the same way
// (changed 2026-07-23: a release_url-only entry used to instead open
// externally on click, and a changelog-less entry couldn't expand at all)
// -- one row shape, one chevron, regardless of what a given entry has to
// show once expanded.
const ICON_CHEVRON_DOWN = "M7.41,8.58L12,13.17L16.59,8.58L18,10L12,16L6,10L7.41,8.58Z";
// mdiThumbUp/mdiAlert, verified against api.iconify.design (2026-07-22): the
// community-verdict badge (see verdictBadge), read-only slice, no vote UI
// yet. Thumb-up for zero problematic reports, alert for one or more.
const ICON_THUMB_UP =
  "M23 10a2 2 0 0 0-2-2h-6.32l.96-4.57c.02-.1.03-.21.03-.32c0-.41-.17-.79-.44-1.06L14.17 1L7.59 7.58C7.22 7.95 7 8.45 7 9v10a2 2 0 0 0 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73zM1 21h4V9H1z";
const ICON_ALERT = "M13 14h-2V9h2m0 9h-2v-2h2M1 21h22L12 2z";

// The one place "problematic -> alert icon, else thumb-up" gets decided --
// found by code review, 2026-07-27: this exact ternary (or its count>0
// equivalent) was independently re-derived at five call sites across this
// file, risking the two spellings silently drifting apart.
function verdictIcon(isProblematic) {
  return isProblematic ? ICON_ALERT : ICON_THUMB_UP;
}

// TRANSLATIONS itself now lives in its own file, translations.js (2026-08-07,
// direct user feedback: "Ik wil alle copy, bij alle projecten, centraal
// kunnen beheren per taal"), loaded dynamically below rather than via a
// plain static `import` -- see _loadTranslations' own comment for why a
// static import would risk exactly the kind of stale-browser-cache bug
// panel.py's own _panel_js_cache_key already exists to prevent for this
// file itself.
//
// Reuses the exact ?v= query string this module itself was loaded with
// (import.meta.url already carries it), so translations.js busts the
// browser's cache in lockstep with this file -- panel.py's own
// _panel_js_cache_key hashes both files' combined content for that same
// query string, see its own docstring.
function _loadTranslations() {
  const panelUrl = new URL(import.meta.url);
  const translationsUrl = new URL(`translations.js${panelUrl.search}`, panelUrl);
  return import(translationsUrl.href).then((module) => module.TRANSLATIONS);
}
const _translationsPromise = _loadTranslations();
// Seconds per unit, in the same order as tr.units -- language-independent,
// kept separate from the translated words themselves.
const _UNIT_SECONDS = [365 * 24 * 3600, 30 * 24 * 3600, 7 * 24 * 3600, 24 * 3600, 3600, 60];

const TAB_DEFS = [
  { tab: "updates", relativePath: "/updates", path: `${PANEL_PATH}/updates`, iconPath: ICON_UPDATE, nameKey: "tab_updates" },
  { tab: "history", relativePath: "/history", path: `${PANEL_PATH}/history`, iconPath: ICON_HISTORY, nameKey: "tab_history" },
  { tab: "settings", relativePath: "/settings", path: `${PANEL_PATH}/settings`, iconPath: ICON_COG, nameKey: "tab_settings" },
];

function tabForPath(relativePath) {
  const match = TAB_DEFS.find(
    (t) => relativePath === t.relativePath || relativePath.startsWith(`${t.relativePath}/`)
  );
  return match ? match.tab : "updates";
}

// Native ha-form all the way through (direct user feedback: a hand-rolled
// table, while compact, stopped feeling like standard HA) -- one always-
// expanded section per size (so nothing needs a click to reveal, still
// "speaks for itself"), each holding its two fields stacked, not side by
// side (direct user feedback: let each take the full width). The two field
// labels do repeat across the 3 sections, but only ever one size's worth is
// what you're looking at at a
// time -- the section title itself (tr.size_*, shown once per size, with
// its explanation) is what would otherwise have needed repeating.
const SIZES = ["small", "medium", "large"];

// vote_reason_* translation keys, one shared source of truth (see
// _buildVoteControls): found by review, two independently hand-written
// {value, label} arrays used to duplicate this mapping with inconsistent
// relative order. Journey A (pending update, not yet installed) only
// offers a filtered, reordered subset -- breaking change listed first
// there, since a known breaking change (from the release notes) is the
// whole reason that journey exists (direct user feedback, 2026-07-22).
// Journey B (History tab, already installed) offers all five in the same
// order community-votes' own vote.yml dropdown uses.
const _VOTE_REASON_LABEL_KEYS = {
  "broken functionality": "vote_reason_broken",
  "requires a newer HA version": "vote_reason_requires_newer",
  "is a dev/pre-release build": "vote_reason_dev_build",
  "breaking change": "vote_reason_breaking_change",
  other: "vote_reason_other",
};
const _JOURNEY_B_REASON_ORDER = [
  "broken functionality",
  "requires a newer HA version",
  "is a dev/pre-release build",
  "breaking change",
  "other",
];
const _JOURNEY_A_REASON_ORDER = ["breaking change", "requires a newer HA version", "is a dev/pre-release build"];

function fieldKind(name) {
  for (const size of SIZES) {
    if (name === `${size}_wait_days`) return "wait_days";
    if (name === `${size}_auto_install`) return "auto_install";
  }
  return null;
}

// Found via live testing: a config entry's stored options never get
// automatically cleaned up by HA, so fields from an earlier design (e.g.
// the removed *_blocked/*_mode from before 2026-07-16) can keep sitting in
// there indefinitely. Deriving the known-field list from SIZES itself (not
// a separately maintained list, so it can't drift) and filtering through it
// on both load and save means stale keys just quietly stop being sent,
// instead of silently accumulating.
function knownSettingsFields() {
  const names = ["enabled", "announce_hours", "excluded_entities", "hide_postponed", "trusted_voters"];
  for (const size of SIZES) {
    names.push(`${size}_wait_days`, `${size}_auto_install`);
  }
  return names;
}

// Fields whose value must always be a real array, never null/undefined --
// ha-form's own multiple:true selector emits null once the last chip is
// removed (found live, 2026-07-27), and save_settings' own schema requires
// a real list for both. Coerced here too, not just at each field's own
// value-changed handler (see entitiesForm/trustedForm below): this is the
// one place every settings field already passes through before being sent,
// so a future third list-typed field is covered automatically instead of
// needing to remember this same fix on its own.
const LIST_SETTINGS_FIELDS = new Set(["excluded_entities", "trusted_voters"]);

function pickKnownSettings(data) {
  const known = knownSettingsFields();
  const result = {};
  for (const key of known) {
    if (!(key in data)) continue;
    result[key] = LIST_SETTINGS_FIELDS.has(key) ? data[key] || [] : data[key];
  }
  return result;
}

// Status sorts green-orange-red (safest first), requested directly by the
// user. Within "ready"/"blocked", oldest-available first (the longest-
// standing, most "proven" update sinks to the top of its group); within
// "waiting", soonest-to-turn-green first instead (least remaining_seconds)
// -- oldest-available doesn't mean the same thing there (found live: a
// "large" update available 59 days into a 60-day wait sorted above a
// "medium" update 12 hours from ready, since it had simply existed longer,
// not because it was closer to actionable).
const STATUS_SORT_PRIORITY = { ready: 0, waiting: 1, blocked: 2, skipped: 3 };

// ha-alert's alertType per status, shown in the detail dialog -- kept next
// to STATUS_SORT_PRIORITY since both need the same fallback for a status
// value this panel doesn't recognize (see _FALLBACK_STATUS below).
const STATUS_ALERT_TYPE = { ready: "success", waiting: "info", blocked: "warning", skipped: "info" };

// One shared fallback for an unrecognized/future status value, used by
// every lookup keyed on u.status below (sort priority, grouping, alert
// color) -- previously each had its own independent hardcoded fallback
// (two silently agreed on "blocked", the alert color didn't, defaulting to
// "info" instead), so a new status value added without touching all of
// them would sort/group as blocked but render with the wrong alert color.
const _FALLBACK_STATUS = "blocked";

// Tier-by-tier, not one packed number -- a single additive key worked while
// every status only ever needed one secondary ordering, but "ready" now
// needs two different ones within the same group (see below), and a raw
// available_since timestamp and a scheduled execute_at time aren't the same
// unit, so packing both into one arithmetic slot doesn't generalize.
function compareUpdates(a, b, settings) {
  const priorityOf = (u) => STATUS_SORT_PRIORITY[u.status] ?? STATUS_SORT_PRIORITY[_FALLBACK_STATUS];
  const pa = priorityOf(a);
  const pb = priorityOf(b);
  if (pa !== pb) return pa - pb;

  // Within "ready": an entity already counting down to a real scheduled
  // auto-install (pending_install) sorts soonest-execute_at-first among
  // others like it, ahead of "ready" entities with nothing scheduled yet --
  // direct user feedback, 2026-07-27 ("in ready to update zou ik verwachten
  // dat de geplande geautomatiseerde updates op volgorde gesorteerd staan
  // van nu naar later"). Plain ready entities (no pending_install) keep the
  // existing oldest-available-first order below.
  if (a.status === "ready" && b.status === "ready") {
    const aScheduled = a.pending_install != null;
    const bScheduled = b.pending_install != null;
    if (aScheduled !== bScheduled) return aScheduled ? -1 : 1;
    if (aScheduled) {
      return new Date(a.pending_install.execute_at).getTime() - new Date(b.pending_install.execute_at).getTime();
    }
  }

  const availableSinceSec = (u) => (u.available_since ? Math.floor(new Date(u.available_since).getTime() / 1000) : 0);
  // Same number the badge itself displays, not always plain remaining_seconds
  // -- found live: two auto-install-projected updates sorted apart, with an
  // unrelated manual one in between, because remaining_seconds alone (time
  // to "ready") no longer matches what's shown once projectedAutoInstallTime
  // (remaining_seconds + announce_hours) is what the badge actually counts
  // down to.
  const waitingSeconds = (u) => {
    const projected = u.status === "waiting" ? projectedAutoInstallTime(u, settings) : null;
    return projected ? Math.round((new Date(projected).getTime() - Date.now()) / 1000) : u.remaining_seconds;
  };
  const secondaryOf = (u) => {
    const w = u.status === "waiting" ? waitingSeconds(u) : null;
    return w != null ? w : availableSinceSec(u);
  };
  return secondaryOf(a) - secondaryOf(b);
}

// Mirrors announcer.py's own effective_auto_install_state (found by code
// review, 2026-07-29): a trusted "healthy" vote overrides a community block,
// same as it does server-side, but otherwise any problematic vote means
// auto-install genuinely won't happen. Shared by autoInstallEnabledFor below
// and _openDetailDialog's own heldBackByCommunity, so the two can't drift
// apart the way they already once did (the Updates-tab list row's own "will
// auto-install at X" pill disagreeing with that same entity's dialog).
function communityBlocksAutoInstall(u) {
  if (u.trusted_vote === "healthy") return false;
  return ((u.community_verdict && u.community_verdict.problematic_count) || 0) > 0;
}

// Will this update ever auto-install itself, as currently configured?
// Installable, not excluded (hard or user-picked), and the *_auto_install
// setting for its size is on. `settings` is the saved settings object
// (this._settings), not the live-edited form state -- what's actually
// configured backend-side is what install_manager.py will actually act on.
function autoInstallEnabledFor(u, settings) {
  // settings.enabled -- the master pause switch (const.py's CONF_ENABLED) --
  // short-circuits this exactly like every size's own auto_install being
  // off at once, matching install_manager.py's own _async_evaluate_one:
  // showing a "will update automatically" projection while paused would be
  // actively misleading, since nothing will actually happen.
  if (!settings || settings.enabled === false || !u.installable || u.auto_install_excluded) return false;
  if (communityBlocksAutoInstall(u)) return false;
  return !!settings[`${u.version_size}_auto_install`];
}

// The real moment auto-install would happen for a "waiting" update whose
// size has auto-install enabled, even though no announcement exists yet --
// announcer.py's decide_action is deliberately sequential (2026-07-17,
// direct user feedback): the announcement itself only starts once status
// is actually "ready", so the eventual real install time is exactly
// remaining_seconds (time left until ready) plus the full announce_hours,
// not just remaining_seconds alone. Direct user feedback: once auto-install
// is on for a size, the "waiting" phase isn't really a different outcome
// from "ready and counting down" -- it's the same eventual auto-install,
// just an earlier segment of the same countdown, so it should read that
// way rather than as an unrelated, shorter-looking wait. Returns an ISO
// string (same shape as pending_install.execute_at) so callers can reuse
// relativeTime's formatting, or null when this can't/shouldn't be
// projected (not waiting, or auto-install isn't actually enabled for it).
function projectedAutoInstallTime(u, settings) {
  if (u.status !== "waiting" || u.remaining_seconds == null) return null;
  if (!autoInstallEnabledFor(u, settings) || settings.announce_hours == null) return null;
  const totalSeconds = u.remaining_seconds + settings.announce_hours * 3600;
  return new Date(Date.now() + totalSeconds * 1000).toISOString();
}

// The real moment this "waiting" update's own announcement would actually
// start (not the full auto-install time projectedAutoInstallTime above
// already covers -- this is that same countdown's own *first* leg, exactly
// remaining_seconds from now, the moment status flips to "ready" and
// announcer.py's decide_action actually creates the real announcement, see
// its own docstring). Direct user feedback, 2026-08-01: History shows
// "when it was announced" as its own fact; a "waiting" pending update
// should show "when it will be announced" the same way, not only the
// eventual final auto-install time the status text already gives. Same
// auto-install-enabled guard as projectedAutoInstallTime -- "announcement"
// isn't a real concept at all for a size that only ever installs
// manually, same reason History never shows this fact for a manual
// install either.
function projectedAnnouncementTime(u, settings) {
  if (u.status !== "waiting" || u.remaining_seconds == null) return null;
  if (!autoInstallEnabledFor(u, settings)) return null;
  return new Date(Date.now() + u.remaining_seconds * 1000).toISOString();
}

// "Ready" (green) covers two different situations: nothing planned yet
// (you'd install it yourself), or an auto-install already counting down --
// status_pending_install makes the difference visible right here, not only
// in a separate scheduled-installs section (direct user feedback: the
// green dot alone didn't hint that a countdown -- and its cancel button --
// existed at all). Plain labels only, no embedded countdown numbers --
// that lives in the trailing timer badge/pill instead (see timerBadge),
// direct user feedback: the badge should carry the "when", this text just
// the "what".
function statusText(tr, u, settings, hass) {
  // Overrides every other status, checked first -- while an install is
  // actually running, whatever "waiting"/"skipped"/etc this entity was
  // classified as a moment ago no longer describes what's happening right
  // now (direct user feedback: seeing a stale "Postponed"/"Skipped" while
  // an install you just started was already running read as wrong).
  if (updateIsInstalling(entityState(hass, u.entity_id))) return tr.status_installing;
  let text;
  // status checked first, not pending_install -- announcer.py's
  // decide_action is deliberately sequential (2026-07-17, direct user
  // feedback): the announcement only ever starts once status is actually
  // "ready", never while still "waiting". So these two are mutually
  // exclusive by construction, and the icon/text can just follow status
  // directly instead of needing to guess which one "wins".
  //
  // An absolute clock time throughout (absoluteWhen), not a relative
  // countdown -- direct user feedback (2026-07-17): "Postponed (13 hours
  // left)"/"Expected to update automatically in 4 hours" read as vague.
  // "Will update automatically" is used for both the projected and the
  // already-announced case alike, no separate hedged phrasing for the
  // former -- also direct user feedback, the distinction wasn't worth the
  // extra vagueness it added.
  //
  // absoluteWhen's own result is never capitalized (see its own comment) --
  // it's embedded mid-sentence here, so a capital "Tomorrow" would be wrong.
  if (u.status === "waiting") {
    const projected = projectedAutoInstallTime(u, settings);
    if (projected) {
      text = tr.status_pending_install(absoluteWhen(tr, projected, hass));
    } else if (u.remaining_seconds != null) {
      const readyAt = new Date(Date.now() + u.remaining_seconds * 1000).toISOString();
      text = tr.status_waiting_manual(absoluteWhen(tr, readyAt, hass));
    } else {
      text = tr.status_waiting_soon;
    }
  } else if (u.pending_install) {
    text = tr.status_pending_install(absoluteWhen(tr, u.pending_install.execute_at, hass));
  } else {
    text = tr[`status_${u.status}`] || u.status;
  }
  if (u.auto_install_excluded) text += tr.always_manual_suffix;
  return text;
}

// The Updates list row's trailing badge/pill (see _buildListRow): a
// download icon + real clock time for anything that will end up
// auto-installing itself (whether already announced, or still "waiting"
// but projected -- see projectedAutoInstallTime), a clock icon + time-
// until-ready for anything that still needs a manual click once ready.
// Same status-first reasoning, and same absolute-time preference, as
// statusText above.
// Standalone (a pill of its own, not embedded in a sentence), so its
// absoluteWhen result is capitalized here -- the one place that's correct.
function timerBadge(tr, u, settings, hass) {
  // Same override as statusText above, checked first here too -- the
  // Updates list row's own spinner (see installingIndicatorNode,
  // _buildListRow) replaces the normal countdown pill entirely while an
  // install is actually running.
  if (updateIsInstalling(entityState(hass, u.entity_id))) return { installing: true };
  if (u.status === "waiting") {
    const projected = projectedAutoInstallTime(u, settings);
    if (projected) return { icon: ICON_AUTO_DOWNLOAD, text: capitalize(absoluteWhen(tr, projected, hass, true)) };
    if (u.remaining_seconds != null) {
      const readyAt = new Date(Date.now() + u.remaining_seconds * 1000).toISOString();
      return { icon: ICON_CLOCK_OUTLINE, text: capitalize(absoluteWhen(tr, readyAt, hass, true)) };
    }
    return { icon: ICON_CLOCK_OUTLINE, text: tr.relative_soon };
  }
  if (u.pending_install) {
    return { icon: ICON_AUTO_DOWNLOAD, text: capitalize(absoluteWhen(tr, u.pending_install.execute_at, hass, true)) };
  }
  return null;
}

// Builds the aggregate sentence for a healthy/problematic count pair,
// showing both numbers when genuinely mixed instead of silently dropping
// the minority one -- direct user feedback, 2026-07-27 (found live: 2
// healthy + 1 problematic used to only ever surface as "1... problematic",
// the 2 healthy votes invisible). `perspective` picks the wording: "people"
// when there's no separate "you" row already distinguishing your own vote
// (the badge tooltip below, the dialog's other-jumps rows, or the dialog's
// own aggregate row when you haven't voted yourself), "others" when there
// is one and these counts already exclude you.
function aggregateVerdictText(tr, healthyCount, problematicCount, perspective) {
  // A closed, fixed set of six translation functions (2 perspectives x 3
  // shapes) -- an explicit lookup, not a dynamically-built tr[...] property
  // name: found by review, a typo'd key there would fail silently (calling
  // undefined) instead of at a lint/reference-check level.
  const strings =
    perspective === "others"
      ? { mixed: tr.community_verdict_others_mixed, problematic: tr.community_verdict_others_problematic, healthy: tr.community_verdict_others_healthy }
      : { mixed: tr.community_verdict_mixed, problematic: tr.community_verdict_problematic, healthy: tr.community_verdict_healthy };
  if (healthyCount > 0 && problematicCount > 0) return strings.mixed(healthyCount, problematicCount);
  if (problematicCount > 0) return strings.problematic(problematicCount);
  if (healthyCount > 0) return strings.healthy(healthyCount);
  return null;
}

// Row 1's own "you voted" rendering (see _buildCommunitySection), shared
// between the initial verdict_for_version fetch (my_verdict already set)
// and a vote just cast in this same dialog session (see _buildVoteControls'
// own onVoted callback) -- direct user feedback, 2026-07-27: casting a vote
// used to leave this row exactly as it was before ("No one's reported on
// this jump yet."), reading as a flat contradiction sitting right next to
// the vote confirmation ("Marked as healthy...") that appears right below
// it. Idempotent (removes any icon this row already has before inserting
// the new one): a vote can be changed more than once in the same dialog
// session.
function applyMyVerdictRow(verdictRow, verdictText, tr, verdict) {
  verdictText.textContent = verdict === "problematic" ? tr.community_verdict_you_problematic : tr.community_verdict_you_healthy;
  const existingIcon = verdictRow.querySelector("ha-svg-icon");
  if (existingIcon) existingIcon.remove();
  const iconEl = document.createElement("ha-svg-icon");
  iconEl.path = verdictIcon(verdict === "problematic");
  verdictRow.insertBefore(iconEl, verdictText);
  verdictRow.hidden = false;
}

// The shared "icon + one line of text" row shape every fact in the
// Community section's own infoGroup uses (the aggregate row, the
// trusted-vote row, each other-jump row) -- found by review: three near-
// identical div/ha-svg-icon/span builds in _buildCommunitySection, now one
// shared builder. `title` (the disclaimer tooltip) is optional: only the
// primary aggregate row carries it, matching the original per-row behavior.
function buildVerdictLineRow(iconPath, text, title) {
  const row = document.createElement("div");
  row.className = "dialog-community-verdict-line";
  if (title) row.title = title;
  const icon = document.createElement("ha-svg-icon");
  icon.path = iconPath;
  const span = document.createElement("span");
  span.textContent = text;
  row.appendChild(icon);
  row.appendChild(span);
  return row;
}

// One problematic vote's own reported reason (category/notes/link) as a
// single grouped block -- shared by both the generic "Reported reasons"
// list and your own reason attached right under your own vote line (see
// _buildCommunitySection), found by review, 2026-07-29 while auditing the
// whole Community section for overlap/redundancy: this used to be built
// twice with near-identical code. `trusted` marks a reason from a
// configured trusted voter (cross-checked against trusted_voters_matched,
// already available client-side, no extra fetch) so it reads as clearly
// the same vote the separate "Trusted vote: @name..." line above is
// about, instead of an unattributed, seemingly unrelated entry in the list.
function buildReasonItem(tr, reason, { trusted } = {}) {
  const baseLabel = (reason.reason_category && tr[_VOTE_REASON_LABEL_KEYS[reason.reason_category]]) || tr.vote_reason_other;
  const categoryLabel = trusted ? `${tr.community_trusted_voter_label}: ${baseLabel}` : baseLabel;
  const item = document.createElement("div");
  item.className = "community-reason-item";
  item.appendChild(buildVerdictLineRow(ICON_ALERT, categoryLabel));
  if (reason.notes) {
    const notes = document.createElement("p");
    notes.className = "hint";
    notes.textContent = reason.notes;
    item.appendChild(notes);
  }
  if (reason.link) {
    const linkRow = document.createElement("p");
    linkRow.className = "hint";
    const link = document.createElement("a");
    link.href = reason.link;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = reason.link;
    linkRow.appendChild(link);
    item.appendChild(linkRow);
  }
  return item;
}

// A second, independent pill (see _buildListRow's own verdictBadgeInfo
// parameter), read from community_verdict.py's read-only community-votes
// lookup (https://github.com/HA-Update-Manager/community-votes, added
// 2026-07-22). No badge at all when null (not HACS-identified, or not yet
// rated): a neutral pill on every single row would be more clutter than
// signal for the common "nobody's voted yet" case. The pill's own icon/
// digit stay single-number (problematic leads, asymmetric safety) -- a
// badge can't show two counts -- but the hover tooltip gets the fuller
// "both counts when mixed" treatment via aggregateVerdictText.
function verdictBadge(tr, verdict) {
  if (!verdict || (verdict.healthy_count === 0 && verdict.problematic_count === 0)) return null;
  const title = aggregateVerdictText(tr, verdict.healthy_count, verdict.problematic_count, "people");
  const isProblematic = verdict.problematic_count > 0;
  return { icon: verdictIcon(isProblematic), text: String(isProblematic ? verdict.problematic_count : verdict.healthy_count), title };
}

// The shared .dialog-rows/.row/.key/.value fact-list building block --
// used both by the pending-update section's own installed/latest version +
// impact rows and by the History facts block. A pair whose value is
// null/undefined is skipped entirely rather than shown as "unknown" (found
// by review: the two call sites used to hand-roll this same loop, one of
// them additionally skipping null values, the other not needing to).
function buildKeyValueRows(pairs) {
  const rows = document.createElement("div");
  rows.className = "dialog-rows";
  pairs.forEach(([key, value]) => {
    if (!value) return;
    const row = document.createElement("div");
    row.className = "row";
    const k = document.createElement("div");
    k.className = "key";
    k.textContent = key;
    const v = document.createElement("div");
    v.className = "value";
    v.textContent = value;
    row.appendChild(k);
    row.appendChild(v);
    rows.appendChild(row);
  });
  return rows;
}

// A link-only row, exactly like more-info-update.ts's own release_url row
// (a .row with just a .key containing an <a>, no .value) -- shared by both
// the pending-update dialog's own Release notes section and History's own
// per-entry one (appendReleaseNotesSection/ensureCommunitySection's own
// sibling code), both of which now render this link as *part of* that
// section instead of off on its own in the facts block, 2026-08-01, direct
// user feedback: "als die notes ontbreken, dan staat die link bij de
// details ipv onder het kopje 'Release notes'". null when there's no
// releaseUrl at all -- callers skip inserting it entirely in that case.
function buildReleaseUrlLinkRow(tr, releaseUrl) {
  if (!releaseUrl) return null;
  const row = document.createElement("div");
  row.className = "row";
  const k = document.createElement("div");
  k.className = "key";
  const link = document.createElement("a");
  link.href = releaseUrl;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = tr.dialog_release_announcement;
  k.appendChild(link);
  row.appendChild(k);
  return row;
}

// The "hr + Release notes heading + optional markdown + release-
// announcement link" block -- shared by the pending-update dialog's own
// Release notes section and History's per-entry equivalent (both the
// synchronous entry.release_notes path and the async GitHub-fallback
// path), 2026-08-01, replacing three separately hand-rolled copies of the
// same sequence. `before` is the reference node to insert ahead of
// (Node.insertBefore(x, null) already behaves exactly like appendChild, so
// passing null here lets a caller "append" without a separate code path).
// notes may be null/empty -- releaseUrl alone is still reason enough to
// show the section, just with only the link in it; callers must never call
// this at all when both are empty (no empty section).
//
// fromVersion/toVersion, when given, trim `notes` down to just the section
// covering toVersion before anything else happens to it -- direct user
// feedback, 2026-08-02, two real add-ons whose own changelog-based release
// notes dumped their *entire*, years-long history instead of just the
// relevant version(s): see _trimChangelogToVersion's own comment for the
// real root cause (a fragile regex in HA core itself). Safe to always pass
// these through regardless of source -- see that function's own comment
// on why this can't make an already-correct result worse.
//
// linkUrl, when given, is used for the link row instead of releaseUrl --
// found by review, 2026-08-03: a caller whose GitHub-fallback fetch
// corrected the *notes* for a downgrade (see
// _fetchGithubReleaseNotesFallback's own comment) still had no way to also
// correct the link, since this function always built it from the same
// releaseUrl also used for decoration. releaseUrl itself is still used for
// decoration (parsing owner/repo for #issue/@mention links) even when
// linkUrl is given -- both describe the same repo, only the tag differs,
// so there's nothing to correct there.
function insertReleaseNotesSection(container, before, tr, notes, releaseUrl, fromVersion, toVersion, linkUrl) {
  container.insertBefore(document.createElement("hr"), before);
  const heading = document.createElement("h3");
  heading.textContent = tr.dialog_release_notes_heading;
  container.insertBefore(heading, before);
  if (notes) {
    const markdown = document.createElement("ha-markdown");
    markdown.content = _decorateReleaseNotes(_trimChangelogToVersion(notes, fromVersion, toVersion), releaseUrl);
    container.insertBefore(markdown, before);
  }
  const linkRow = buildReleaseUrlLinkRow(tr, linkUrl || releaseUrl);
  if (linkRow) container.insertBefore(linkRow, before);
}

// A small, centered loading spinner shown right where release notes will
// land once their (possibly slow) fetch resolves -- direct user feedback,
// 2026-08-02, a follow-up to the earlier fixed-delay fix for dialogs
// visibly shifting right after opening. Confirmed against HA core's own
// native more-info dialog (more-info-update.ts's own _renderLoader/
// _markdownLoading, real source): it solves the exact same problem this
// way, not with a fixed delay -- reserving this small, stable amount of
// space the whole time content is still loading, instead of a growing gap
// suddenly appearing once it lands. Callers remove this themselves (see
// each call site's own .remove()) the moment their fetch actually
// resolves, whether or not it found anything worth showing.
function buildReleaseNotesLoader() {
  const wrap = document.createElement("div");
  wrap.className = "release-notes-loader";
  const spinner = document.createElement("ha-spinner");
  spinner.size = "small";
  wrap.appendChild(spinner);
  return wrap;
}

// The Updates tab's own empty state (matches ha-config-section-updates.ts's
// real source exactly: an outlined ha-card containing a .no-updates div)
// and the History tab's own empty state both build this same shape -- found
// by review: independently hand-rolled twice rather than shared once.
function buildEmptyStateCard(text) {
  const card = document.createElement("ha-card");
  card.outlined = true;
  const empty = document.createElement("div");
  empty.className = "no-updates";
  empty.textContent = text;
  card.appendChild(empty);
  return card;
}

// "@a", "@a and @b", "@a, @b and @c" -- used wherever more than one trusted
// username can be named at once (the History facts block, the auto-install
// pill's own tooltip, the pending-update "held back" alert). `tr.list_and`
// (not a hardcoded "and"): this joins usernames, not a fixed-language list.
function joinUsernames(tr, usernames) {
  const named = usernames.map((u) => `@${u}`);
  if (named.length <= 1) return named[0] || "";
  return `${named.slice(0, -1).join(", ")} ${tr.list_and} ${named[named.length - 1]}`;
}

// One install_log entry -> its own "how was this installed" sentence, shared
// by the History facts block (always shown) and its card's own auto-install
// pill tooltip (only shown when entry.auto_installed). `auto_install_reason`/
// `trusted_voter_usernames` are both null/empty on a manual install, or on
// any entry logged before this session's trusted-voter feature existed at
// all (see install_log.py's own docstring on this) -- the last `dialog_history_auto`
// fallback covers that older case specifically, distinct from a genuine manual
// install.
function installMethodText(tr, entry) {
  if (!entry.auto_installed) return tr.dialog_history_method_manual;
  if (entry.auto_install_reason === "trusted_voter") {
    return tr.dialog_history_method_trusted(joinUsernames(tr, entry.trusted_voter_usernames || []));
  }
  if (entry.auto_install_reason === "rules") return tr.dialog_history_method_rules;
  return tr.dialog_history_auto;
}

// Grouped by status, not by domain/category (changed 2026-07-16, direct
// user feedback: status is what you actually act on, not which
// integration something came from) -- Ready first, then Postponed, then
// Discouraged, same order as the status sort itself.
//
// Two categories pulled out of that ready/waiting/blocked bucketing
// entirely, both shown last (direct user feedback: "Skipped" at the top
// read as "heel vreemd" -- neither of these is something you act on via
// the usual ready/waiting flow, so both sink below it), in the same
// relative order and with the same precedence rule as HA's own real
// Updates page (ha-config-section-updates.ts, confirmed against its real
// source): "Skipped" first, then "Not installable" last. Critically,
// _filterSkippedUpdateEntities there additionally requires
// supportsFeature(entity, UpdateEntityFeature.INSTALL) -- so an entity
// that's both skipped and not installable counts ONLY as "Not
// installable", never "Skipped" (a real user-initiated skip -- see
// coordinator.py's own is_own_skip distinction; our own staging_skip.py
// auto-skips never show up as this status at all, they just read as
// "waiting").
function groupUpdates(tr, updates) {
  const notInstallable = updates.filter((u) => !u.installable);
  const rest = updates.filter((u) => u.installable);
  const skipped = rest.filter((u) => u.status === "skipped");
  const installable = rest.filter((u) => u.status !== "skipped");

  const byStatus = { ready: [], waiting: [], blocked: [] };
  installable.forEach((u) => {
    (byStatus[u.status] || byStatus[_FALLBACK_STATUS]).push(u);
  });

  const groups = [];
  if (byStatus.ready.length) groups.push({ key: "ready", title: tr.group_ready, entities: byStatus.ready });
  if (byStatus.waiting.length) groups.push({ key: "waiting", title: tr.group_waiting, entities: byStatus.waiting });
  if (byStatus.blocked.length) groups.push({ key: "blocked", title: tr.group_blocked, entities: byStatus.blocked });
  if (skipped.length) {
    groups.push({ key: "skipped", title: tr.group_skipped(skipped.length), entities: skipped });
  }
  if (notInstallable.length) {
    groups.push({ key: "not_installable", title: tr.group_not_installable(notInstallable.length), entities: notInstallable });
  }
  return groups;
}

// Shared by relativeTime below: picks the largest unit
// (years..seconds, via _UNIT_SECONDS) that `abs` (already-non-negative
// seconds) amounts to at least 1 of, and returns its {value, unit word}.
// Null once `abs` doesn't even reach the smallest unit (e.g. "just now").
function _breakdown(tr, abs) {
  for (let i = 0; i < _UNIT_SECONDS.length; i++) {
    const value = Math.floor(abs / _UNIT_SECONDS[i]);
    if (value >= 1) {
      const [singular, plural] = tr.units[i];
      return { value, unit: value === 1 ? singular : plural };
    }
  }
  return null;
}

// HA's own relative-time display is a live-updating component
// (ha-relative-time), which needs a Lit template to embed -- every other
// file in this project deliberately has no build step/Lit dependency (see
// the module docstring), so this is the same idea (age relative to now,
// "3 dagen geleden") computed once per render instead of ticking up live.
function relativeTime(tr, iso) {
  if (!iso) return tr.dash;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const diffSec = Math.round((Date.now() - date.getTime()) / 1000);
  const future = diffSec < 0;
  const broken = _breakdown(tr, Math.abs(diffSec));
  if (!broken) return future ? tr.relative_soon : tr.relative_just_now;
  return future ? tr.relative_future(broken.value, broken.unit) : tr.relative_ago(broken.value, broken.unit);
}

// "Today 11:24" / "Tomorrow 11:24" / "Monday 11:24" -- an absolute clock
// time, not a relative countdown. Direct user feedback (2026-07-17):
// "Postponed (13 hours left)"/"Expected to update automatically in 4
// hours" read as vague hedging; a real clock time is unambiguous and lets
// you actually plan around it, the same way a calendar invite would.
// Falls back to a short date once far enough out that "which day" alone
// stops being obviously unambiguous.
function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

// hass.locale.time_format -- a real, independent HA profile setting
// (language/system/am_pm/24, see Settings -> General), not implied by the
// display language alone. Same detection HA's own useAmPm() uses
// (confirmed against src/common/datetime/use_am_pm.ts): a fixed 22:00
// timestamp renders with "10" in it when the resolved convention is
// 12-hour. Found live: hardcoding the browser/tr locale's own default
// hour-cycle didn't necessarily match what the user actually configured.
function useAmPm(hass) {
  const timeFormat = hass && hass.locale && hass.locale.time_format;
  if (timeFormat === "am_pm") return true;
  if (timeFormat === "24") return false;
  const testLanguage = timeFormat === "language" && hass && hass.language ? hass.language : undefined;
  return new Date(2023, 0, 1, 22, 0, 0).toLocaleString(testLanguage).includes("10");
}

// Not capitalized here -- most callers embed this mid-sentence ("Ready to
// update {when}", "Will update automatically {when}"), where a capital
// "Tomorrow" would be wrong. The one caller that shows it standalone (the
// Updates list's own trailing pill) capitalizes it itself.
// `compact`, when true, drops the "today"/"tomorrow" word whenever the bare
// clock time already makes it unambiguous -- direct user feedback,
// 2026-08-01: the Updates list's own trailing timer pill (timerBadge,
// the only caller that passes this) sits right next to the entity title on
// the same row, and "Today 21:30" was often wide enough to crowd that
// title out. Left off (the default) for the dialog's own status sentence
// and the History detail rows, both of which have the room and genuinely
// benefit from the explicit word.
function absoluteWhen(tr, iso, hass, compact) {
  if (!iso) return tr.dash;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  // tr.locale, not undefined -- found live: `undefined` uses the browser's
  // own OS-level locale, which isn't necessarily hass.language (they can
  // easily disagree), producing a mixed-language result (an English
  // "today" from our own tr object right next to a Dutch weekday name
  // from the browser's own locale).
  const locale = tr.locale;
  const time = date.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit", hour12: useAmPm(hass) });
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const now = new Date();
  const dayDiff = Math.round((startOfDay(date) - startOfDay(now)) / 86400000);
  if (dayDiff === 0) {
    // A dayDiff of 0 combined with a real future timestamp guarantees this
    // moment is still later today -- the bare time can never be misread as
    // "already happened" or as some other day, so "today" never actually
    // disambiguates anything here.
    if (compact) return time;
    return tr.when_today(time);
  }
  if (dayDiff === 1) {
    // Only droppable once the target's own clock time has already passed
    // for today (e.g. it's 20:00 now and this is tomorrow's 09:00) -- only
    // then is a bare time unambiguous, since that same clock time already
    // happened today and naturally reads as its next occurrence, tomorrow.
    // If the target time hasn't passed yet today (tomorrow's 20:00 while
    // it's 08:00 now), a bare "20:00" would look identical to a same-day
    // 20:00 -- the word has to stay in that case.
    if (compact && date.getHours() * 60 + date.getMinutes() <= now.getHours() * 60 + now.getMinutes()) return time;
    return tr.when_tomorrow(time);
  }
  if (dayDiff > 1 && dayDiff < 7) return tr.when_weekday(date.toLocaleDateString(locale, { weekday: "long" }), time);
  return tr.when_date(date.toLocaleDateString(locale, { day: "numeric", month: "short" }), time);
}

// Groups install-log entries (already newest-first) into calendar-relative
// sections for the History tab: Today/Yesterday/This week/This month/
// Earlier, same "relative, not a fixed date" spirit as relativeTime/
// absoluteWhen above. Only returns buckets that actually have something in
// them, in that fixed order, so an instance with only a handful of old
// entries doesn't show four empty "This week"/"This month" headings above
// its one real "Earlier" section.
function historySections(tr, entries) {
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const today = startOfDay(new Date());
  // `key` (language-independent, unlike `label`) lets a caller single out
  // "today" specifically: see _buildHistoryList, which only shows a
  // relative time in each entry's own subtitle for that one section; every
  // other section's heading already says roughly when, so repeating it
  // (in every single row under "Yesterday"/"This week"/...) was redundant.
  const buckets = [
    { key: "today", label: tr.history_section_today, items: [] },
    { key: "yesterday", label: tr.history_section_yesterday, items: [] },
    { key: "week", label: tr.history_section_this_week, items: [] },
    { key: "month", label: tr.history_section_this_month, items: [] },
    { key: "earlier", label: tr.history_section_earlier, items: [] },
  ];
  for (const entry of entries) {
    const date = new Date(entry.installed_at);
    // NaN (unparseable/missing installed_at) and a future timestamp (clock
    // skew between this browser and whatever wrote the entry) both fall
    // through to dayDiff <= 0, the same bucket a genuinely "just now" entry
    // lands in: there's no sensible "earlier" section for something that
    // fails to parse as being in the past at all.
    const dayDiff = Number.isNaN(date.getTime()) ? 0 : Math.round((today - startOfDay(date)) / 86400000);
    if (dayDiff <= 0) buckets[0].items.push(entry);
    else if (dayDiff === 1) buckets[1].items.push(entry);
    else if (dayDiff < 7) buckets[2].items.push(entry);
    else if (dayDiff < 30) buckets[3].items.push(entry);
    else buckets[4].items.push(entry);
  }
  return buckets.filter((bucket) => bucket.items.length);
}

function entityState(hass, entityId) {
  return hass && hass.states && hass.states[entityId];
}

// Same three helpers more-info-update.ts itself exports from data/update.ts
// (confirmed against its real source, not guessed) -- reused here so the
// detail dialog's own live install-progress button/bar behave identically:
// UpdateEntityFeature.PROGRESS = 4 (homeassistant/components/update/const.py).
function latestVersionIsSkipped(state) {
  return !!(state && state.attributes.latest_version && state.attributes.skipped_version === state.attributes.latest_version);
}
function updateButtonIsDisabled(state) {
  return !!(state && state.state === "off" && !latestVersionIsSkipped(state));
}
function updateIsInstalling(state) {
  return !!(state && state.attributes && state.attributes.in_progress);
}

// The Updates list row's own trailing indicator while installing (see
// _buildListRow) -- matches ha-config-updates.ts's own real
// _renderUpdateProgress exactly: a percentage ring when the entity
// supports it and reports one, a plain spinner otherwise. Replaces the
// row's normal timer pill + chevron entirely while installing, same as
// HA's own row replaces its trailing chevron with exactly this and
// nothing else.
function installingIndicatorNode(state, tr) {
  if (state && state.attributes.update_percentage != null) {
    const ring = document.createElement("ha-progress-ring");
    ring.size = "small";
    ring.value = state.attributes.update_percentage;
    ring.label = tr.status_installing;
    return ring;
  }
  const spinner = document.createElement("ha-spinner");
  spinner.size = "small";
  spinner.ariaLabel = tr.status_installing;
  return spinner;
}

// The word "update" is baked into most update entities' own friendly_name
// (e.g. "Matter Server Update") by convention -- redundant on a page that's
// entirely about updates, so drop it as a trailing suffix rather than
// showing it on every single row.
function friendlyEntityName(hass, entityId) {
  const state = entityState(hass, entityId);
  const name = (state && state.attributes && state.attributes.friendly_name) || entityId;
  return name.replace(/\s+update$/i, "");
}

// Matches ha-config-updates.ts's own real supporting-text line (confirmed
// against source): the device's area name, via the device registry's own
// area_id, not the entity's -- "service"-type devices (helpers/virtual,
// no physical location) deliberately excluded, same as that component.
function deviceAreaName(hass, entityId) {
  const entity = hass && hass.entities && hass.entities[entityId];
  const device = entity && entity.device_id && hass.devices && hass.devices[entity.device_id];
  if (!device || device.entry_type === "service") return null;
  const area = device.area_id && hass.areas && hass.areas[device.area_id];
  return (area && area.name) || null;
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

// Shared by every ha-progress-button click handler below (cancel/skip/
// install/save) -- each one flips the button into its progress state,
// awaits its own action, then reports success/error via the button's own
// real API instead of hand-rolling the same try/catch four times.
//
// progress is reset in a `finally`, always, not only on error -- verified
// against ha-progress-button's own real source (home-assistant/frontend,
// stable tag 20260624.6): actionSuccess()/actionError() only ever toggle a
// temporary 2-second checkmark/alert overlay, they never touch `progress`
// itself, which alone drives the underlying ha-button's own spinner
// (`.loading=${this.progress}`). Every other caller of this helper never
// noticed, since cancel/skip/unskip/link/unlink all rebuild/replace the
// button within that 2-second window -- but a vote button that stays in
// place spun forever once the checkmark faded and `progress` was still
// true underneath it (found live, 2026-07-22).
async function _runProgressAction(btn, fn) {
  btn.progress = true;
  try {
    await fn();
    btn.actionSuccess();
  } catch (err) {
    btn.actionError();
  } finally {
    btn.progress = false;
  }
}

// GitHub's own markdown renderer converts `:shortcode:` text into a real
// emoji glyph (the "gemoji"/gitmoji convention); ha-markdown doesn't know
// this syntax at all and shows the literal `:boom:` text instead -- found
// live, 2026-08-01, fetching home-assistant/supervisor's own real release
// notes (_fetchGithubReleaseNotesFallback below): its own
// .github/release-drafter.yml headers every section with exactly this
// syntax (":boom: Breaking Changes", ":sparkles: New Features", etc.),
// confirmed directly against that file, not guessed. Not exhaustive (real
// gemoji has ~1800 entries, not worth bundling here, this is a vanilla,
// no-build-step file) -- covers home-assistant/supervisor's own full list
// verified live, plus the standard gitmoji.dev set commit-convention
// release notes commonly use across many other repos too. An unmapped
// shortcode is left exactly as written, same graceful "can't improve on
// it, don't break it" treatment as everything else in this fallback.
const _GITHUB_EMOJI_SHORTCODES = {
  boom: "💥", sparkles: "✨", bug: "🐛", gem: "💎", package: "📦", rocket: "🚀",
  rotating_light: "🚨", hammer_and_wrench: "🛠️", gear: "⚙️", recycle: "♻️",
  wastebasket: "🗑️", arrow_up: "⬆️", arrow_down: "⬇️", tada: "🎉", fire: "🔥",
  white_check_mark: "✅", warning: "⚠️", memo: "📝", bulb: "💡", zap: "⚡",
  lock: "🔒", unlock: "🔓", construction: "🚧", wrench: "🔧", hammer: "🔨",
  art: "🎨", lipstick: "💄", ambulance: "🚑", heavy_plus_sign: "➕",
  heavy_minus_sign: "➖", pushpin: "📌", construction_worker: "👷",
  chart_with_upwards_trend: "📈", green_heart: "💚", closed_lock_with_key: "🔐",
  alien: "👽", truck: "🚚", page_facing_up: "📄", bento: "🍱", wheelchair: "♿",
  speech_balloon: "💬", card_file_box: "🗃️", loud_sound: "🔊", mute: "🔇",
  busts_in_silhouette: "👥", children_crossing: "🚸", building_construction: "🏗️",
  iphone: "📱", egg: "🥚", see_no_evil: "🙈", camera_flash: "📸", alembic: "⚗️",
  mag: "🔍", label: "🏷️", seedling: "🌱", triangular_flag_on_post: "🚩",
  goal_net: "🥅", test_tube: "🧪", stethoscope: "🩺", x: "❌",
  heavy_check_mark: "✔️", "100": "💯", star: "⭐", star2: "🌟",
  thumbsup: "👍", thumbsdown: "👎", eyes: "👀", heart: "❤️",
};

function _replaceGithubEmojiShortcodes(text) {
  return text.replace(/:([a-z0-9_+-]+):/g, (match, name) => _GITHUB_EMOJI_SHORTCODES[name] || match);
}

// GitHub's own renderer turns bare #1234 (issue/PR references) and
// @username mentions into real links automatically; ha-markdown has no idea
// these repo-relative conventions exist and just shows the literal text --
// same class of gap as the emoji shortcodes above, direct user feedback
// 2026-08-01 ("1 en 2 klinkt goed"). Needs owner/repo (now returned
// alongside notes by update_manager/github_release_notes, see
// websocket_api.py) since #1234 is only ever meaningful relative to the
// repo the notes came from -- GitHub's own /issues/{n} URL resolves for PRs
// too, no need to know which of the two it actually is.
//
// #1234 -- negative lookbehind on \w and # themselves, so this doesn't
// match in the middle of a longer token (a version like "2026.7.4" has no
// "#" in it so that's not a real risk, but a heading like "### 1234" or an
// already-composed "##1234" would be, without the lookbehind).
const _GITHUB_ISSUE_REF_RE = /(?<![\w#])#(\d+)\b/g;
// @username -- GitHub handles are alphanumeric/hyphen, 1-39 chars, can't
// start or end with a hyphen (not enforced here, a trailing-hyphen handle
// simply doesn't exist to link to, low stakes). Negative lookbehind on
// \w/@/. so this doesn't fire mid-email-address (e.g. "user@example.com").
// Optional trailing "[bot]" captured separately -- found by review,
// 2026-08-02, checking real popular repos for more edge cases: GitHub's
// own auto-generated release notes ("bumped by @dependabot[bot] in #1234")
// are an extremely common shape, confirmed live in several popular HACS
// repos (dependabot, renovate, and this project's own mealie-actions all
// use it). A bot's own real profile lives at github.com/apps/{name}, not
// github.com/{name} (that 404s for most bots) -- without this, the "[bot]"
// suffix was also left dangling as plain text right after the link
// instead of being part of it.
const _GITHUB_MENTION_RE = /(?<![\w@.])@([a-zA-Z0-9][a-zA-Z0-9-]{0,38})(\[bot\])?/g;

function _linkifyGithubReferences(text, owner, repo) {
  if (!owner || !repo) return text;
  return text
    .replace(_GITHUB_ISSUE_REF_RE, (match, number) => `[#${number}](https://github.com/${owner}/${repo}/issues/${number})`)
    .replace(_GITHUB_MENTION_RE, (match, username, botSuffix) => {
      const url = botSuffix ? `https://github.com/apps/${username}` : `https://github.com/${username}`;
      return `[@${username}${botSuffix || ""}](${url})`;
    });
}

// Same shape github_release_notes.py's own _RELEASE_URL_RE matches
// (mirrored here, not shared -- Python and JS can't literally share a
// regex literal across the backend/frontend split). Used only to recover
// owner/repo for _linkifyGithubReferences above, for release notes that
// *aren't* fetched through _fetchGithubReleaseNotesFallback (which already
// gets owner/repo straight from the backend that resolved them) -- found
// by review, 2026-08-01: HA's own native update/release_notes call and
// History's own frozen entry.release_notes snapshot are both real GitHub
// markdown just as often (HACS's own compiled notes, for one), but neither
// went through any decoration at all, so the exact same `:boom:`/`#1234`
// text the fallback path was built to clean up still showed up literally
// whenever the *other* two sources happened to have something.
function _parseGithubReleaseUrl(url) {
  const match = url && /^https:\/\/github\.com\/([^/]+)\/([^/]+)\/releases\//.exec(url);
  return match ? { owner: match[1], repo: match[2] } : null;
}

// Applies both decorations in one place -- shared by every release-notes
// rendering path via insertReleaseNotesSection below, so notes are
// decorated exactly once regardless of which of the three sources (HA's
// own native call, the GitHub fallback, or History's frozen snapshot)
// produced them. Deliberately NOT done inside _fetchGithubReleaseNotesFallback
// itself anymore (moved here, 2026-08-01) -- doing it in two different
// places risked double-decorating whenever one path's already-decorated
// output flowed into another (e.g. re-running the linkify regex on its own
// already-linkified `[#1234](url)` output matches the bare #1234 inside
// the brackets again, since `[` isn't a word character either, producing a
// broken nested link).
function _decorateReleaseNotes(notes, releaseUrl) {
  if (!notes) return notes;
  const parsed = _parseGithubReleaseUrl(releaseUrl);
  const linkified = parsed ? _linkifyGithubReferences(notes, parsed.owner, parsed.repo) : notes;
  return _replaceGithubEmojiShortcodes(linkified);
}

// Finds the one external (not this entity's own repo) GitHub release
// reference embedded in `notes`, if there's exactly one distinct one --
// direct user feedback, 2026-08-02, two real examples: a Zigbee2MQTT
// add-on's own release notes link straight to Koenkk/zigbee2mqtt's exact
// release ("Updated Zigbee2MQTT to version
// [2.13.0](.../Koenkk/zigbee2mqtt/releases/tag/2.13.0)"), a Mealie add-on's
// own release notes link to mealie-recipes/mealie's general releases page
// with no specific tag at all ("changelog :
// https://github.com/mealie-recipes/mealie/releases"). Matches a bare URL,
// not just proper `[text](url)` markdown link syntax -- the Mealie example
// above isn't wrapped in brackets at all, just plain text containing a raw
// URL. `ownOwner`/`ownRepo` (this entity's own repo, parsed from its own
// releaseUrl) are excluded so a repo's own release notes linking back to
// its own earlier release is never mistaken for "an upstream project".
// null whenever no such link is found, or more than one *distinct* repo is
// referenced -- direct user feedback: "misschien alleen doen als er 1 link
// in zit en niet meer?", several dependency bumps mentioned at once is a
// real, common shape too, and guessing which one is "the" upstream project
// among several would be exactly the kind of unreliable guess this whole
// feature otherwise avoids.
//
// Also recognizes `github.com/OWNER/REPO/blob/BRANCH/CHANGELOG.md`, not
// just `/releases/...` -- direct user feedback, 2026-08-03, a real
// matterbridge-home-assistant-addon example: its own changelog links a
// sub-dependency's changelog this way ("Updated matterbridge-hass to
// [1.4.0](.../matterbridge-hass/blob/main/CHANGELOG.md#140-...)"), a
// different but equally common GitHub link shape. Carries no tag of its
// own (a blob link has no release tag in it at all), so the caller's own
// knownVersion fallback always applies here.
//
// A link that mentions neither GitHub shape (matterbridge's own real
// changelog links its main upstream project to a custom-domain mirror,
// `matterbridge.io/CHANGELOG.html#...`, confirmed to be the exact same
// content as github.com/Luligu/matterbridge's own CHANGELOG.md, just
// HTML-rendered) still can't be resolved to a repo -- there's no reliable,
// general way to turn an arbitrary docs domain into "this is really this
// GitHub repo" without guessing, and a one-off hardcoded domain mapping for
// this single add-on is exactly the kind of per-vendor registry this
// project avoids elsewhere (see package-tracker-card's own carrier
// detection). But it still counts as *a* distinct external reference here
// (keyed by its own URL, unresolved) so an entry mentioning both this kind
// of link and a real, resolvable GitHub one isn't mistaken for "exactly
// one" -- matterbridge's own changelog does exactly this in some entries
// (matterbridge.io alongside matterbridge-hass's real GitHub link), and
// picking the resolvable one anyway would show the *wrong* (less relevant)
// project's notes with no indication anything was left out, worse than
// showing nothing.
function _findEmbeddedUpstreamRelease(notes, ownOwner, ownRepo) {
  if (!notes) return null;
  const linkRe = /https?:\/\/[^\s)]+/g;
  const releaseRe = /^https:\/\/github\.com\/([^/]+)\/([^/]+)\/releases(?:\/(?:tag\/)?([^/]+))?/;
  const changelogBlobRe = /^https:\/\/github\.com\/([^/]+)\/([^/]+)\/blob\/[^/]+\/CHANGELOG\.md/i;
  const seen = new Map();
  let match;
  while ((match = linkRe.exec(notes)) !== null) {
    const url = match[0];
    const releaseMatch = releaseRe.exec(url);
    const blobMatch = !releaseMatch && changelogBlobRe.exec(url);
    if (!releaseMatch && !blobMatch) {
      if (!seen.has(url)) seen.set(url, null);
      continue;
    }
    const [, owner, repo, tag] = releaseMatch || blobMatch;
    if (ownOwner && ownRepo && owner.toLowerCase() === ownOwner.toLowerCase() && repo.toLowerCase() === ownRepo.toLowerCase()) {
      continue;
    }
    const key = `${owner.toLowerCase()}/${repo.toLowerCase()}`;
    // "latest" (github.com/owner/repo/releases/latest, a real, common
    // GitHub URL shape that always redirects to whatever's newest) isn't a
    // real tag at all -- found by review, 2026-08-02, while checking for
    // more edge cases: without this, it would have been tried verbatim as
    // a release tag to fetch (a repo would need to be tagging its own
    // releases with the literal string "latest" for that to ever work).
    // Treated the same as no tag at all, so the caller's own knownVersion
    // fallback kicks in instead.
    const normalizedTag = tag && tag.toLowerCase() !== "latest" ? tag : null;
    if (!seen.has(key)) seen.set(key, { owner, repo, tag: normalizedTag });
  }
  if (seen.size !== 1) return null;
  return seen.values().next().value;
}

// The index of a markdown heading line that *contains* `version` somewhere
// in it (not necessarily as the entire rest of the line) -- direct user
// feedback, 2026-08-02, two real examples: matterbridge-home-assistant-addon's
// own changelog headings read "## 2026.7.5 - 2026-07-31" (a trailing date)
// and alexbelgium's mealie add-on's own read "## v3.22.0 (2026-08-01)" (a
// trailing date in parens, plus a "v" prefix). Confirmed against HA core's
// own SupervisorAddonUpdateEntity.async_release_notes() source: its own
// regex requires the version to be the *entire* remainder of the heading
// line, so it silently fails to match either of these real, common shapes
// and falls back to returning the whole, unfiltered, often years-long
// changelog file instead -- that's the "belachelijk lange lijst" this
// exists to salvage. null when no heading anywhere mentions this version at
// all (nothing confident to find, not an error -- a raw GitHub release
// body, for one, has no reason to ever contain one).
//
// (?![.\-\d]) after the version, not a trailing \b -- found by review,
// 2026-08-02, confirmed against alexbelgium's real mealie add-on changelog:
// it has both "## v3.17.0-1 (2026-05-10)" and, right below it, "## v3.17.0
// (2026-05-09)" (same shape repeats for v3.9.2-2 through v3.9.2-5 vs plain
// v3.9.2). A trailing \b alone treats the "-" in "v3.17.0-1" as a valid
// boundary (a hyphen is a non-word character, same as a real line end), so
// searching for "v3.17.0" incorrectly matched inside "v3.17.0-1"'s own
// heading first, since that one happens to appear earlier (newer) in the
// text. This negative lookahead only accepts a match when the version
// isn't immediately continued by ".", "-", or another digit -- exactly
// what distinguishes "v3.17.0" on its own from the start of "v3.17.0-1" or
// "v3.17.00". Matterbridge's own "2026.7.5 - 2026-07-31" shape (a space
// before the dash) is unaffected either way, since the character right
// after "5" there is a space, not "-".
function _findChangelogHeadingIndex(text, version) {
  if (!version) return null;
  const escaped = version.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`^#{1,6}[ \\t].*\\b${escaped}(?![.\\-\\d])`, "m").exec(text);
  return match ? match.index : null;
}

// Splits a block of raw changelog text into one chunk per top-level heading
// it contains, each running from that heading's own line through just
// before the next one (or the end of the block for the last chunk) -- used
// by _trimChangelogToVersion's own downgrade branch below to reorder a
// contiguous newest-first block into the oldest-first reading order a
// downgrade wants, without losing or reflowing any of the original text.
function _splitIntoHeadingSections(text) {
  const headingRe = /^#{1,6}[ \t].*$/gm;
  const indices = [];
  let match;
  while ((match = headingRe.exec(text))) {
    indices.push(match.index);
  }
  if (indices.length === 0) return [text];
  return indices.map((start, i) => text.slice(start, i + 1 < indices.length ? indices[i + 1] : text.length));
}

// Trims release-notes text down to just the section covering toVersion,
// stopping right before fromVersion's own heading if that's found too --
// same "compile from target down to (not including) from_version" idea as
// github_release_notes.py's own compile_release_range, just for a raw
// changelog file's own loose markdown headings instead of GitHub's
// structured releases list, see _findChangelogHeadingIndex's own comment
// for why HA's own attempt at this regularly fails. Returns `notes`
// completely unchanged whenever toVersion's own heading can't be found at
// all -- never guess, same principle as compile_release_range: this is
// only ever a refinement of already-real content, never a source of new
// content, and applying it uniformly to every release-notes source
// (including ones that were already correctly scoped, like the GitHub
// fallback's own single-release fetch, which has no version heading in it
// at all to begin with) is safe by construction for exactly that reason.
function _trimChangelogToVersion(notes, fromVersion, toVersion) {
  if (!notes || !toVersion) return notes;
  const startIndex = _findChangelogHeadingIndex(notes, toVersion);
  if (startIndex == null) return notes;
  const afterStartLine = notes.indexOf("\n", startIndex);
  const searchFrom = afterStartLine === -1 ? notes.length : afterStartLine + 1;
  // A downgrade (fromVersion newer than toVersion) has fromVersion's own
  // heading appearing *before* toVersion's in this newest-first text, not
  // after -- found by review, 2026-08-02, while checking for more edge
  // cases: the exact same directional assumption already fixed in
  // github_release_notes.py's own compile_release_range (a real 7.1.10 ->
  // 7.1.9 downgrade), missed here at the time. Searching for fromVersion
  // only *after* toVersion's own heading (the plain case further below)
  // never finds it in that case, so this used to fall through to
  // "everything from toVersion's heading to the end of the file" --
  // confirmed live against alexbelgium's real mealie add-on changelog
  // (from=v3.10.1, to=v3.9.2 walked all the way back to its very first,
  // 2021 release). First fixed by only ever showing the one version
  // actually landed on; reconsidered the same day (direct user feedback --
  // a downgrade is really "what am I giving up by stepping back", which is
  // exactly what the versions between toVersion and fromVersion describe)
  // to show all of them instead, same idea as compile_release_range's own
  // downgrade branch: every heading from fromVersion down through
  // toVersion's own section, reordered oldest-first (you land on toVersion
  // first, then read forward through what you're losing, ending on
  // fromVersion, the version you were just on) -- the opposite of this
  // text's own newest-first order, so the matched block is split back into
  // its individual heading sections and reversed, not just sliced.
  // Deliberately NOT the same as the "fromVersion genuinely never given at
  // all" case right below, whose own to-the-end-of-file behavior is correct
  // for that different situation and must stay that way.
  const fromHeadingIndex = fromVersion ? _findChangelogHeadingIndex(notes.slice(0, startIndex), fromVersion) : null;
  if (fromHeadingIndex != null) {
    const nextHeading = /^#{1,6}[ \t]/m.exec(notes.slice(searchFrom));
    const blockEnd = nextHeading ? searchFrom + nextHeading.index : notes.length;
    return _splitIntoHeadingSections(notes.slice(fromHeadingIndex, blockEnd)).reverse().join("");
  }
  if (!fromVersion) return notes.slice(startIndex);
  // Searched only from just after toVersion's own heading line, not from
  // the very start of `notes` -- fromVersion's own heading must be a later
  // one, never toVersion's own line (a coincidental substring match there
  // would otherwise cut the result down to nothing).
  const relativeEndIndex = _findChangelogHeadingIndex(notes.slice(searchFrom), fromVersion);
  return relativeEndIndex == null ? notes.slice(startIndex) : notes.slice(startIndex, searchFrom + relativeEndIndex);
}

class UpdateManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "updates";
    this._route = null;
    this._updates = null;
    this._rolloutGroups = [];
    this._installLog = null;
    this._settings = null;
    this._defaults = null;
    this._hardExcludedEntities = [];
    this._dialogEntityId = null;
    this._dialogLastState = null;
    this._dialogStatusTextNode = null;
    this._dialogActionButtons = [];
    this._installSnapshots = null;
    this._formData = null;
    this._loadError = null;
    // Release notes for an already-published version/entry don't change --
    // direct user feedback, 2026-08-01: "als ik een dialog vaker achter
    // elkaar open moet hij die content telkens opnieuw ophalen. overbodig
    // toch?" Cleared only by a full page reload (no explicit eviction),
    // shared by _fetchGithubReleaseNotesFallback and
    // _fetchNativeReleaseNotes below (different key prefixes, one Map).
    // Deliberately NOT extended to the community verdict fetch
    // (verdict_for_version) -- that one stays uncached on purpose, votes
    // genuinely can change between two dialog opens, see its own
    // websocket_api.py docstring ("the right price for always tell the
    // truth right now").
    this._releaseNotesCache = new Map();
    // translations.js, loaded dynamically (see _loadTranslations' own
    // comment) -- null until _translationsReady resolves. _updateShell/
    // _renderContent below self-guard on this (deferring to
    // _translationsReady rather than rendering with nothing to read text
    // from) since connectedCallback/set hass/set route can each be the
    // very first thing HA's panel resolver calls, in no guaranteed order.
    this._translations = null;
    this._translationsReady = _translationsPromise.then((t) => {
      this._translations = t;
    });
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._initialLoad();
    } else {
      this._updateShell();
      this._updateDialogProgress();
      this._updateInstallProgress();
    }
  }

  get hass() {
    return this._hass;
  }

  get _tr() {
    if (!this._translations) return null;
    return this._translations[this._hass && this._hass.language] || this._translations.en;
  }

  set narrow(narrow) {
    this._narrow = narrow;
    this._updateShell();
  }

  // Set by HA's panel resolver on every navigation under this panel's own
  // URL (e.g. /update-manager/history) -- the same mechanism every other
  // HA settings page uses, see hass-router-page.ts/compute-route.ts.
  set route(route) {
    const path = (route && route.path) || "";
    if ((path === "" || path === "/") && route && route.prefix) {
      // Land on the Updates tab by default, same as e.g. /config redirecting
      // to its first sub-page -- don't leave the bare panel URL tab-less.
      //
      // this._route itself is corrected to the redirected path too, not
      // just the visible URL and this._tab -- found by review (this is the
      // real root cause behind two earlier, unsuccessful fix attempts):
      // hass-tabs-subpage's own active-tab matching (willUpdate, confirmed
      // against its real source) compares `route.prefix + route.path`
      // against each tab's own full path. Leaving this._route's path as ""
      // (or "/") meant that comparison never matched any tab at all on the
      // bare panel URL, even though our own _tab/content already corrected
      // themselves -- no tab ever looked active on first opening the panel.
      history.replaceState(null, "", `${route.prefix}/updates`);
      this._route = { ...route, path: "/updates" };
      this._tab = "updates";
    } else {
      this._route = route;
      this._tab = tabForPath(path);
    }
    this._updateShell();
    this._renderContent();
  }

  // Only ever read for its own config.integration_version (see panel.py's
  // own comment on why that's sourced from the real manifest.json instead
  // of a second, hand-maintained JS constant like the sibling Lovelace
  // cards' own CARD_VERSION) -- _buildVersionLink below is the one reader.
  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    this._ensureShell();
    this._updateShell();
    this._renderContent();
  }

  async _initialLoad() {
    this._ensureShell();
    this._updateShell();
    this._renderContent();
    await this._loadAll();
    // A second _updateShell() call, not just the one above -- found live:
    // the tab bar's active-tab highlight still didn't show on first load.
    // Whatever the exact property-setter ordering HA's panel resolver uses
    // for hass/narrow/route on first mount, every one of them is
    // guaranteed to have already fired for real by the time this
    // WebSocket round-trip finishes, so re-pushing route here (as its own
    // fresh object, see _updateShell's own comment) is a safe, late
    // catch-up regardless of what raced what earlier.
    this._updateShell();
    this._renderContent();
  }

  async _loadAll() {
    if (!this._hass) return;
    try {
      const [updatesResp, logResp, settingsResp] = await Promise.all([
        this._hass.callWS({ type: "update_manager/updates" }),
        this._hass.callWS({ type: "update_manager/install_log" }),
        this._hass.callWS({ type: "update_manager/get_settings" }),
      ]);
      this._updates = updatesResp.updates;
      this._rolloutGroups = updatesResp.rollout_groups || [];
      this._installLog = logResp.entries.slice().reverse();
      this._settings = settingsResp.options;
      this._defaults = settingsResp.defaults;
      this._hardExcludedEntities = settingsResp.hard_excluded_entities || [];
      if (!this._formData) {
        // const.py's own DEFAULT_WAIT_DAYS as the silent fallback for
        // anything not actually stored yet, not an empty object --
        // otherwise a field missing from this._settings (a fresh install,
        // or one of this session's field renames leaving old keys behind)
        // ends up completely absent from _formData, and pickKnownSettings
        // then leaves it out of the save payload entirely: save_settings's
        // vol.Required(...) schema rejected that outright ("required key
        // not provided"), found live. excluded_entities/trusted_voters
        // aren't part of it (plain lists, not wait/auto-install tuning
        // values), so both need their own explicit empty-array default the
        // same way.
        const fallback = this._defaults || {};
        this._formData = {
          enabled: true,
          excluded_entities: [],
          trusted_voters: [],
          hide_postponed: true,
          ...fallback,
          ...pickKnownSettings(this._settings),
        };
      }
      this._loadError = null;
    } catch (err) {
      this._loadError = (err && err.message) || String(err);
    }
  }

  // The same "hass-notification" toast event real HA pages use
  // (src/util/toast.ts's showToast, confirmed against source: a bubbling,
  // composed CustomEvent, so dispatching it here reaches HA's real toast
  // manager the same way) -- shared by _refresh's own confirmation and the
  // Install button's error handler below, rather than each building the
  // same CustomEvent by hand.
  _showToast(message) {
    this.dispatchEvent(
      new CustomEvent("hass-notification", {
        detail: { message },
        bubbles: true,
        composed: true,
      })
    );
  }

  // Last-resort release-notes source, shared by both the pending-update
  // dialog and the History section below: GitHub's own release body for
  // this exact release_url, fetched server-side (update_manager/
  // github_release_notes, see websocket_api.py's own docstring on that
  // handler for the full reasoning). null on anything -- no release_url,
  // an unparseable one, a 404, a network error -- same graceful "nothing to
  // add" treatment the other two release-notes sources already get, never
  // surfaced as an error to the user (this is a nice-to-have enrichment,
  // not something a failure here should be loud about).
  //
  // fromVersion, when given, asks the backend to compile notes across every
  // release skipped since that version instead of just the newest one (see
  // compile_release_range's own docstring) -- direct user feedback,
  // 2026-08-01: skipping straight from an old installed version otherwise
  // only ever shows the single newest release's own notes.
  //
  // toVersion, when given, asks the backend to correct releaseUrl's own tag
  // to whatever release actually matches this version before fetching
  // anything -- direct user feedback, 2026-08-01, found on a real downgrade
  // (2.0 -> 1.0): releaseUrl reflects "latest available", not "what was
  // actually installed" (true for HACS specifically), so a downgrade used
  // to show the newer version's own notes instead of the version actually
  // ended up on. Always pass the version this fetch is actually *for*
  // (u.latest_version for the pending dialog, entry.to_version for
  // History) -- never assume releaseUrl's own embedded version already
  // matches it.
  // Cached in this._releaseNotesCache (see the constructor's own comment)
  // -- keyed on every input that can change the result, so a later call
  // with a different fromVersion/toVersion (a newly-available version, a
  // different History entry reusing the same repo) never serves another
  // jump's cached notes. Decoration (emoji/linkify) happens downstream, in
  // insertReleaseNotesSection -- not here, not anymore (found by review,
  // 2026-08-01): doing it in this function only ever decorated *this*
  // source's notes, leaving update/release_notes and History's own
  // entry.release_notes undecorated even though both are just as often
  // real GitHub markdown.
  //
  // A transient failure (network hiccup, rate limit, a 404 on an
  // unexpectedly-renamed repo) is deliberately NOT cached -- found by
  // review, 2026-08-01: caching the promise unconditionally meant a single
  // bad request poisoned this exact cache key for the rest of the panel's
  // lifetime, indistinguishable from a confirmed "this release genuinely
  // has no notes" result. Only a result that actually resolved (even to
  // null, meaning the fetch succeeded but truly found nothing) is worth
  // remembering; only a call that itself threw deserves a real retry next
  // time.
  // Returns { notes, correctedUrl }, not just notes -- found by review,
  // 2026-08-03: a to_version match corrects the *notes* to the version
  // actually being described (see the backend's own docstring), but the
  // "Read release announcement" link callers build from their own,
  // uncorrected releaseUrl was never updated to match, so it kept pointing
  // at the newest release even once the notes right above it correctly
  // described an older one, for a downgrade. correctedUrl is that match's
  // own html_url, null whenever no correction happened (no to_version, or
  // no match found) -- callers substitute it in place of their own
  // releaseUrl for the link specifically, see insertReleaseNotesSection's
  // own linkUrl parameter.
  async _fetchGithubReleaseNotesFallback(releaseUrl, fromVersion, toVersion) {
    if (!releaseUrl) return { notes: null, correctedUrl: null };
    const cacheKey = `github:${releaseUrl}:${fromVersion || ""}:${toVersion || ""}`;
    if (this._releaseNotesCache.has(cacheKey)) return this._releaseNotesCache.get(cacheKey);
    let result;
    try {
      result = await this._hass.callWS({
        type: "update_manager/github_release_notes",
        release_url: releaseUrl,
        ...(fromVersion ? { from_version: fromVersion } : {}),
        ...(toVersion ? { to_version: toVersion } : {}),
      });
    } catch {
      return { notes: null, correctedUrl: null };
    }
    const resolved = { notes: (result && result.notes) || null, correctedUrl: (result && result.corrected_url) || null };
    this._releaseNotesCache.set(cacheKey, resolved);
    return resolved;
  }

  // Same cache, a "native" key prefix so it can never collide with
  // _fetchGithubReleaseNotesFallback's own "github" one -- HA's own
  // update/release_notes websocket command has no from/to params of its
  // own (it always reflects the entity's current state), so version is
  // included here explicitly instead, same reasoning as toVersion above:
  // a newly-available version must never serve a stale, older version's
  // own cached notes. Same "don't cache a transient failure" reasoning as
  // _fetchGithubReleaseNotesFallback above too.
  async _fetchNativeReleaseNotes(entityId, version) {
    const cacheKey = `native:${entityId}:${version}`;
    if (this._releaseNotesCache.has(cacheKey)) return this._releaseNotesCache.get(cacheKey);
    let notes;
    try {
      notes = await this._hass.callWS({ type: "update/release_notes", entity_id: entityId });
    } catch {
      return null;
    }
    this._releaseNotesCache.set(cacheKey, notes);
    return notes;
  }

  // "Also see: OWNER/REPO's own release notes" -- direct user feedback,
  // 2026-08-02: many add-ons are thin wrappers around an external upstream
  // project, and their own release notes are often just a one-line "bumped
  // to X" note pointing at the real, more detailed upstream notes (see
  // _findEmbeddedUpstreamRelease's own comment for the two real examples
  // this was built from). If that embedded link already names a specific
  // tag, that's used directly, no guessing needed; if it's just a bare
  // releases-listing link with no tag, `knownVersion` (whatever version
  // this section already describes) is tried as a candidate tag instead,
  // since an add-on's own version number frequently *is* the upstream tag
  // verbatim (confirmed live for mealie-recipes/mealie). Reuses
  // _fetchGithubReleaseNotesFallback's own cache, so re-opening the same
  // dialog doesn't re-fetch this either. Never chases a second link inside
  // whatever this fetch itself returns (one level deep only), and does
  // nothing visible at all -- no error, no empty section -- whenever no
  // link is found, more than one distinct repo is referenced, or the
  // guessed tag 404s, same graceful "nothing to add" treatment as every
  // other release-notes enrichment in this file.
  //
  // Scanned on the same fromVersion/toVersion-trimmed text the Release
  // notes section itself displays, not the raw, untrimmed `notes` -- found
  // by review, 2026-08-03: an add-on entity's own native release_notes can
  // itself be the *entire*, years-long changelog file (the very fallback
  // _trimChangelogToVersion exists to salvage, see its own comment), which
  // would otherwise let this function's "exactly one distinct reference"
  // check see links from every version ever logged, not just the one jump
  // actually being shown -- both diluting real matches with old, irrelevant
  // ones and risking a false "exactly one" once matterbridge.io-style
  // unresolved links are counted too (see _findEmbeddedUpstreamRelease's
  // own comment).
  async _appendUpstreamReleaseNotes(container, before, tr, notes, releaseUrl, fromVersion, toVersion) {
    const scoped = _trimChangelogToVersion(notes, fromVersion, toVersion);
    const ownRepo = _parseGithubReleaseUrl(releaseUrl);
    const found = _findEmbeddedUpstreamRelease(scoped, ownRepo && ownRepo.owner, ownRepo && ownRepo.repo);
    if (!found) return;
    const tag = found.tag || toVersion;
    if (!tag) return;
    const upstreamUrl = `https://github.com/${found.owner}/${found.repo}/releases/tag/${tag}`;
    const { notes: upstreamNotes } = await this._fetchGithubReleaseNotesFallback(upstreamUrl, null, null);
    if (!upstreamNotes) return;
    const label = document.createElement("p");
    const strong = document.createElement("strong");
    strong.textContent = tr.dialog_upstream_release_notes(`${found.owner}/${found.repo}`);
    label.appendChild(strong);
    container.insertBefore(label, before);
    const markdown = document.createElement("ha-markdown");
    markdown.content = _decorateReleaseNotes(upstreamNotes, upstreamUrl);
    container.insertBefore(markdown, before);
  }

  async _refresh() {
    // Re-fetches our own already-computed state (updates/history/settings)
    // and redraws, plus (see the homeassistant.update_entity call below)
    // actually makes every underlying integration poll for a brand new
    // version right now, instead of only ever reflecting whatever this
    // integration's own coordinator already knew, including anything the
    // 15-minute periodic recheck happened to pick up since the page was
    // last loaded. Found live: clicking it gave no visible feedback at all,
    // indistinguishable from doing nothing -- the spin+disable below can
    // still be too brief to notice on a fast connection, so this also
    // fires the same "hass-notification" toast (see _showToast) real HA
    // pages use for their own refresh confirmations.
    const btn = this._subpageEl && this._subpageEl.querySelector(".refresh-btn");
    if (btn) btn.disabled = true;
    const icon = btn && btn.querySelector("ha-icon");
    if (icon) icon.classList.add("spinning");
    try {
      // Same service HA's own Settings > Updates page calls for its "Check
      // for updates" action (verified against home-assistant/frontend's own
      // src/data/update.ts, checkForEntityUpdates) -- forces every update.*
      // entity on the system to actually re-poll its own integration for a
      // new version, not just refresh whatever this integration's own
      // coordinator already had cached. Every entity, not just the ones
      // this integration currently tracks as pending: a brand-new update
      // that just became available wouldn't be "pending" anywhere yet, the
      // whole point of checking. Direct user feedback, 2026-08-01 ("kan die
      // knop ook 'check for updates' doen? zoals ha zelf doet").
      //
      // Excludes anything already installing, unlike HA's own
      // checkForEntityUpdates (confirmed against its real source, it
      // doesn't make this exception either) -- direct user feedback,
      // 2026-08-02: "als een update in progress is, ik op refresh druk en
      // refreshen eerder klaar is dan de update, dan verdwijnt de spinner".
      // Forcing a fresh poll on an entity that's busy installing risks the
      // underlying integration reporting a momentarily inconsistent state
      // while it's occupied (integration-specific, outside anything we
      // control), which our own coordinator can misread as "no longer
      // pending" and drop from its cache entirely -- taking this row, and
      // its spinner, down with it. There's no real reason to check for an
      // even newer version on something already mid-install anyway.
      const updateEntityIds = Object.keys(this._hass.states).filter(
        (entityId) => entityId.startsWith("update.") && !updateIsInstalling(this._hass.states[entityId])
      );
      // Awaited before _loadAll(), not alongside it: direct user feedback,
      // 2026-07-25 ("als ik op de refresh knop druk wil ik dat hij ook de
      // meest recente info van de votes naar binnen haalt") -- community
      // verdicts otherwise stay cached for up to an hour
      // (community_verdict.py's own _REFRESH_INTERVAL), same as any other
      // background-refreshed fact. This forces a fresh fetch for every
      // currently-pending entity and patches the coordinator's own cache
      // *before* _loadAll()'s own update_manager/updates call reads it, so
      // this one manual click is guaranteed to show genuinely current
      // counts, not whatever was last cached. Also reconciles my_votes.py's
      // entire local record against live community-votes data server-side
      // (websocket_api.py's own refresh_community_verdicts handler), an
      // explicit "tell me the truth now" action that bypasses the usual
      // grace period a passive dialog-open respects.
      //
      // Run alongside (not after) the update_entity dispatch + its 15s wait
      // below, not sequentially before _loadAll() the way it first was --
      // found by review, 2026-08-01: the two are otherwise unrelated (one's
      // about newly-available versions, the other about vote data), so
      // there's nothing forcing the verdict refresh to wait for the full
      // 15s update_entity settle time to even start. Both still finish
      // before _loadAll() reads either's result.
      const verdictRefresh = this._hass.callWS({ type: "update_manager/refresh_community_verdicts" });
      // A no-op .catch() here, not the only error handling for this call --
      // found by review, 2026-08-01: without it, a quick rejection (a fast
      // "not_found" from the backend, say) fires the browser's own
      // unhandled-rejection console warning well before the real `await
      // verdictRefresh` below ever runs (that only happens after the
      // update_entity call and its full 15s wait), since no handler was
      // attached yet at the point the engine checks. The real handling
      // (propagating into this method's own try/finally) still happens at
      // that later await -- this only silences the premature warning.
      verdictRefresh.catch(() => {});
      if (updateEntityIds.length) {
        this._showToast(this._tr.checking_updates_toast);
        await this._hass.callService("homeassistant", "update_entity", { entity_id: updateEntityIds });
        // There's no reliable way to know when every one of those polls has
        // actually finished (same reasoning HA's own checkForEntityUpdates
        // uses for its own identical wait) -- 15s is a practical, empirical
        // balance between giving slower integrations (a HACS repo's own
        // GitHub API round-trip, for one) time to land, and not leaving the
        // button spinning indefinitely.
        await new Promise((resolve) => setTimeout(resolve, 15000));
      }
      await verdictRefresh;
      await this._loadAll();
      this._renderContent();
      this._showToast(this._tr.refreshed_toast);
    } finally {
      if (btn) btn.disabled = false;
      if (icon) icon.classList.remove("spinning");
    }
  }

  // Builds the page chrome once: hass-tabs-subpage, the same layout
  // component /config/devices etc. use (menu button, title, tab bar wired
  // to real HA routing) -- built once and only had its properties updated
  // afterwards, not recreated every render, so it (and any child state like
  // scroll position) survives tab switches and data refreshes.
  _ensureShell() {
    // Deferred, not rendered with nothing to read text from, whenever this
    // fires (via connectedCallback or _initialLoad) before translations.js
    // has actually resolved -- see the constructor's own comment. Re-enters
    // itself once ready; _shellBuilt below still makes the real build run
    // exactly once either way.
    if (!this._translations) {
      this._translationsReady.then(() => this._ensureShell());
      return;
    }
    if (this._shellBuilt) return;
    this._shellBuilt = true;

    this.shadowRoot.innerHTML = `<style>${this._styles()}</style>`;

    const subpage = document.createElement("hass-tabs-subpage");
    subpage.tabs = TAB_DEFS.map((t) => ({ path: t.path, name: this._tr[t.nameKey], iconPath: t.iconPath }));
    // This is a top-level sidebar panel, not a page nested under another
    // one. Without mainPage=true, hass-tabs-subpage's own default
    // (confirmed against its real source) is a back-arrow that navigates
    // browser history, only falling back to the menu icon on its own if
    // history.state?.root happens to be true, which isn't guaranteed for
    // a panel opened directly from the sidebar. Direct user feedback:
    // caught this should be the hamburger/menu icon, like every other
    // top-level HA panel, not a back arrow.
    subpage.mainPage = true;

    const refreshBtn = document.createElement("button");
    refreshBtn.className = "icon-btn refresh-btn";
    refreshBtn.title = this._tr.refresh;
    refreshBtn.setAttribute("slot", "toolbar-icon");
    refreshBtn.innerHTML = `<ha-icon icon="mdi:refresh"></ha-icon>`;
    refreshBtn.addEventListener("click", () => this._refresh());
    subpage.appendChild(refreshBtn);

    const content = document.createElement("div");
    content.className = "content";
    subpage.appendChild(content);

    this.shadowRoot.appendChild(subpage);
    this._subpageEl = subpage;
    this._contentEl = content;

    // Built once and reused, not recreated per click -- the per-entity
    // detail dialog (see _openDetailDialog): a real ha-dialog, matching how
    // every other HA dialog closes (scrim click, Escape) without wiring
    // that up by hand.
    const dialog = document.createElement("ha-dialog");
    dialog.addEventListener("closed", () => {
      dialog.open = false;
      this._dialogEntityId = null;
      // Found by review: this used to leave a stale historyEntry behind,
      // harmless today (every read of it is guarded by _dialogEntityId
      // first) but dead state that's an easy trap for a future reader.
      this._dialogHistoryEntry = null;
    });
    this.shadowRoot.appendChild(dialog);
    this._dialogEl = dialog;
  }

  _updateShell() {
    // Same reasoning as _ensureShell's own guard above -- callers (e.g.
    // connectedCallback) call all three of _ensureShell/_updateShell/
    // _renderContent back to back, synchronously; if translations weren't
    // ready yet, _ensureShell's own deferred re-invocation runs (and
    // resolves _subpageEl) *after* this exact call already returned, so
    // this needs its own deferred re-invocation too, not just the
    // pre-existing !this._subpageEl guard below (that one alone would
    // leave the panel blank forever: nothing else re-triggers this call
    // once _ensureShell finally does build the shell). Promise .then()
    // callbacks fire in registration order, so _ensureShell's own deferred
    // continuation (registered first by every caller) always resolves
    // before this one -- _subpageEl is guaranteed to exist by the time
    // this re-invocation actually runs.
    if (!this._translations) {
      this._translationsReady.then(() => this._updateShell());
      return;
    }
    if (!this._subpageEl) return;
    this._subpageEl.hass = this._hass;
    this._subpageEl.narrow = this._narrow;
    // Only ever forward a real route, never a {prefix:"",path:""} filler --
    // found live: HA's panel resolver sets `hass` before `route`, so
    // _initialLoad's first _updateShell() call used to run before the real
    // route was known yet, handing hass-tabs-subpage an empty route right
    // at first paint.
    //
    // A fresh object every time, not the same this._route reference passed
    // through unchanged -- hass-tabs-subpage only recomputes which tab
    // looks active (its own _activeTab, see its willUpdate) when Lit's
    // default change detection (plain !==) sees its `route` property
    // actually change. _updateShell can run multiple times (hass/narrow/
    // route setters all call it) reusing the same this._route object in
    // between real navigations, which Lit would then treat as "unchanged"
    // and skip -- found live: the tab bar never visibly showed which tab
    // was current at all.
    if (this._route) this._subpageEl.route = { ...this._route };
  }

  // Fired on every hass push (see set hass), same as more-info-update.ts's
  // own reactive stateObj -- but touches the DOM only when the currently
  // open dialog's own entity actually has a new state object (HA replaces
  // only the changed entity's own nested state, so a cheap !== catches
  // real changes without re-rendering on every unrelated entity's push).
  // Purely the currently-open dialog's own DOM (progress bar, status text,
  // Install/Skip/Cancel/Unskip buttons) -- reloading Updates/History once
  // an install actually finishes is handled globally instead (see
  // _updateInstallProgress below), not duplicated here, since that also
  // has to work when the dialog isn't even open.
  // No progress bar of our own to redraw here anymore (see "Open update",
  // 2026-07-29: the actual install/its live progress happens in HA's own
  // dialog now). Direct user feedback, 2026-08-01: "als hij installing is
  // wil ik niet onze dialog tonen maar direct die van ha waarin de
  // progress zichtbaar is" -- so as of this method's own redirect below,
  // this dialog is never actually left open and visible once an install
  // starts, however it got started (this dialog's own former Install
  // button, "Update all", auto-install, or the rollout queue). What
  // follows the redirect (disabling Skip/Cancel/Unskip, the status alert's
  // own live "Installing…" text) is effectively unreachable for that
  // reason, kept only for the brief window before HA's own dialog-close
  // animation actually finishes and this._dialogEntityId is cleared -- see
  // that redirect's own comment.
  _updateDialogProgress() {
    if (!this._dialogEntityId) return;
    const state = entityState(this._hass, this._dialogEntityId);
    if (state === this._dialogLastState) return;
    const wasInstalling = updateIsInstalling(this._dialogLastState);
    this._dialogLastState = state;

    const installing = updateIsInstalling(state);

    // Same redirect _openDetailDialog itself already does at open time
    // (see its own comment) -- here for the case an install starts (or
    // resumes, e.g. "Update all", auto-install, the rollout queue) while
    // this exact entity's own dialog happens to already be open. Only on
    // the actual not-installing-to-installing transition (wasInstalling
    // guards this), not on every later push while it's still installing --
    // and only for the live pending view, never a History view
    // (_dialogHistoryEntry set): a past, already-completed entry has
    // nothing to do with whatever this same entity might be doing now.
    if (installing && !wasInstalling && !this._dialogHistoryEntry) {
      this._dialogEl.open = false;
      this._openMoreInfo(this._dialogEntityId);
      return;
    }

    for (const btn of this._dialogActionButtons) btn.disabled = installing;

    if (this._dialogStatusTextNode) {
      const tr = this._tr;
      const u = this._updates && this._updates.find((x) => x.entity_id === this._dialogEntityId);
      if (u) this._dialogStatusTextNode.textContent = statusText(tr, u, this._settings, this._hass);
    }
  }

  // Fired on every hass push (see set hass), independent of whether the
  // detail dialog is open -- two things every entity currently in
  // this._updates is checked for: whether it just started/stopped
  // installing (drives the Updates list's own spinner, see
  // installingIndicatorNode/_buildListRow), and whether its
  // installed_version just changed. The latter is the one signal every
  // real install eventually produces, even for entities that never bother
  // reporting in_progress at all -- found live ("het lijkt wel alsof de
  // update manager nooit up to date is"): relying on the in_progress
  // transition alone (the dialog's own former approach) left both the
  // dialog and this list looking stuck on those entities, and the list
  // never refreshed at all unless the dialog happened to be open for that
  // exact entity.
  _updateInstallProgress() {
    if (!this._updates) return;
    const previous = this._installSnapshots || new Map();
    const next = new Map();
    let installingChanged = false;
    let anyVersionChanged = false;
    let dialogEntityVersionChanged = false;
    for (const u of this._updates) {
      const state = entityState(this._hass, u.entity_id);
      const installing = updateIsInstalling(state);
      const installedVersion = state && state.attributes && state.attributes.installed_version;
      // Direct user feedback, 2026-08-02: "als er op de achtergrond ontdekt
      // wordt dat er een nieuwe update beschikbaar voor is, dan ververst de
      // dialog niet" -- this loop already caught installed_version changing
      // (an install actually finishing), but never latest_version changing
      // on its own (a newer version being discovered while nothing gets
      // installed), so a dialog already open for that exact entity just
      // kept showing the stale "New version" fact indefinitely, with
      // nothing short of closing and reopening it ever re-reading the truth.
      const latestVersion = state && state.attributes && state.attributes.latest_version;
      next.set(u.entity_id, { installing, installedVersion, latestVersion });
      const prev = previous.get(u.entity_id);
      if (!prev) continue;
      if (prev.installing !== installing) installingChanged = true;
      if (prev.installedVersion !== installedVersion || prev.latestVersion !== latestVersion) {
        anyVersionChanged = true;
        if (u.entity_id === this._dialogEntityId) dialogEntityVersionChanged = true;
      }
    }
    this._installSnapshots = next;
    if (dialogEntityVersionChanged) {
      // _afterDialogAction already does exactly loadAll + reopen-in-place
      // (if this._dialogEntityId still matches) + renderContent -- direct
      // user feedback, 2026-07-27 ("na het installeren van een update
      // vanuit een dialog verwacht je dat je het history-dialog te zien
      // krijgt voor die entity"). The Install button itself is deliberately
      // fire-and-forget (see its own click handler's comment: awaiting it
      // either closed the dialog too early or left it stuck spinning for a
      // slow install), so nothing previously told an already-open dialog
      // its own install had actually finished -- it kept showing the stale
      // pending facts and an enabled Install button indefinitely. Reusing
      // this method rather than re-inlining its own loadAll/reopen/render
      // sequence a second time.
      this._afterDialogAction(this._dialogEntityId);
    } else if (anyVersionChanged) {
      // Gated on the Updates tab, same as installingChanged right below --
      // found live, 2026-08-07, direct user feedback: typing in the
      // Settings tab's trusted-voters field (a free-text ha-form) could
      // lose focus mid-word, "niet altijd, soms". Root cause: this branch
      // used to call _renderContent() unconditionally whenever *any*
      // tracked update entity's version changed anywhere in the system --
      // entirely unrelated to whatever tab is actually showing, and with
      // no regard for a field the user might be actively editing.
      // _renderContent() wipes and rebuilds the current tab's whole DOM
      // (innerHTML = ""), which replaces the <ha-form> element itself,
      // not just its value -- the browser can't keep focus on a node that
      // no longer exists. Settings' own content never depends on
      // this._updates at all, so skipping the render there loses nothing:
      // _loadAll() still refreshes the underlying data in the background,
      // and switching to Updates/History later renders it fresh anyway.
      this._loadAll().then(() => {
        if (this._tab === "updates") this._renderContent();
      });
    } else if (installingChanged && this._tab === "updates") {
      this._renderContent();
    }
  }

  // Used to be a single batched update.install *service* call, matching
  // ha-config-section-updates.ts's own _updateAll exactly (HA's own
  // services already support a list target for entity_id). Changed
  // 2026-07-22: that raw service call bypassed update_manager/install
  // entirely, so a Zigbee rollout queue (see rollout_manager.py) had no
  // way to gate "Update all" at all. One update_manager/install call per
  // entity instead: each needs its own independent dispatch-or-queue
  // decision, RolloutManager decides per entity_id, not per batch. Still
  // fire-and-forget beyond a try/catch per entity for the error toast, no
  // loading state of its own, no per-entity clear-skip handling either,
  // since a "ready" entity is never skipped/postponed by our own grouping
  // to begin with.
  async _updateAllInGroup(group) {
    const entityIds = group.entities
      .filter((u) => !updateIsInstalling(entityState(this._hass, u.entity_id)))
      .map((u) => u.entity_id);
    if (!entityIds.length) return;
    // Dispatched concurrently, not one at a time: each entity's own
    // dispatch-or-queue decision is fully independent (RolloutManager's own
    // gate already provides correct ordering for anything Zigbee-paced, see
    // rollout_manager.py), so serializing these on the client would only
    // slow "Update all" down for no correctness benefit.
    const results = await Promise.allSettled(
      entityIds.map((entityId) => this._hass.callWS({ type: "update_manager/install", entity_id: entityId }))
    );
    results.forEach((result, i) => {
      if (result.status !== "rejected") return;
      const entityId = entityIds[i];
      const err = result.reason;
      let message = (err && err.message) || String(err);
      if (message.includes(entityId)) {
        message = message.split(entityId).join(friendlyEntityName(this._hass, entityId));
      }
      this._showToast(message);
    });
  }

  // Reloads our own data and rebuilds this same dialog in place, instead
  // of closing it -- direct user feedback: closing after Cancel/Skip/Clear
  // skipped hid the very confirmation that the action actually took
  // effect (and needed a manual page refresh before the underlying list
  // caught up too, on top of that). _openDetailDialog itself already
  // tolerates the entity's status having changed (or even not being
  // tracked at all anymore) since it always rebuilds from fresh data, and
  // re-setting dialog.open to the value it already has is a no-op, not a
  // close/reopen flicker.
  async _afterDialogAction(entityId) {
    await this._loadAll();
    // this._dialogHistoryEntry, not a bare entityId re-open: preserves
    // which History entry's card should stay expanded across this refresh
    // (see _openDetailDialog's own entries.forEach/defaultExpandIndex,
    // matched by installed_at+to_version, not object identity -- the
    // this._loadAll() above just replaced this._installLog with a fresh
    // array of fresh objects). Without this, any action button (Cancel/
    // Skip/Unskip/etc succeeding) would silently reset back to the most
    // recent entry instead of whichever one the user actually had open.
    if (this._dialogEntityId === entityId) this._openDetailDialog(entityId, this._dialogHistoryEntry);
    this._renderContent();
  }

  _renderContent() {
    // Same reasoning as _updateShell's own guard above.
    if (!this._translations) {
      this._translationsReady.then(() => this._renderContent());
      return;
    }
    if (!this._contentEl) return;
    // Found by review: the device-flow poll (_buildCommunityCard) used to
    // only ever get cleared by rebuilding the Settings card itself, so
    // switching to another tab mid-poll (waiting for GitHub approval) left
    // it running against a now-detached statusContainer, still popping a
    // "timed out"/"failed" toast on whatever tab the user navigated to.
    if (this._tab !== "settings" && this._communityLinkPollTimer) {
      clearInterval(this._communityLinkPollTimer);
      this._communityLinkPollTimer = null;
    }
    const hasData = this._updates !== null;
    this._contentEl.innerHTML = "";
    // All three tabs now share the same centered/padded page grid (changed
    // 2026-07-21, direct user feedback: History used to be a bare, edge-to-
    // edge list, unlike the other two, and Settings used a narrower column
    // than Updates for no real reason). Each still keeps its own class for
    // the tab-specific content inside it (grouped cards, date-sectioned
    // item cards, or a settings form), see _styles' shared content--*
    // rule for the actual shared width/padding values.
    this._contentEl.className =
      this._tab === "settings"
        ? "content content--form"
        : this._tab === "updates"
          ? "content content--groups"
          : "content content--list";

    if (this._loadError) {
      this._contentEl.innerHTML = `<div class="error">${escapeHtml(this._tr.load_error_prefix)}${escapeHtml(this._loadError)}</div>`;
      return;
    }
    if (!hasData) {
      this._contentEl.innerHTML = `<div class="loading">${escapeHtml(this._tr.loading)}</div>`;
      return;
    }

    if (this._tab === "updates") {
      this._contentEl.appendChild(this._buildUpdatesList());
    } else if (this._tab === "history") {
      this._contentEl.appendChild(this._buildHistoryList());
    } else {
      this._contentEl.appendChild(this._buildSettingsCard());
    }
  }

  // Opens HA's own more-info dialog for the entity -- the same one you'd
  // get by clicking it anywhere else in HA. Only reachable now via the
  // per-entity detail dialog's own "more info" button (see
  // _openDetailDialog): clicking a row itself opens that dialog instead,
  // since it can show our own staging status/countdown/history, which
  // HA's native more-info never can.
  _openMoreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true })
    );
  }

  // The icon(+time) pill (see timerBadge), shared between the Updates
  // list rows and the detail dialog's status alert, so "when does this
  // actually happen" reads identically in both places. Also reused by
  // History's own auto-install badge, which passes no `text` at all
  // (icon-only, changed 2026-07-21, direct user feedback: the "Automatically
  // updated" label next to every auto-installed row added up to a lot of
  // repeated text down a long list). The title attribute stands in for
  // that dropped label so the meaning isn't lost, just not spelled out inline.
  _buildTimerPill(timerBadgeInfo) {
    const pill = document.createElement("div");
    pill.className = "timer-pill";
    const pillIcon = document.createElement("ha-svg-icon");
    pillIcon.path = timerBadgeInfo.icon;
    // An explicit title always applies, text or not (added for
    // verdictBadge: unlike the icon-only pills this was originally written
    // for, a verdict pill shows a count AND wants a hover explanation of
    // what that count means).
    if (timerBadgeInfo.title) pillIcon.title = timerBadgeInfo.title;
    else if (!timerBadgeInfo.text) pillIcon.title = "";
    pill.appendChild(pillIcon);
    if (timerBadgeInfo.text) {
      const pillText = document.createElement("span");
      pillText.textContent = timerBadgeInfo.text;
      pill.appendChild(pillText);
    }
    return pill;
  }

  // One row, reused for both the Updates and History lists (see
  // _buildUpdateRow/_buildHistoryRow) -- state-badge as the real entity
  // icon (slot="start"), name as the headline, a single supporting-text
  // line for the rest, a chevron signalling "tap for more". Clicking opens
  // the per-entity detail dialog, not HA's native more-info directly (see
  // _openMoreInfo's comment). `timerBadgeInfo` (see timerBadge) is the
  // optional trailing icon+time pill, left of the chevron -- direct user
  // feedback: the supporting-text line got simplified down to just the
  // version, so the "when does this actually happen" information needed
  // somewhere else to live, not just dropped.
  // verdictBadgeInfo (see verdictBadge) is a second, independent trailing
  // pill, left of timerBadgeInfo's own pill, so a row can show both a
  // community verdict and a timer countdown at once instead of one
  // replacing the other, read-only slice added 2026-07-22.
  _buildListRow(entityId, supportingText, onClick, timerBadgeInfo, verdictBadgeInfo) {
    const row = document.createElement("ha-list-item-button");
    row.hasMeta = true;

    const start = document.createElement("div");
    start.slot = "start";
    const stateBadge = document.createElement("state-badge");
    stateBadge.stateObj = entityState(this._hass, entityId);
    start.appendChild(stateBadge);
    row.appendChild(start);

    const headline = document.createElement("span");
    headline.slot = "headline";
    headline.textContent = friendlyEntityName(this._hass, entityId);
    row.appendChild(headline);

    const supporting = document.createElement("span");
    supporting.slot = "supporting-text";
    supporting.textContent = supportingText;
    row.appendChild(supporting);

    const end = document.createElement("div");
    end.slot = "end";
    end.className = "row-end";
    // Installing overrides the normal pill+chevron entirely -- matches
    // ha-config-updates.ts's own row exactly (confirmed against its real
    // source): its trailing chevron is *replaced* by the spinner/ring
    // while installing, never shown alongside it.
    if (timerBadgeInfo && timerBadgeInfo.installing) {
      end.appendChild(installingIndicatorNode(entityState(this._hass, entityId), this._tr));
    } else {
      if (verdictBadgeInfo) end.appendChild(this._buildTimerPill(verdictBadgeInfo));
      if (timerBadgeInfo) end.appendChild(this._buildTimerPill(timerBadgeInfo));
      end.appendChild(document.createElement("ha-icon-next"));
    }
    row.appendChild(end);

    row.addEventListener("click", onClick);
    return row;
  }

  // One card per active Zigbee rollout group (see rollout_manager.py's own
  // docstring: only ever appears once a second same-model/-version device
  // is asked to install while one is already in flight, reactive not
  // proactive: an untouched sibling still sitting in "Ready to update"
  // shows no queue card at all). Same building blocks as the normal
  // ready/waiting/blocked cards below (_buildListRow, installingIndicatorNode),
  // just a different trailing state per row: the front entity gets the
  // usual installing spinner, the rest get a "waiting for X" pill instead
  // of a countdown, since there's nothing to count down, only "not yet".
  // Shared by this and _buildUpdatesList's own group-card loop below
  // (found by review, 2026-07-22: the two had independently duplicated the
  // exact same ha-card/.card-content/.card-header/.title shell). Callers
  // append their own body content to the returned `content`, and any extra
  // header content (e.g. an "Update all" button) to `header`.
  _buildCardShell(titleText) {
    const card = document.createElement("ha-card");
    card.outlined = true;

    const content = document.createElement("div");
    content.className = "card-content";

    const header = document.createElement("div");
    header.className = "card-header";
    const title = document.createElement("div");
    title.className = "title";
    title.setAttribute("role", "heading");
    title.textContent = titleText;
    header.appendChild(title);
    content.appendChild(header);
    card.appendChild(content);

    return { card, content, header };
  }

  _buildRolloutGroupCard(group) {
    const tr = this._tr;
    const { card, content } = this._buildCardShell(
      group.network === "z2m" ? tr.rollout_queue_title_z2m : tr.rollout_queue_title_zha
    );

    const subtitle = document.createElement("p");
    subtitle.className = "hint";
    subtitle.textContent = tr.rollout_queue_subtitle;
    content.appendChild(subtitle);

    // Always the *front* (currently installing) entity's name, not each
    // row's own immediate predecessor: once the front entity finishes,
    // every remaining entry shifts up and only the new front one is
    // actually blocking progress, so it's the one accurate "waiting for"
    // target regardless of how far back in line a given row sits.
    const frontName = friendlyEntityName(this._hass, group.entities[0].entity_id);

    const list = document.createElement("ha-list-base");
    group.entities.forEach((entry) => {
      const installing = entry.status === "installing";
      list.appendChild(
        this._buildListRow(
          entry.entity_id,
          [deviceAreaName(this._hass, entry.entity_id), group.to_version].filter(Boolean).join(" ⋅ "),
          () => this._openDetailDialog(entry.entity_id),
          installing ? { installing: true } : { icon: ICON_CLOCK_OUTLINE, text: tr.rollout_queue_waiting(frontName) }
        )
      );
    });
    content.appendChild(list);
    return card;
  }

  // Looks up entityId inside this._rolloutGroups (see rollout_manager.py's
  // own rollout_groups_snapshot), null if it isn't part of any active
  // queue right now. Used both to exclude a queued/installing entity from
  // its normal ready/waiting/blocked group (see _buildUpdatesList) and to
  // swap the dialog's Install button for the same "waiting for X" state
  // (no-override decision, see rollout_manager.py's own docstring: a
  // queued device can't jump the line from here either).
  _rolloutStatusFor(entityId) {
    for (const group of this._rolloutGroups) {
      const entry = group.entities.find((e) => e.entity_id === entityId);
      if (entry) return { status: entry.status, frontEntityId: group.entities[0].entity_id };
    }
    return null;
  }

  // Default sort: safest first (green, then orange, then red), see
  // compareUpdates's own comments for the secondary ordering -- requested
  // directly by the user. No interactive sort/filter controls (HA's own
  // /config updates list doesn't have them either); this whole page is a
  // short, at-a-glance list, not a big searchable table anymore.
  // Grouped into cards (see groupUpdates), the same shape as HA's own
  // updates page -- direct user feedback/idea. No "update all" button per
  // group yet (deliberately deferred: it would need to decide whether it
  // only touches entities already "ready", or bulldozes the staging status
  // entirely, which is a real design conversation, not a display detail).
  // Card structure copied from ha-config-section-updates.ts's real render
  // template, not ha-card's own built-in `.header` -- that page builds its
  // own .card-content > .card-header > .title, with the group title and
  // (there, an "Update all" button) side by side, so it does the same even
  // without that button yet. Same reasoning for max-width/padding: matches
  // that page's real static styles exactly, down to the --ha-space-*
  // tokens, not approximated pixel values.
  _buildUpdatesList() {
    const tr = this._tr;
    const outer = document.createElement("div");
    outer.className = "update-groups-outer";

    // Shown whenever the master pause switch is off (see _buildGeneralCard)
    // -- without this, a paused instance would silently look identical to
    // a normal one: same statuses, same "will update automatically"
    // projections, just nothing actually happening, which read as broken
    // rather than paused.
    if (this._settings && this._settings.enabled === false) {
      const pausedAlert = document.createElement("ha-alert");
      pausedAlert.alertType = "warning";
      pausedAlert.title = tr.paused_banner;
      outer.appendChild(pausedAlert);
    }

    if (!this._updates.length) {
      outer.appendChild(buildEmptyStateCard(tr.updates_empty));
      return outer;
    }

    // Active rollout-queue cards go above the normal ready/waiting/blocked
    // groups (see _buildRolloutGroupCard): any entity shown there is
    // excluded from its normal group in the same pass below, no duplicate
    // row for the same entity in two places at once.
    const queuedEntityIds = new Set();
    this._rolloutGroups.forEach((group) => {
      outer.appendChild(this._buildRolloutGroupCard(group));
      group.entities.forEach((e) => queuedEntityIds.add(e.entity_id));
    });

    const remainingUpdates = this._updates.filter((u) => !queuedEntityIds.has(u.entity_id));
    if (!remainingUpdates.length) return outer;

    const groups = groupUpdates(tr, remainingUpdates);

    const wrap = document.createElement("div");
    wrap.className = "update-groups";

    groups.forEach((group) => {
      const { card, content, header } = this._buildCardShell(group.title);
      // Only the "ready" group -- matches real HA's own placement
      // (ha-config-section-updates.ts's own showUpdateAll), and direct
      // user feedback specifically asked for it there, not for postponed/
      // discouraged/skipped/not-installable groups where bulk-installing
      // isn't the point. Plain ha-button, not ha-progress-button -- real
      // HA's own button here has no loading state of its own either
      // (confirmed against its exact source): _updateAll doesn't gate
      // anything on the service call's own promise beyond a try/catch for
      // the error toast, same as this._updateAllInGroup below.
      if (group.key === "ready") {
        const updateAllBtn = document.createElement("ha-button");
        updateAllBtn.appearance = "plain";
        updateAllBtn.size = "s";
        updateAllBtn.textContent = tr.update_all;
        updateAllBtn.disabled = group.entities.every((u) => updateIsInstalling(entityState(this._hass, u.entity_id)));
        updateAllBtn.addEventListener("click", () => this._updateAllInGroup(group));
        header.appendChild(updateAllBtn);
      }

      const list = document.createElement("ha-list-base");
      group.entities
        .slice()
        .sort((a, b) => compareUpdates(a, b, this._settings))
        .forEach((u) => {
          // The version to install, plus the device's area (confirmed
          // against ha-config-updates.ts's real source -- "AreaName ⋅
          // version") and a "(skipped)" annotation whenever this specific
          // entity is currently skipped, matching that component's own
          // unconditional "(skipped)" suffix regardless of which group a
          // row ends up in. Direct user feedback: this row used to be a
          // whole sentence (size, both versions, full status text), the
          // status/countdown now live in the group heading and the
          // trailing timer badge instead (see timerBadge) -- just the
          // area/version/skipped facts stay here, matching real HA.
          // The "(skipped)" annotation is suppressed while actually
          // installing -- direct user feedback: clicking Install on a
          // postponed/skipped update should stop looking postponed/skipped
          // right away, not keep that label until the install finishes.
          const installingNow = updateIsInstalling(entityState(this._hass, u.entity_id));
          list.appendChild(
            this._buildListRow(
              u.entity_id,
              [deviceAreaName(this._hass, u.entity_id), u.latest_version + (u.status === "skipped" && !installingNow ? ` (${tr.status_skipped_suffix})` : "")]
                .filter(Boolean)
                .join(" ⋅ "),
              () => this._openDetailDialog(u.entity_id),
              timerBadge(tr, u, this._settings, this._hass),
              verdictBadge(tr, u.community_verdict)
            )
          );
        });
      content.appendChild(list);
      wrap.appendChild(card);
    });

    outer.appendChild(wrap);
    return outer;
  }

  // Own card per entry, not one shared list (changed 2026-07-21, direct
  // user feedback: wanted the same "white card, border, breathing room
  // between rows" look the per-entity dialog's own history cards already
  // have, applied to this top-level tab too). Grouped into the same
  // Today/Yesterday/This week/... sections as historySections, each with
  // its own plain-text heading: a real ha-card per group (like the
  // Updates tab's status groups) would be one card per row *inside* another
  // card, which HA's own design language doesn't do.
  _buildHistoryList() {
    const tr = this._tr;
    if (!this._installLog.length) {
      // Same buildEmptyStateCard the Updates tab's own empty state uses
      // (which already matches ha-config-section-updates.ts's real source
      // exactly) -- direct user feedback, 2026-07-27: a bare, cardless line
      // of text here read as inconsistent with both that tab and with
      // every other History entry on this same tab, which is always its
      // own ha-card.
      return buildEmptyStateCard(tr.history_empty);
    }

    const outer = document.createElement("div");
    outer.className = "history-sections";
    historySections(tr, this._installLog).forEach((section) => {
      const heading = document.createElement("h2");
      heading.className = "history-section-heading";
      heading.textContent = section.label;
      outer.appendChild(heading);

      const items = document.createElement("div");
      items.className = "history-section-items";
      section.items.forEach((entry) => {
        // Only "Today" spells out a relative time in the subtitle itself
        // (still useful there: "3 hours ago" vs. "just now" is real
        // information within a single day). Every other section's own
        // heading already places it roughly in time, so repeating that in
        // every single row under it was redundant. Direct user feedback.
        const supporting =
          section.key === "today"
            ? `${entry.from_version} → ${entry.to_version} ⋅ ${relativeTime(tr, entry.installed_at)}`
            : `${entry.from_version} → ${entry.to_version}`;
        // Same download-icon pill _buildListRow already renders for the
        // Updates tab's own auto-install countdown (see timerBadge),
        // reused here, not a new mechanism, so this list shows the same
        // auto/manual distinction the per-entity dialog's own history
        // cards already do (entry.auto_installed), instead of only
        // showing it there.
        const badge = entry.auto_installed ? { icon: ICON_AUTO_DOWNLOAD, title: installMethodText(tr, entry) } : null;
        const row = this._buildListRow(
          entry.entity_id,
          supporting,
          () => this._openDetailDialog(entry.entity_id, entry),
          badge
        );
        const card = document.createElement("ha-card");
        card.outlined = true;
        const list = document.createElement("ha-list-base");
        list.appendChild(row);
        card.appendChild(list);
        items.appendChild(card);
      });
      outer.appendChild(items);
    });
    return outer;
  }

  // A real ha-dialog (built once, see _ensureShell), repopulated per click
  // -- not HA's native more-info, which has no notion of Update Manager's
  // own staging status, pending-install countdown/cancel, or per-entity
  // install history (direct user feedback/idea: "misschien zelfs een
  // custom detailpagina of dialog per update entity"). A button at the
  // bottom still opens the real more-info, for the entity's raw attributes
  // and its own native controls.
  //
  // Structure verified against HA's own more-info dialogs, not guessed:
  // the header bar is title-only (ha-dialog's headerTitle -- confirmed
  // against ha-more-info-dialog.ts, whose own header has no icon either),
  // the icon lives in the content area instead (confirmed against
  // ha-more-info-state-header.ts's layout), status uses ha-alert (real
  // color/left-border treatment, not a plain paragraph), and version facts
  // use the same key/value ".row" pattern more-info-update.ts itself uses.
  _openDetailDialog(entityId, historyEntry = null) {
    // While an update is actually installing, HA's own more-info dialog
    // already has the real thing (a live progress bar, a real percentage)
    // -- direct user feedback, 2026-08-01: "als hij installing is wil ik
    // niet onze dialog tonen maar direct die van ha waarin de progress
    // zichtbaar is". Only for the entity's own live pending view
    // (!historyEntry) -- a History row is always a *past*, already-
    // completed install, irrelevant to whatever this same entity might be
    // doing right now. See _updateDialogProgress's own matching guard for
    // the case an install starts while this dialog is already open.
    if (!historyEntry && updateIsInstalling(entityState(this._hass, entityId))) {
      this._openMoreInfo(entityId);
      return;
    }
    const tr = this._tr;
    const dialog = this._dialogEl;
    // Tracks which entity the dialog is currently showing -- lets an
    // in-flight release-notes fetch (see below) recognize itself as stale
    // if the dialog closes or gets reopened for a different entity before
    // it resolves.
    this._dialogEntityId = entityId;
    this._dialogHistoryEntry = historyEntry;
    // Shared by every async fetch this method kicks off (release notes,
    // verdict_for_version, github_link_status) instead of each repeating
    // the same `this._dialogEntityId !== entityId` check inline.
    const isDialogStale = () => this._dialogEntityId !== entityId;
    // Live-updated by _updateDialogProgress (see set hass) as real
    // state_changed pushes stream in, exactly like more-info-update.ts's
    // own reactive stateObj -- not something this one-shot render call
    // itself keeps current.
    this._dialogLastState = entityState(this._hass, entityId) || null;
    this._dialogStatusTextNode = null;
    this._dialogActionButtons = [];
    dialog.innerHTML = "";
    dialog.headerTitle = friendlyEntityName(this._hass, entityId);

    const body = document.createElement("div");
    body.className = "dialog-content";

    const state = entityState(this._hass, entityId);
    const u = this._updates.find((x) => x.entity_id === entityId);
    const sizeShort = u ? tr[`size_${u.version_size}_short`] || u.version_size : null;
    // Named once, used at both spots that gate the pending-update block
    // (body content and its own action buttons) -- opened for one specific
    // History entry means the user wants that one past install, not also
    // the entity's unrelated current pending update dragged in above it.
    const showPendingUpdate = u && !historyEntry;

    // Hoisted above the header, direct user feedback 2026-07-29: the
    // header's own brief .state value always shows the plain status
    // (ready/waiting/skipped/blocked) regardless of what the alert below
    // says -- it's the one place answering "which group is this filed
    // under", not something to hide just because the alert repeats the
    // same word. `heldBackByCommunity` is still used to gate the plain
    // status alert (and Cancel inside it, see below): a real community
    // block means auto-install genuinely won't run, so "ready"/"will
    // update automatically at X" would be flatly false regardless of
    // which staging status this happens to be in right now -- not just
    // "ready" specifically (found by a follow-up screenshot, 2026-07-29:
    // a "waiting" entity with a projected auto-install time and a
    // negative vote showed both "will update automatically" *and* "held
    // back" side by side, and a Cancel button for an install that was
    // never actually going to run).
    const communityProblematicCount = showPendingUpdate
      ? (u.community_verdict && u.community_verdict.problematic_count) || 0
      : 0;
    const heldBackByCommunity =
      showPendingUpdate && communityBlocksAutoInstall(u) && !u.auto_install_excluded && u.status !== "skipped";
    // Hoisted so both the header (always uses it) and this check (compares
    // against it) share one computation. The status alert itself is now
    // skipped entirely whenever it would add nothing beyond the header's
    // own bare word -- direct user feedback, 2026-07-29, after "Skipped"
    // still showed twice even once the header/alert dedup only omitted
    // the header: "die alert mag wel weg. want de status is al skipped en
    // clear skipped staat in de footer" -- Unskip already lives in the
    // footer (see below), so a plain "Skipped"/"Ready to update"/
    // "Discouraged" alert with nothing else to say no longer has any
    // reason to exist at all, not just a reason to go quiet. Never
    // silently drops Cancel: a truthy cancelToVersion always coincides
    // with statusText returning something richer than the bare word
    // (pending_install's own sentence, or "waiting"'s own countdown,
    // which is never the bare word to begin with), so there's no case
    // where suppressing "identical text" also suppresses a real Cancel.
    const headerStateText = showPendingUpdate
      ? (u.status === "waiting" ? tr.status_waiting_short : tr[`status_${u.status}`]) || u.status
      : null;
    // Computed once here (rather than again down at the alert's own text
    // node below) since both need the exact same value: this comparison,
    // and, if it turns out to differ, the alert's initial text itself.
    const dialogStatusText = showPendingUpdate ? statusText(tr, u, this._settings, this._hass) : null;
    const willShowStatusAlert = showPendingUpdate && !heldBackByCommunity && headerStateText !== dialogStatusText;

    // state-info + a right-aligned ".state" value, in a
    // ".horizontal.justified.layout" row -- not hand-laid-out, this is the
    // real pair of components/classes state-card-update.ts itself uses for
    // every update entity's more-info header (confirmed against its actual
    // source, not guessed). Shown whenever the entity still exists at all,
    // even for a purely historical entry (opened from the History tab)
    // with no currently pending update -- state-info reflects the
    // entity's real current state, not just whatever Update Manager still
    // happens to be tracking; the summary/.state pieces below it only
    // apply when there's an actual pending update, though.
    if (state) {
      const header = document.createElement("div");
      header.className = "dialog-header";
      const stateInfo = document.createElement("state-info");
      stateInfo.hass = this._hass;
      stateInfo.stateObj = state;
      // Real HA more-info dialogs render this with inDialog=true (confirmed
      // against source: ha-more-info-info.ts renders <state-card-content
      // in-dialog>, which for the "update" domain -- not in
      // DOMAINS_NO_INFO -- reaches state-card-update.ts and passes
      // .inDialog through to here), which would give state-info's own
      // built-in "Last changed"/"Last updated" tooltip. Deliberately NOT
      // done here (direct user feedback): those are generic state-change
      // timestamps, not the fact that actually matters for an update --
      // how long the update itself has existed (available_since,
      // coordinator.py's own recorder lookup) -- so inDialog stays false
      // and that fact is slotted in below instead, in the same visual spot
      // (.extra-info gets the exact same secondary-text/ellipsis styling
      // state-info's own .time-ago block would).
      header.appendChild(stateInfo);

      if (u) {
        const availableSince = document.createElement("span");
        availableSince.textContent = relativeTime(tr, u.available_since);
        stateInfo.appendChild(availableSince);

        // Bug fixed 2026-07-17: tr.status_waiting is a function (n, unit) =>
        // ..., not a plain string like tr.status_ready/status_blocked --
        // assigning it straight to .textContent stringified the function's
        // own source code instead of calling it. status_waiting_short is
        // the deliberately unparameterized, brief form for this small
        // header value (the full countdown sentence already lives in the
        // alert body below via statusText). Always shown, direct user
        // feedback 2026-07-29 (reverting an earlier attempt this same
        // session to omit it when it'd repeat the alert below): this is
        // the one place answering "which group is this filed under"
        // (Ready/Postponed/Skipped/Blocked) at a glance, regardless of
        // whatever else the alert below goes on to say.
        const stateValue = document.createElement("div");
        stateValue.className = "state";
        stateValue.textContent = headerStateText;
        header.appendChild(stateValue);
      }
      body.appendChild(header);
    }

    // A purely historical entity (no pending update at all) no longer gets
    // a top-level community section here -- voting now lives inside each of
    // its own History entries below instead (see the entries.forEach loop
    // further down), consistently, whether or not something's pending.

    // showPendingUpdate (`u && !historyEntry`, not just `u`): opened via a
    // specific History-tab row (historyEntry set) means the user wants
    // that one past install, not also the entity's unrelated current
    // pending update dragged in above it -- direct user feedback,
    // 2026-07-27 ("je verwacht die bovenkant helemaal niet"). Same signal
    // _openDetailDialog's own defaultExpandIndex already uses for the same
    // reasoning. The Updates-tab/rollout-queue entry points (both `u`
    // truthy, no historyEntry) are unaffected.
    if (showPendingUpdate) {
      // No progress bar of our own here anymore (see "Open update",
      // 2026-07-29): live install progress now lives entirely in HA's own
      // more-info dialog, reached via that button below, instead of being
      // mirrored here too.

      // The entity's own "title" attribute (e.g. "Frontend"), not
      // necessarily the same string as its friendly name in state-info
      // above -- more-info-update.ts shows both, so we do too.
      const attrTitle = state && state.attributes && state.attributes.title;
      if (attrTitle) {
        const titleEl = document.createElement("h3");
        titleEl.textContent = attrTitle;
        body.appendChild(titleEl);
      }

      // communityProblematicCount/heldBackByCommunity: hoisted above the
      // header now (see that block's own comment) -- reused here as-is.
      //
      // Skipped entirely for "ready" + held-back: cancelToVersion is never
      // truthy in that combination either (nothing is actually projected/
      // announced once auto-install is blocked), so no action button is
      // lost by skipping this whole block, only the redundant repeated
      // text.
      if (willShowStatusAlert) {
        // "info" (blue), not the status-driven default, whenever there's
        // an actual scheduled auto-install countdown (u.pending_install)
        // to show -- direct user feedback, 2026-07-29: "zou het niet
        // logischer zijn als de alert met 'will update automatically...'
        // blauw is ipv groen? het is info en geen success toch?" A plain
        // "ready" with nothing scheduled yet is a genuinely positive
        // status worth "success" green; "will update automatically at X"
        // is a scheduled fact, not an accomplishment, regardless of which
        // underlying status (most often "ready", but not exclusively)
        // happens to have that schedule attached to it.
        const statusAlertType = u.pending_install
          ? "info"
          : STATUS_ALERT_TYPE[u.status] || STATUS_ALERT_TYPE[_FALLBACK_STATUS];
        const statusAlert = document.createElement("ha-alert");
        statusAlert.alertType = statusAlertType;
        // ha-alert's own default icon (checkmark/info/warning, based on
        // alertType) is replaced by the same icon the Updates list's pill
        // uses (see timerBadge) whenever there's a real countdown to show --
        // ha-alert supports this via its own slot="icon" (confirmed against
        // its real source), the text itself already explains what's
        // happening (statusText), the icon just ties it visually to the
        // same download/clock icon used elsewhere for "when".
        const dialogBadge = timerBadge(tr, u, this._settings, this._hass);
        if (dialogBadge) {
          const customIcon = document.createElement("ha-svg-icon");
          customIcon.slot = "icon";
          customIcon.path = dialogBadge.icon;
          statusAlert.appendChild(customIcon);
        }
        // Kept as its own text node reference, not a one-shot string --
        // _updateDialogProgress re-sets its own .textContent live as hass
        // pushes come in, so this reflects "Installing…" (statusText's own
        // installing override) the moment an install actually starts,
        // instead of staying frozen on whatever status this was at the
        // moment the dialog opened.
        this._dialogStatusTextNode = document.createTextNode(dialogStatusText);
        statusAlert.appendChild(this._dialogStatusTextNode);
        // Cancellable even before a real announcement exists yet -- still
        // "waiting" but auto-install is projected to happen (see
        // projectedAutoInstallTime below), not just once actually "ready"
        // and formally announced. Direct user feedback: seeing "will update
        // automatically" with no way to act on it read as a real gap.
        // install_manager.py's async_cancel already supports this (records
        // the cancellation regardless of whether a PendingAnnouncement
        // exists yet), so only the to_version to send needs picking: the
        // real announcement's own target once one exists, else whatever
        // version is currently projected. Never reachable here at all
        // while heldBackByCommunity is true (this whole block is gated on
        // willShowStatusAlert, see its own comment above), so there's no
        // separate guard needed against showing a Cancel button for an
        // install that was never actually going to run.
        const cancelToVersion = u.pending_install
          ? u.pending_install.to_version
          : projectedAutoInstallTime(u, this._settings)
            ? u.latest_version
            : null;
        if (cancelToVersion) {
          // Back in the alert's own slot="action" (2026-07-29, round two --
          // moving it out to a plain sibling instead, tried right before
          // this, looked worse: floating disconnected from the message it
          // actually acts on, exactly the "context" the first move back in
          // was already about). The real, narrower problem was only ever
          // the *color* -- ha-alert's own action slot expects an MWC-era
          // button honoring --mdc-theme-primary (set to --primary-text-
          // color, a neutral tone that reads on any of its tinted
          // backgrounds), but this project's actual ha-progress-button (a
          // newer webawesome-based component) never reads that legacy
          // variable, so its own "plain" appearance fell back to its usual
          // link-blue regardless of the alert underneath it. Overriding
          // the specific custom property that component's own "plain"
          // style actually reads (confirmed against ha-button's real
          // source) gets the same "readable on any alert color" result
          // ha-alert always intended, without needing to relocate anything.
          const cancelBtn = document.createElement("ha-progress-button");
          cancelBtn.slot = "action";
          cancelBtn.style.setProperty("--wa-color-on-normal", "var(--primary-text-color)");
          cancelBtn.appearance = "plain";
          cancelBtn.label = tr.cancel_auto_install;
          cancelBtn.disabled = updateIsInstalling(this._dialogLastState);
          cancelBtn.addEventListener("click", () =>
            _runProgressAction(cancelBtn, async () => {
              await this._hass.callWS({
                type: "update_manager/cancel_pending_install",
                entity_id: entityId,
                to_version: cancelToVersion,
              });
              await this._afterDialogAction(entityId);
            })
          );
          statusAlert.appendChild(cancelBtn);
          this._dialogActionButtons.push(cancelBtn);
        }
        body.appendChild(statusAlert);
      }

      // Shown regardless of whatever the status alert above already says
      // (e.g. still "waiting" on its own postponement period) -- direct
      // user feedback: a block needs to explain itself right here, on the
      // still-pending update it actually prevents, not just be inferable
      // from "why hasn't this auto-installed even though it's ready and the
      // toggle is on". Distinct wording from the unrelated "blocked"
      // *staging* status (a discouraged size/jump) on purpose: this is
      // about a community vote overriding auto-install, not that. Named
      // ("@user reported this...") when it's specifically a trusted
      // voter's own problematic vote -- more meaningful, someone you
      // deliberately trust flagged it -- falling back to the generic
      // count-based message otherwise (any problematic vote at all
      // blocks, direct user feedback, 2026-07-29: a 100% negative verdict
      // with no trusted voters configured used to have no effect on
      // auto-install whatsoever).
      if (heldBackByCommunity) {
        const heldBackAlert = document.createElement("ha-alert");
        heldBackAlert.alertType = "warning";
        heldBackAlert.textContent =
          u.trusted_vote === "problematic"
            ? tr.dialog_auto_install_held_back(joinUsernames(tr, u.trusted_voters_matched || []))
            : tr.dialog_auto_install_held_back_community(communityProblematicCount);
        body.appendChild(heldBackAlert);
      }

      // Mutually exclusive: an entity is either "ready" with a real,
      // already-created announcement (pending_install.announced_at, exact
      // same fact History shows once installed), or "waiting" with at most
      // a *projected* one (projectedAnnouncementTime, only meaningful once
      // auto-install is actually enabled for its size) -- never both.
      // Direct user feedback, 2026-08-01: "bij postponed zie je niet
      // wanneer hij announced gaat worden en bij ready net zo goed" --
      // History already shows this fact for a completed install, the live
      // dialog showed it nowhere at all.
      let announcementLabel = null;
      let announcementValue = null;
      if (u.pending_install) {
        announcementLabel = tr.dialog_history_announced;
        announcementValue = absoluteWhen(tr, u.pending_install.announced_at, this._hass);
      } else {
        const projectedAnnouncement = projectedAnnouncementTime(u, this._settings);
        if (projectedAnnouncement) {
          announcementLabel = tr.dialog_announcement_label;
          announcementValue = absoluteWhen(tr, projectedAnnouncement, this._hass);
        }
      }
      body.appendChild(
        buildKeyValueRows([
          [tr.dialog_current_version, u.installed_version],
          [tr.dialog_new_version, u.latest_version],
          [tr.col_jump, sizeShort],
          [announcementLabel, announcementValue],
        ])
      );

      // Not rendered here -- moved into the Release notes section below
      // (appendReleaseNotesSection), 2026-08-01, direct user feedback:
      // "Read release announcement is soms een wat vreemde tekst als die
      // notes er gewoon boven staan. En als die notes ontbreken, dan staat
      // die link bij de details ipv onder het kopje 'Release notes'." Kept
      // here only as the plain attribute read -- straight from the
      // entity's own state, not something we compute ourselves.
      const releaseUrl = state && state.attributes && state.attributes.release_url;

      // Journey A (report-only, no healthy button) unconditionally -- this
      // is inherently about a not-yet-installed version, regardless of
      // whatever History entry the dialog might also have been opened
      // with (changed 2026-07-25: used to be derived from `!!historyEntry`,
      // which could let a not-yet-installed version get voted "healthy" if
      // a historyEntry also happened to be passed).
      const pendingCommunitySection = this._buildCommunitySection(
        tr, entityId, u.installed_version, u.latest_version, false, isDialogStale
      );
      if (pendingCommunitySection) body.appendChild(pendingCommunitySection);

      // Release notes. UpdateEntityFeature.RELEASE_NOTES = 16
      // (homeassistant/components/update/const.py): entities that support
      // it generate notes on demand (e.g. fetched from a changelog API),
      // fetched the same real way HA's own more-info dialog does --
      // update/release_notes, a core websocket command (verified against
      // frontend's data/update.ts's updateReleaseNotes, not guessed), not
      // something we compute ourselves. Entities without that feature just
      // expose a plain release_summary attribute instead -- more-info-
      // update.ts falls back to exactly that same attribute when the
      // feature isn't supported, so we do too. Neither of those is
      // guaranteed to actually have anything, though (direct user feedback,
      // 2026-08-01, confirmed live -- "dus het is absoluut niet alleen
      // hacs": HACS's own async_release_notes() returns None whenever
      // pending_restart is still true or the installed version isn't in its
      // own published_tags, and Home Assistant Supervisor's own update
      // entity doesn't support RELEASE_NOTES at all), so both paths below
      // fall back to fetching GitHub's own release body directly
      // (_fetchGithubReleaseNotesFallback) whenever they'd otherwise show
      // nothing but the release_url link above. The `<hr>` + markdown block
      // is only ever appended once real content is in hand, from whichever
      // of the three sources actually had it -- not upfront, unlike the old
      // version, which could leave a bare `<hr>` with nothing under it
      // whenever update/release_notes resolved empty.
      // An anchor, placed right here synchronously, so appendReleaseNotes
      // below can always insert *before* the History section further down
      // (also appended synchronously, right after this whole block) no
      // matter how long the actual fetch takes -- direct user feedback,
      // 2026-08-01, seen on a real browser_mod pending update: a plain
      // trailing body.appendChild landed release notes after History
      // instead, since History's own synchronous append always finished
      // first whenever the notes took a moment longer to resolve (e.g. the
      // GitHub fallback fetch above).
      const releaseNotesAnchor = document.createComment("release-notes");
      body.appendChild(releaseNotesAnchor);
      const supportsReleaseNotes = state && (state.attributes.supported_features || 0) & 16;
      // notes may be null/empty here -- releaseUrl alone is still reason
      // enough to show the section, just with only the link in it (see
      // insertReleaseNotesSection's own comment). Never called at all when
      // both are empty, same "no empty section" treatment as before.
      const appendReleaseNotesSection = (notes, linkUrl) => {
        insertReleaseNotesSection(body, releaseNotesAnchor, tr, notes, releaseUrl, u.installed_version, u.latest_version, linkUrl);
        if (notes) this._appendUpstreamReleaseNotes(body, releaseNotesAnchor, tr, notes, releaseUrl, u.installed_version, u.latest_version);
      };
      if (supportsReleaseNotes) {
        const loader = buildReleaseNotesLoader();
        body.insertBefore(loader, releaseNotesAnchor);
        // _fetchNativeReleaseNotes already folds a rejection into a null
        // resolution (see its own comment) -- a rejected update/release_notes
        // call and a resolved-but-empty one both need exactly the same
        // fallback treatment, so one .then() here covers both.
        this._fetchNativeReleaseNotes(entityId, u.latest_version).then(async (notes) => {
          // Stale by the time it resolves (dialog closed, or reopened for
          // a different entity) -- checked *before* the fallback fetch
          // below too, not just after it, so a stale dialog doesn't still
          // pay for that (heavier) extra request for nobody. loader.remove()
          // either way: harmless even if dialog.innerHTML already wiped it
          // out from under us.
          if (isDialogStale()) {
            loader.remove();
            return;
          }
          let finalNotes = notes;
          let correctedUrl = null;
          if (!finalNotes) {
            ({ notes: finalNotes, correctedUrl } = await this._fetchGithubReleaseNotesFallback(
              releaseUrl, u.installed_version, u.latest_version
            ));
          }
          loader.remove();
          if (!isDialogStale() && (finalNotes || releaseUrl)) appendReleaseNotesSection(finalNotes, correctedUrl);
        });
      } else {
        const releaseSummary = state && state.attributes && state.attributes.release_summary;
        if (releaseSummary) {
          appendReleaseNotesSection(releaseSummary);
        } else {
          const loader = buildReleaseNotesLoader();
          body.insertBefore(loader, releaseNotesAnchor);
          this._fetchGithubReleaseNotesFallback(releaseUrl, u.installed_version, u.latest_version).then(({ notes, correctedUrl }) => {
            loader.remove();
            if (!isDialogStale() && (notes || releaseUrl)) appendReleaseNotesSection(notes, correctedUrl);
          });
        }
      }

    }

    // Skipped entirely when there's no history at all, not shown with an
    // empty-state message -- direct user feedback: a heading for a section
    // with nothing under it just added noise, especially for a purely
    // historical entity that's otherwise short on content anyway.
    const entries = this._installLog.filter((entry) => entry.entity_id === entityId);
    if (entries.length) {
      // Missing entirely before this fix -- direct user feedback,
      // 2026-07-30: whatever renders above (Community section, or the
      // changelog block right before this one) ran straight into the
      // "History" heading with no visual boundary at all.
      body.appendChild(document.createElement("hr"));
      const historyHeading = document.createElement("h3");
      historyHeading.textContent = tr.dialog_history_heading;
      body.appendChild(historyHeading);

      // One ha-card per entry, not a plain <ul>. Direct user feedback
      // (2026-07-17): felt "spuug lelijk", didn't read as HA at all. Same
      // outlined-card building block the Settings tab already uses, read
      // top-to-bottom as a timeline (newest first, same order the log
      // itself is already in). Each card is fully clickable when there's
      // anywhere to go (release notes to expand, or a release page to
      // open). Only the version jump + when + auto/manual pill is always
      // visible, matching direct user feedback that a card should open to
      // show its details rather than dumping everything inline.
      //
      // At most one entry starts expanded. Opened for one *specific* entry
      // (historyEntry, from the History tab's own list): that one, matched
      // by installed_at+to_version, not object identity -- _afterDialogAction
      // reloads this._installLog (a fresh array of fresh objects) before
      // re-opening the dialog with the same old historyEntry reference, so
      // `===` would silently fail to re-match a structurally-identical entry
      // after that reload. Otherwise: the most recent entry (entries[0] --
      // this._installLog is already loaded newest-first, see _loadAll's own
      // .slice().reverse()), but only when there's no pending update of its
      // own already drawing attention via the Journey A Community section
      // above (`u`, in scope from earlier in this method) -- direct user
      // feedback, 2026-07-27: opening the dialog from the Updates tab (or
      // the rollout-queue row -- both always have `u` truthy) shouldn't also
      // auto-expand History. `-1` never matches a real `index`, so every
      // card stays collapsed in that case. `_afterDialogAction`'s own
      // self-refresh re-evaluates `u` fresh each time, so once an Install
      // finishes and `u` becomes falsy, the newest entry (the install that
      // just completed) auto-expands on the refreshed dialog -- correct by
      // construction, not a case needing its own handling here.
      const defaultExpandIndex = (() => {
        if (historyEntry) {
          const i = entries.findIndex(
            (e) => e.installed_at === historyEntry.installed_at && e.to_version === historyEntry.to_version
          );
          return i !== -1 ? i : 0;
        }
        return u ? -1 : 0;
      })();

      const list = document.createElement("div");
      list.className = "dialog-history";
      entries.forEach((entry, index) => {
        const card = document.createElement("ha-card");
        card.outlined = true;

        const content = document.createElement("div");
        content.className = "card-content dialog-history-card";

        const versionText = `${entry.from_version} → ${entry.to_version}`;
        const whenText = relativeTime(tr, entry.installed_at);
        const pill = entry.auto_installed
          ? this._buildTimerPill({ icon: ICON_AUTO_DOWNLOAD, title: installMethodText(tr, entry) })
          : null;

        // Every entry expands the same way now, regardless of whether it
        // has release notes, a bare release_url, or neither (changed
        // 2026-07-23, direct user feedback: install method + timing is
        // worth showing even for an entry with no changelog at all, the
        // same way the pending-update dialog above already shows installed/
        // latest version and impact as plain fact rows).
        const row = document.createElement("ha-list-item-button");
        row.hasMeta = true;
        const headline = document.createElement("span");
        headline.slot = "headline";
        headline.textContent = versionText;
        row.appendChild(headline);
        const supporting = document.createElement("span");
        supporting.slot = "supporting-text";
        supporting.textContent = whenText;
        row.appendChild(supporting);
        const end = document.createElement("div");
        end.slot = "end";
        end.className = "row-end";
        if (pill) end.appendChild(pill);
        const isDefaultExpanded = index === defaultExpandIndex;
        const chevron = document.createElement("ha-svg-icon");
        chevron.path = ICON_CHEVRON_DOWN;
        chevron.className = "dialog-history-chevron";
        chevron.classList.toggle("open", isDefaultExpanded);
        end.appendChild(chevron);
        row.appendChild(end);
        content.appendChild(row);

        // Toggled by hand (not ha-expansion-panel's own built-in toggle,
        // see ICON_CHEVRON_DOWN's own comment) -- just a hidden attribute
        // and a rotated icon, not a new component of its own. Collapsed by
        // default, except for whichever one entry defaultExpandIndex above
        // picked.
        const expandWrap = document.createElement("div");
        expandWrap.className = "dialog-history-notes-wrap";
        expandWrap.hidden = !isDefaultExpanded;

        // Same buildKeyValueRows the pending-update section above already
        // uses for installed/latest version + impact. Any fact this exact
        // entry doesn't have (available_since/announced_at are both null on
        // a manual install, or on any entry logged before this session's
        // audit-trail fields existed at all) is skipped entirely, not shown
        // as "unknown".
        expandWrap.appendChild(
          buildKeyValueRows([
            [tr.dialog_history_available_since, entry.available_since ? absoluteWhen(tr, entry.available_since, this._hass) : null],
            [tr.dialog_history_announced, entry.announced_at ? absoluteWhen(tr, entry.announced_at, this._hass) : null],
            [tr.dialog_history_installed_at, absoluteWhen(tr, entry.installed_at, this._hass)],
            [tr.dialog_history_method_label, installMethodText(tr, entry)],
            // null (not just false) on a manual install -- install_log.py's
            // own backup_used field is only ever a sure fact for an
            // auto-install (its own dispatch unconditionally requests a
            // backup whenever the entity supports it); a manual install
            // could equally have gone through HA's own native dialog and
            // its own separate checkbox, entirely invisible to us, so this
            // row is left out rather than guessing.
            [tr.dialog_history_backup_label, entry.backup_used == null ? null : (entry.backup_used ? tr.dialog_history_backup_yes : tr.dialog_history_backup_no)],
          ])
        );

        // Marks where the changelog/release-notes block below starts, so
        // the (lazily-built, see ensureCommunitySection below) Community
        // section can always be inserted right before it -- direct user
        // feedback, 2026-07-27: votes used to render after the changelog,
        // at the very bottom, easy to miss on an entry with long release
        // notes, when spotting a reported problem before reading the notes
        // is exactly the point. An invisible, empty comment node, not a
        // real element: nothing to style or accidentally match a CSS rule.
        const changelogAnchor = document.createComment("changelog");
        expandWrap.appendChild(changelogAnchor);

        // No release_summary fallback here (unlike the pending-update
        // section above, which reads it live off the entity's current
        // state): direct user feedback, 2026-07-29, seeing a red "Restart
        // of Home Assistant required" alert permanently frozen into an
        // already-completed History entry. Confirmed against HACS's own
        // update.py source -- for a HACS-managed entity this attribute
        // isn't release content at all, it's `repository.pending_restart`
        // rendered as a one-off HTML snippet, true only for the brief
        // window right after that specific install before HA gets
        // restarted. install_log.py's own _on_install freezes whatever
        // that snippet said at the exact moment install finished (when
        // it's almost always still true), so History would otherwise show
        // this as if still outstanding long after the restart it was
        // warning about already happened. release_notes (the real,
        // durable changelog) has no such problem and stays.
        // The release_url link now renders as *part of* this section (see
        // buildReleaseUrlLinkRow's own comment), not off on its own further
        // down -- 2026-08-01, direct user feedback: "als die notes
        // ontbreken, dan staat die link bij de details ipv onder het
        // kopje 'Release notes'".
        // entry.release_notes, when present, is normally trusted as-is --
        // except when it looks like HACS's own compile is anchored to
        // completely the wrong end, not just imprecisely scoped (which
        // insertReleaseNotesSection's own trim step already handles safely
        // on its own). Direct user feedback, 2026-08-02, a real downgrade
        // (7.1.10 -> 7.1.9): HACS's own async_release_notes() (see its own
        // docstring, "Compile release notes from installed version up to
        // the latest") has no concept of a downgrade at all -- it always
        // walks from whatever it still considers "latest" down to
        // installed_version, so for a downgrade this produces a real,
        // non-empty compiled result that describes entirely different
        // (newer) versions than what actually got installed, with
        // from_version's own heading right at the top and to_version's own
        // heading never included at all (the compile loop breaks the
        // moment it reaches that tag, before ever appending anything for
        // it). Detected the same way the trim step finds headings at all:
        // from_version's own heading present but to_version's own absent
        // is specific enough to this exact failure mode that it doesn't
        // false-positive on a normal upgrade either (whose own compiled
        // range never reaches back far enough to include from_version's
        // heading at all, upgrade or downgrade -- see
        // _findChangelogHeadingIndex's own comment).
        const releaseNotesLooksWrongForThisJump =
          !!entry.release_notes &&
          _findChangelogHeadingIndex(entry.release_notes, entry.from_version) != null &&
          _findChangelogHeadingIndex(entry.release_notes, entry.to_version) == null;
        if (entry.release_notes && !releaseNotesLooksWrongForThisJump) {
          // Same heading the pending-update dialog's own Release notes
          // section now has (2026-08-01, direct user feedback: "dit
          // consistent doorvoeren binnen een history item" -- History's
          // per-entry changelog was the one place left without it). Appended
          // eagerly, unlike the release_url-only branch below -- this is
          // already-available data (install_log.py's own frozen snapshot),
          // no fetch involved, same as every other synchronously-built part
          // of this card.
          insertReleaseNotesSection(expandWrap, null, tr, entry.release_notes, entry.release_url, entry.from_version, entry.to_version);
          this._appendUpstreamReleaseNotes(expandWrap, null, tr, entry.release_notes, entry.release_url, entry.from_version, entry.to_version);
        }
        // Same last-resort GitHub fallback as the pending-update section
        // above (_fetchGithubReleaseNotesFallback) -- entry.release_notes is
        // only ever install_log.py's own snapshot of whatever the entity's
        // release_notes/release_summary happened to say *at install time*,
        // which HACS entities regularly have nothing for (see that method's
        // own docstring), or (releaseNotesLooksWrongForThisJump) have the
        // wrong thing for.
        //
        // Lazy, same reasoning as ensureCommunitySection right below --
        // found by review, 2026-08-01: this used to fire its own live
        // GitHub fetch unconditionally in this forEach, for every entry
        // lacking entry.release_notes, directly contradicting the reasoning
        // ensureCommunitySection's own comment already gives for why that's
        // wasteful (N live outbound requests per dialog-open, most for
        // entries nobody ever expands). Shows the section (with at least
        // the link) even when the fetch itself finds no notes -- the link
        // must never end up orphaned outside "Release notes", whether or
        // not there turned out to be real notes to put above it. Never
        // re-fetched on a later re-expand, same "built once" rule as
        // ensureCommunitySection.
        let releaseNotesFetchStarted = false;
        const ensureReleaseNotesSection = () => {
          if (
            (entry.release_notes && !releaseNotesLooksWrongForThisJump) ||
            releaseNotesFetchStarted ||
            !entry.release_url
          ) {
            return;
          }
          releaseNotesFetchStarted = true;
          // Same "reserve the space instead of leaving a sudden gap"
          // treatment as the pending-update section's own release notes
          // (see buildReleaseNotesLoader's own comment) -- relevant here
          // too, even though this card is only ever fetched once actually
          // expanded (lazy, see this closure's own comment above): the
          // fetch itself can still take a moment after that click.
          const loader = buildReleaseNotesLoader();
          expandWrap.insertBefore(loader, changelogAnchor.nextSibling);
          this._fetchGithubReleaseNotesFallback(entry.release_url, entry.from_version, entry.to_version).then(({ notes, correctedUrl }) => {
            loader.remove();
            if (isDialogStale()) return;
            // changelogAnchor.nextSibling evaluated fresh right here (not
            // captured any earlier) -- whatever else has landed right after
            // changelogAnchor by the time this actually resolves (e.g. the
            // Community section below, if that happened to finish first)
            // stays exactly where it is, now that the loader right above
            // this comment has already removed itself from that same spot.
            // Captured once into a local, not re-evaluated for the
            // _appendUpstreamReleaseNotes call below -- insertReleaseNotesSection's
            // own insertions already moved what used to be right after
            // changelogAnchor, so a second, fresh read at that point would
            // find the wrong node (its own just-inserted <hr>, not the
            // original insertion point).
            const insertionPoint = changelogAnchor.nextSibling;
            insertReleaseNotesSection(expandWrap, insertionPoint, tr, notes, entry.release_url, entry.from_version, entry.to_version, correctedUrl);
            if (notes) this._appendUpstreamReleaseNotes(expandWrap, insertionPoint, tr, notes, entry.release_url, entry.from_version, entry.to_version);
          });
        };

        // Built lazily, once, the first time this entry's card is expanded
        // -- not eagerly for every entry when the dialog opens. Direct user
        // feedback, 2026-07-25: voting moves here from a single fixed
        // section elsewhere in the dialog, but websocket_api.py's own
        // verdict_for_version handler is deliberately never cached ("one
        // extra live HTTP GET... the right price for always tell the truth
        // right now" -- see that handler's own docstring), so building this
        // for every entry unconditionally would turn one dialog-open into N
        // live outbound requests for an entity with N history entries.
        // Always Journey B (allowHealthy=true): every entry here is, by
        // definition, already installed. Never rebuilt again once built --
        // re-collapsing and re-expanding the same entry just shows/hides
        // the same content, no refetch.
        let entryCommunitySection = null;
        const ensureCommunitySection = () => {
          if (entryCommunitySection) return;
          entryCommunitySection = this._buildCommunitySection(
            tr, entityId, entry.from_version, entry.to_version, true, isDialogStale
          );
          // Inserted right before changelogAnchor, not appended at the end
          // -- puts it between the plain facts above and the changelog/
          // release notes below, regardless of how long the notes are (see
          // changelogAnchor's own comment). No extra <hr> before the
          // section itself -- _buildCommunitySection already adds its own
          // leading divider (that's the facts/votes boundary). No trailing
          // <hr> added here either (removed 2026-08-01, direct user
          // feedback -- "tussen community en release notes 2 dividers?"):
          // the release-notes section (insertReleaseNotesSection, wired up
          // above) now always adds its own leading <hr> right before its
          // own "Release notes" heading whenever it actually has content
          // (both the synchronous entry.release_notes path and the async
          // GitHub-fallback path), so a second,
          // separately-added one here just duplicated it. That also fixes
          // the same edge case the old comment here used to guard for a
          // different way (an entry.release_url whose async fallback fetch
          // never actually resolves any notes) -- the old check only ever
          // looked at entry.release_url being *present*, not whether notes
          // were actually found, so it could still add a boundary divider
          // with nothing below it to divide.
          if (entryCommunitySection) {
            expandWrap.insertBefore(entryCommunitySection, changelogAnchor);
          }
        };
        if (isDefaultExpanded) {
          ensureCommunitySection();
          ensureReleaseNotesSection();
        }

        content.appendChild(expandWrap);
        row.addEventListener("click", () => {
          expandWrap.hidden = !expandWrap.hidden;
          chevron.classList.toggle("open", !expandWrap.hidden);
          if (!expandWrap.hidden) {
            ensureCommunitySection();
            ensureReleaseNotesSection();
          }
        });

        card.appendChild(content);
        list.appendChild(card);
      });
      body.appendChild(list);
    }

    dialog.appendChild(body);

    // slot="footer" -- ha-dialog's own real footer area (confirmed against
    // its current, WebAwesome-based implementation: ::slotted([slot="footer"])
    // already gives it the right flex/gap/padding, nothing to add here),
    // not an unslotted div. That was the actual bug behind broken
    // scrolling and cramped-looking buttons: an unslotted sticky-positioned
    // div was landing inside ha-dialog's own scrollable body alongside
    // everything else instead of in its dedicated footer slot. Same real
    // update.clear_skipped service HA's own dialog calls (verified
    // against update/services.yaml, not guessed) -- Unskip/Skip are
    // plain/text-style (secondary), Open update is the one filled
    // (primary) action when it's actually the recommended next step
    // (see canOpenUpdate below).
    const actions = document.createElement("div");
    actions.slot = "footer";

    // Unskip specifically (not Cancel, see the status-alert block above --
    // direct user feedback, 2026-07-29: Cancel belongs right next to the
    // "will update automatically at X" text it actually cancels, moving
    // it here made it read as closing the dialog rather than acting on
    // that specific scheduled install) lives in the same footer as Skip,
    // its own opposite action -- turning postponement-hiding on and off
    // for this update belong in one consistent place.
    if (showPendingUpdate) {
      // A real, user-initiated skip (see coordinator.py's own
      // is_own_skip distinction -- our own staging_skip.py auto-skips
      // never reach this status at all, they just read as "waiting") --
      // one-click undo via HA's own real update.clear_skipped, not
      // something you'd otherwise have to remember to do from HA's own
      // device page instead.
      if (u.status === "skipped") {
        const unskipBtn = document.createElement("ha-progress-button");
        unskipBtn.appearance = "plain";
        unskipBtn.label = tr.dialog_unskip;
        unskipBtn.disabled = updateIsInstalling(this._dialogLastState);
        unskipBtn.addEventListener("click", () =>
          _runProgressAction(unskipBtn, async () => {
            await this._hass.callWS({ type: "update_manager/unskip", entity_id: entityId });
            await this._afterDialogAction(entityId);
          })
        );
        actions.appendChild(unskipBtn);
        this._dialogActionButtons.push(unskipBtn);
      }
    }

    // Same showPendingUpdate guard as the body content above -- no Skip
    // for the entity's unrelated pending update either when this dialog
    // was opened for one specific past History entry. Only shown as a
    // reaction to our own community-verdict signal (found by review,
    // 2026-07-29, part of handing Install off to HA's own dialog below):
    // shown unconditionally, Skip was just as much "namaak" of HA's own
    // generic skip capability as Install was, now that "Open update"
    // below gives access to HA's own Skip too -- it earns its place here
    // specifically as a reaction to a reported problem on this exact
    // jump, not as a bare, context-free convenience. Deliberately not the
    // same condition as the "held back" alert above (which also checks
    // auto_install_excluded/trusted_vote): Skip is a personal decision
    // independent of whether auto-install would have happened anyway --
    // even an always-manual Core/Supervisor/OS update, or one with a
    // trusted-healthy override in play, can still be worth skipping
    // yourself over a reported problem.
    // Reuses communityProblematicCount (hoisted near the top of this
    // method, alongside heldBackByCommunity) instead of re-deriving the
    // same u.community_verdict.problematic_count independently a second
    // time (found by code review, 2026-07-29) -- one shared fact, not two
    // copies that could silently drift apart.
    const hasProblematicVote = communityProblematicCount > 0;
    if (showPendingUpdate && u.status !== "skipped" && hasProblematicVote) {
      const skipBtn = document.createElement("ha-progress-button");
      skipBtn.appearance = "plain";
      skipBtn.label = tr.dialog_skip;
      skipBtn.disabled = updateIsInstalling(this._dialogLastState);
      skipBtn.addEventListener("click", () =>
        _runProgressAction(skipBtn, async () => {
          // update_manager/skip, not a plain hass.callService -- this
          // entity might already be auto-skipped by our own
          // hide_postponed feature (staging_skip.py), in which case a
          // bare update.skip service call is a genuine no-op (skipped_
          // version already equals latest_version) and nothing would
          // visibly change. The websocket command also relinquishes
          // staging_skip.py's own record first, so this explicit,
          // user-initiated skip is actually reflected.
          await this._hass.callWS({ type: "update_manager/skip", entity_id: entityId });
          await this._afterDialogAction(entityId);
        })
      );
      actions.appendChild(skipBtn);
      this._dialogActionButtons.push(skipBtn);
    }

    // The primary action: hand off to HA's own real more-info-update
    // dialog (its own Install button, live progress, and backup
    // checkbox) instead of mimicking it ourselves -- direct user
    // feedback, 2026-07-29: our own copy was "namaak", not a real
    // addition, and re-implementing it is exactly what both real bugs
    // this session (release_summary rendering raw HTML as literal text,
    // a [hidden] CSS-specificity bug) had in common. "Open update" only
    // when there's an actual pending, installable update to open (same
    // condition the old Install button used); otherwise -- opened
    // directly from the History tab, or a pending update that isn't
    // installable at all, e.g. manual-flash-only firmware -- falls back
    // to a plain, generic "More info", since there's nothing specific to
    // "open" in either of those cases.
    //
    // Doesn't close this dialog first (changed from this button's own
    // previous "More info" behavior -- no reason found in this file's
    // history for why it used to): closing HA's own dialog should
    // naturally reveal this one again underneath, instead of leaving the
    // user back at the bare Updates list.
    const canOpenUpdate = !!(showPendingUpdate && u.installable);
    const openBtn = document.createElement("ha-progress-button");
    if (canOpenUpdate) {
      // A queued (not yet dispatched) Zigbee rollout entry can't jump the
      // line from here either (no-override decision, see
      // rollout_manager.py's own docstring): same "waiting for X" text
      // the queue card itself shows, button disabled instead of opening
      // HA's own dialog -- opening it would let someone install directly
      // there, bypassing the whole point of pacing.
      const rolloutStatus = this._rolloutStatusFor(entityId);
      const isQueued = !!(rolloutStatus && rolloutStatus.status === "queued");
      // "accent" (not "filled") for the genuinely strong/primary look --
      // confirmed against ha-button's own real source: "filled" uses the
      // softer --wa-color-fill-normal, "accent" the bolder --wa-color-
      // fill-loud, exactly the "loud" variant meant for a page's one
      // primary action. Direct user feedback, 2026-07-29, after seeing
      // "filled" render as a pale, secondary-looking blue: "voelt
      // secondair ipv primair." Only "accent" once this is actually ready
      // -- "bij een update die ready is kan de open update knop wel
      // gewoon primair zijn" -- while still waiting/skipped/blocked,
      // encouraging manual install with the loudest button in the dialog
      // would work against the whole point of staging in the first
      // place. Still the exact same button either way, just quieter
      // until there's actually something to act on now. Also plain, not
      // accent, whenever heldBackByCommunity (found by code review,
      // 2026-07-29): a "ready" update the community has flagged still had
      // its loudest button inviting exactly the manual install the
      // warning right above it is discouraging.
      openBtn.appearance = u.status === "ready" && !heldBackByCommunity ? "accent" : "plain";
      openBtn.label = isQueued
        ? tr.rollout_queue_waiting(friendlyEntityName(this._hass, rolloutStatus.frontEntityId))
        : tr.dialog_open_update;
      openBtn.disabled = isQueued || updateButtonIsDisabled(this._dialogLastState);
    } else {
      openBtn.appearance = "plain";
      openBtn.label = tr.dialog_more_info;
    }
    openBtn.addEventListener("click", () => {
      // A rollout-group member (any status, not just "queued") installs
      // via update_manager/install directly instead of opening HA's own
      // dialog -- found by code review, 2026-07-29: rollout_manager.py's
      // own pacing is only ever consulted through that websocket command
      // (see websocket_api.py's own _handle_install); HA's real dialog
      // calls update.install directly, completely invisible to it. Two
      // identical Zigbee devices could otherwise both install at once by
      // going through HA's own dialog one after the other, exactly the
      // mesh-instability scenario this whole feature exists to prevent --
      // isQueued alone (disabling the button while waiting your turn)
      // wasn't enough, since a *not yet queued* member handing off to
      // HA's dialog was just as capable of racing a sibling that starts
      // installing microseconds later.
      const rolloutStatus = canOpenUpdate ? this._rolloutStatusFor(entityId) : null;
      if (canOpenUpdate && rolloutStatus && rolloutStatus.status !== "queued") {
        _runProgressAction(openBtn, async () => {
          const msg = { type: "update_manager/install", entity_id: entityId };
          if (state && (state.attributes.supported_features || 0) & 8) msg.backup = true;
          await this._hass.callWS(msg);
        });
        return;
      }
      this._openMoreInfo(entityId);
    });
    actions.appendChild(openBtn);

    dialog.appendChild(actions);

    // A short, fixed delay before actually showing the dialog -- direct
    // user feedback, 2026-08-01: "de dialogs lijken allemaal vlak na het
    // openen te verspringen omdat er dan nieuwe data is geladen" (the
    // Community section and Release notes above are both still-pending
    // fetches at this exact point, each popping in and shifting layout
    // once they land). Deliberately NOT tied to those actual fetches
    // finishing (awaiting them would be the more correct fix, but a
    // slower one to land) -- explicit user tradeoff: "een vaste vertraging
    // die de meeste gevallen dekt is voldoende", and just as important,
    // "het moet niet opvallen, je moet nog steeds het idee hebben dat de
    // dialog direct opent". 150ms (bumped up from the original 100ms,
    // 2026-08-02, alongside the release-notes loader below) is still short
    // enough to stay under the generally-cited "feels instant" perception
    // threshold, long enough to let most of these fetches (a single small
    // JSON file/websocket round-trip each) land before anything is
    // actually shown -- won't catch every slow one, that's the accepted
    // trade-off, and Release notes specifically no longer needs to rely on
    // this delay alone anymore either way (see buildReleaseNotesLoader's
    // own comment: that section now reserves its own stable space instead
    // of popping in, the same technique HA core's own native dialog uses
    // for this exact problem). isDialogStale guards the rare case this
    // entity's dialog was closed or reopened for someone else before the
    // delay elapsed.
    setTimeout(() => {
      if (!isDialogStale()) dialog.open = true;
    }, 150);
  }

  // Debounced, not fired on every single value-changed event -- ha-form's
  // number selector (wait_days/announce_hours) fires that on every
  // keystroke while typing, and saving mid-edit would recompute staging
  // rules against a half-typed number each time. 800ms of no further edits
  // before it actually saves.
  _scheduleAutosave() {
    clearTimeout(this._autosaveTimer);
    this._autosaveTimer = setTimeout(() => {
      this._autosaveTimer = null;
      this._saveSettingsNow();
    }, 800);
  }

  async _saveSettingsNow() {
    const settingsOnly = pickKnownSettings(this._formData);
    try {
      await this._hass.callWS({ type: "update_manager/save_settings", ...settingsOnly });
      this._settings = { ...settingsOnly };
      // Re-fetch Updates/History too, not just settings -- new rules can
      // change an entity's ready/waiting/blocked verdict immediately (see
      // coordinator.py's async_update_rules). Doesn't re-render (this only
      // updates the background data model): the Settings tab is what's
      // open right now, and rebuilding its own form mid-edit would drop
      // focus/cursor position out from under the user.
      await this._loadAll();
      this._showToast(this._tr.settings_saved_toast);
    } catch (err) {
      this._showToast((err && err.message) || String(err));
    }
  }

  // "General": the settings that aren't specific to any one update size,
  // the master pause switch (const.py's CONF_ENABLED) and whether a
  // postponed update stays hidden from Home Assistant's own update count
  // (const.py's CONF_HIDE_POSTPONED). First card on the page, above "Update
  // rules": merged from two separate cards (2026-07-21, direct user
  // feedback: both were "general Update Manager settings", not a rule
  // about any one size, and having them apart read as two unrelated
  // toggles rather than one coherent "how does Update Manager behave
  // overall" section). No intro paragraph explaining "postponed" here
  // anymore either (also direct user feedback, same day): that concept is
  // about the per-size wait itself, not a general behavior, so belongs
  // with "Postponement period" in Update rules, not up here, and the
  // page had too much text regardless. The word carries enough of its own
  // meaning in context (a field literally called "Postponement period"
  // right below, "Hide postponed updates" here) without a paragraph
  // spelling it out first.
  // Plain ha-form, both fields' label and helper fully native (reverted
  // 2026-07-21, direct user feedback after trying both a hand-built
  // ha-settings-row version and a split-per-field manual-.hint version:
  // neither was wanted, this plain ha-form rendering is "how it was" and
  // should stay that way).
  _buildGeneralCard(tr) {
    const card = document.createElement("ha-card");
    card.outlined = true;
    card.header = tr.enabled_section_title;

    const body = document.createElement("div");
    body.className = "card-content";

    const form = document.createElement("ha-form");
    form.hass = this._hass;
    form.schema = [
      { name: "enabled", selector: { boolean: {} } },
      { name: "hide_postponed", selector: { boolean: {} } },
    ];
    form.data = this._formData;
    form.computeLabel = (s) => (s.name === "enabled" ? tr.field_enabled : tr.field_hide_postponed);
    form.computeHelper = (s) => (s.name === "enabled" ? tr.field_enabled_helper : tr.field_hide_postponed_helper);
    form.addEventListener("value-changed", (e) => {
      this._formData = { ...this._formData, ...e.detail.value };
      form.data = this._formData;
      this._scheduleAutosave();
    });
    body.appendChild(form);
    card.appendChild(body);
    return card;
  }

  // ha-card + ha-progress-button, the same building blocks (and .card-content/
  // .card-actions convention) /config/general's own settings cards use --
  // verified against that page's actual source, not guessed, per direct user
  // feedback that a hand-rolled settings block didn't feel HA-native either.
  // Two cards, not one long one -- direct user feedback. "Update rules" (the
  // per-size wait/auto-install rules) and "Auto-install" (announcement +
  // always-manual entities) are two different concerns that only sometimes
  // both apply, and splitting them means the always-manual entity list
  // (which can grow long) no longer pushes the announcement setting further
  // down the page. Both still write into the same shared this._formData and
  // save through one shared button below both cards -- it's still one
  // underlying settings payload, just two visual groups of it.
  _buildSettingsCard() {
    const tr = this._tr;
    const wrap = document.createElement("div");
    wrap.className = "settings-cards";

    // First, above every other card: the settings that apply regardless
    // of size (see _buildGeneralCard), not a rule about any one of them.
    wrap.appendChild(this._buildGeneralCard(tr));

    wrap.appendChild(this._buildUpdateRulesCard(tr));
    // Always rendered now (changed 2026-07-23): used to only appear once
    // some size's own auto_install toggle was on, but the trusted-voter
    // override living in this same card (see _buildAutoInstallCard) is
    // reachable independent of any size toggle -- direct user feedback,
    // "installeer altijd automatisch als [klaptafel] een update als healthy
    // heeft beoordeeld, ongeacht mijn eigen rules" makes no sense to hide
    // behind a size setting that isn't otherwise involved.
    wrap.appendChild(this._buildAutoInstallCard(tr));
    // No explicit Save button -- every field autosaves itself (debounced,
    // see _scheduleAutosave), direct user feedback: "kunnen we niet direct
    // saven bij elke edit ipv via een losse button?".

    wrap.appendChild(this._buildCommunityCard(tr));

    // Always last, below every card -- same "Slideshow Card vX.Y.Z" link
    // this project's own sibling Lovelace cards already put at the bottom
    // of their editor, direct user feedback: "die GitHub link met versie
    // die we in elke card editor in de footer hebben staan wil ik voor
    // update manager helemaal onderop de settings pagina hebben".
    wrap.appendChild(this._buildVersionLink());

    return wrap;
  }

  _buildVersionLink() {
    const link = document.createElement("a");
    link.href = "https://github.com/HA-Update-Manager/ha-update-manager";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.className = "version-link";
    const version = this._panel && this._panel.config && this._panel.config.integration_version;
    link.textContent = version ? `Update Manager v${version}` : "Update Manager";
    return link;
  }

  // Account linking only (read-only slice, 2026-07-22): no voting UI yet,
  // just "is a GitHub account linked or not". Device Flow, not the usual
  // OAuth redirect: no client secret needed anywhere, matching this whole
  // feature's own "no hosted server" principle (see FUTURE.md/
  // github_auth.py). this._communityLinkPollTimer is cleared unconditionally
  // up front, not just on success/failure: rebuilding this card (a tab
  // switch, any other settings re-render) must never leave a previous
  // card's poll loop running detached in the background.
  _buildCommunityCard(tr) {
    if (this._communityLinkPollTimer) {
      clearInterval(this._communityLinkPollTimer);
      this._communityLinkPollTimer = null;
    }

    const card = document.createElement("ha-card");
    card.outlined = true;
    card.header = tr.community_section_title;

    const body = document.createElement("div");
    body.className = "card-content";

    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = tr.community_section_desc;
    body.appendChild(hint);

    const statusContainer = document.createElement("div");
    body.appendChild(statusContainer);
    card.appendChild(body);

    const renderNotLinked = () => {
      if (this._communityLinkPollTimer) {
        clearInterval(this._communityLinkPollTimer);
        this._communityLinkPollTimer = null;
      }
      statusContainer.innerHTML = "";
      const linkBtn = document.createElement("ha-progress-button");
      linkBtn.appearance = "filled";
      linkBtn.label = tr.community_link;
      linkBtn.addEventListener("click", () =>
        _runProgressAction(linkBtn, async () => {
          const result = await this._hass.callWS({ type: "update_manager/github_link_start" });
          renderPending(result);
        })
      );
      statusContainer.appendChild(linkBtn);
    };

    const renderLinked = (username) => {
      statusContainer.innerHTML = "";
      const linkedText = document.createElement("p");
      linkedText.textContent = tr.community_linked_as(username);
      statusContainer.appendChild(linkedText);
      const unlinkBtn = document.createElement("ha-progress-button");
      unlinkBtn.appearance = "plain";
      unlinkBtn.label = tr.community_unlink;
      unlinkBtn.addEventListener("click", () =>
        _runProgressAction(unlinkBtn, async () => {
          await this._hass.callWS({ type: "update_manager/github_unlink" });
          renderNotLinked();
        })
      );
      statusContainer.appendChild(unlinkBtn);
    };

    const renderPending = (result) => {
      statusContainer.innerHTML = "";
      const instructions = document.createElement("p");
      instructions.textContent = tr.community_link_instructions;
      statusContainer.appendChild(instructions);

      const codeEl = document.createElement("p");
      codeEl.className = "community-link-code";
      codeEl.textContent = result.user_code;
      statusContainer.appendChild(codeEl);

      const link = document.createElement("a");
      link.href = result.verification_uri;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = result.verification_uri;
      statusContainer.appendChild(link);

      const waiting = document.createElement("p");
      waiting.className = "hint";
      waiting.textContent = tr.community_link_waiting;
      statusContainer.appendChild(waiting);

      const deadline = Date.now() + result.expires_in * 1000;
      this._communityLinkPollTimer = setInterval(async () => {
        if (Date.now() > deadline) {
          renderNotLinked();
          this._showToast(tr.community_link_timed_out);
          return;
        }
        const status = await this._hass.callWS({ type: "update_manager/github_link_status" });
        if (status.status === "linked") {
          renderLinked(status.username);
        } else if (status.status === "failed") {
          renderNotLinked();
          this._showToast(tr.community_link_failed);
        }
      }, 3000);
    };

    this._hass.callWS({ type: "update_manager/github_link_status" }).then((status) => {
      if (status.status === "linked") renderLinked(status.username);
      else renderNotLinked();
    });

    return card;
  }

  // The dialog's own Community section: a compact verdict readout plus
  // vote controls, scoped to the exact (fromVersion, toVersion) jump the
  // caller supplies -- either the entity's own current pending jump
  // (Journey A, `allowHealthy=false`, from _openDetailDialog's own `if (u)`
  // block) or one specific History entry's own jump (Journey B,
  // `allowHealthy=true`, from that entry's own expandable card, see the
  // entries.forEach loop further down). Changed 2026-07-25: used to derive
  // both the jump and the Journey from an ambient `historyEntry`/`u` pair
  // (with `historyEntry` always winning), which only ever allowed one
  // vote section per dialog and could let a not-yet-installed version get
  // voted "healthy" if a historyEntry happened to also be passed --
  // callers now supply everything explicitly, so this can be called once
  // per History entry too, not just once per dialog. Returns null (nothing
  // to build or insert) if either version is missing. Built as a
  // standalone element rather than appended inline, so each caller can
  // insert it wherever it belongs (among the pending-update's own facts,
  // or inside one History entry's own expanded card) instead of this
  // method deciding that itself.
  //
  // Hidden until the identifiable check below resolves, so an
  // unidentifiable entity (e.g. a Zigbee device update with no release_url
  // and no recognized vendor device firmware) never flashes content it's
  // then immediately hidden again. The disclaimer that used to be its own
  // permanent paragraph is now the row's own `title` tooltip instead --
  // direct user feedback, 2026-07-22: the section read as cluttered, and a
  // sentence that's the same for every single vote didn't need to always
  // cost its own line.
  _buildCommunitySection(tr, entityId, fromVersion, toVersion, allowHealthy, isDialogStale) {
    if (!toVersion || !fromVersion) return null;

    const section = document.createElement("div");
    section.className = "dialog-community-section";
    section.hidden = true;
    section.appendChild(document.createElement("hr"));
    // Added 2026-08-01, direct user feedback: History already had its own
    // "History" heading, this section and release notes didn't, reading as
    // inconsistent once pointed out. Reverses this section's own earlier,
    // deliberate "icon + sentence, no heading" choice from 2026-07-22 (see
    // the comment right below) -- that choice still holds for *within* the
    // section (no separate disclaimer paragraph on top of the verdict
    // sentence), just not for labeling the section itself anymore.
    const heading = document.createElement("h3");
    heading.textContent = tr.dialog_community_heading;
    section.appendChild(heading);

    // The verdict fact rows share their own tight-gapped group, separate
    // from the section's own wider gap to the action controls below --
    // direct user feedback, 2026-07-22: uniform spacing throughout made the
    // whole section read as one dense stack, with no visual cue that the
    // top lines are "information" and what's below is "things you can do
    // about it".
    const infoGroup = document.createElement("div");
    infoGroup.className = "dialog-community-info";
    section.appendChild(infoGroup);

    // Icon + sentence, not a separate heading plus a separate disclaimer
    // paragraph on top. The icon is only ever appended once there's a real
    // fact to show, not created upfront and toggled via .hidden -- found
    // live, 2026-07-22: ha-svg-icon's own shadow-DOM styles set `:host {
    // display: inline-flex }` unconditionally, with no `:host([hidden])`
    // override, so the `hidden` attribute never actually collapsed it, only
    // left an empty, pathless icon-sized gap sitting in front of the text.
    const verdictRow = document.createElement("div");
    verdictRow.className = "dialog-community-verdict-line";
    verdictRow.title = tr.dialog_community_verdict_disclaimer;
    const verdictText = document.createElement("span");
    verdictText.textContent = tr.community_not_yet_rated;
    verdictRow.appendChild(verdictText);
    infoGroup.appendChild(verdictRow);

    const controlsContainer = document.createElement("div");
    controlsContainer.className = "dialog-vote";
    section.appendChild(controlsContainer);

    (async () => {
      let result;
      try {
        result = await this._hass.callWS({
          type: "update_manager/verdict_for_version",
          entity_id: entityId,
          version: toVersion,
        });
      } catch {
        return;
      }
      // Stale by the time it resolves (dialog closed, or reopened for a
      // different entity) -- same staleness guard the release-notes fetch
      // uses.
      if (isDialogStale() || !result.identifiable) return;
      section.hidden = false;

      // Row 1: your own vote, shown as its own fact whenever you have one --
      // regardless of whether it agrees with the wider aggregate below
      // (redesigned 2026-07-27, direct user feedback: a dissenting vote used
      // to be silently dropped from the sentence entirely). No vote of your
      // own, but the aggregate has votes: this row is hidden entirely, the
      // aggregate row below covers it on its own ("N people reported...").
      // No votes at all, anywhere: this row states that plainly.
      const counts = result.verdict || { healthy_count: 0, problematic_count: 0 };
      const myVerdict = result.my_verdict;
      if (myVerdict) {
        applyMyVerdictRow(verdictRow, verdictText, tr, myVerdict);
      } else if (counts.healthy_count === 0 && counts.problematic_count === 0) {
        verdictText.textContent = tr.community_not_yet_rated;
      } else {
        verdictRow.hidden = true;
      }

      // Row 2: everyone else's votes, if any beyond your own -- both counts
      // shown when genuinely mixed (see aggregateVerdictText), "others"
      // perspective when Row 1 above already shows your own vote (these
      // counts then exclude it), "people" perspective otherwise. Rebuilt
      // (not just built once here), via updateAggregateRow below, after you
      // cast a vote -- direct user feedback, 2026-07-27, found by code
      // review: casting a vote used to only update Row 1, leaving this row
      // stuck on its pre-vote perspective/count (still "people", still
      // counting your own just-cast vote in its total) instead of switching
      // to "others" and excluding it. `counts` itself stays frozen at this
      // one fetch's numbers throughout (the external aggregate hasn't
      // processed your vote yet either way) -- same deliberately optimistic
      // principle already used for the vote confirmation text itself.
      let aggregateRow = null;
      const updateAggregateRow = (currentMyVerdict) => {
        const othersHealthy = Math.max(0, counts.healthy_count - (currentMyVerdict === "healthy" ? 1 : 0));
        const othersProblematic = Math.max(0, counts.problematic_count - (currentMyVerdict === "problematic" ? 1 : 0));
        const aggregateText = aggregateVerdictText(tr, othersHealthy, othersProblematic, currentMyVerdict ? "others" : "people");
        if (!aggregateText) {
          if (aggregateRow) aggregateRow.remove();
          aggregateRow = null;
          return;
        }
        if (aggregateRow) {
          aggregateRow.querySelector("ha-svg-icon").path = verdictIcon(othersProblematic > 0);
          aggregateRow.querySelector("span").textContent = aggregateText;
        } else {
          aggregateRow = buildVerdictLineRow(verdictIcon(othersProblematic > 0), aggregateText, tr.dialog_community_verdict_disclaimer);
          // Right after Row 1, not just appended at infoGroup's current end
          // -- infoGroup is still empty of everything else at this point in
          // the build (trusted-vote/other-jumps rows are only added below),
          // but inserting relative to verdictRow rather than relying on
          // build order keeps this correct even if that ordering ever
          // changes.
          infoGroup.insertBefore(aggregateRow, verdictRow.nextSibling);
        }
      };
      updateAggregateRow(myVerdict);

      // Your own reason (only when you voted problematic and gave one),
      // right under your own vote line -- found by review, 2026-07-29,
      // auditing the whole section for overlap/redundancy: it used to show
      // up a second time, unattributed, in the generic reasons list below,
      // reading as a confusing, seemingly-unrelated extra entry rather than
      // detail on the vote already named right above it. Split server-side
      // (websocket_api.py's own linked_username, already resolved for
      // my_verdict anyway) since only the backend knows your own username.
      // Inserted right after whatever's currently last of verdictRow/
      // aggregateRow, not a fixed position, so it lands after "N others
      // reported..." if that row exists, or directly after your own vote
      // line if it doesn't.
      if (result.my_reason) {
        infoGroup.insertBefore(buildReasonItem(tr, result.my_reason), (aggregateRow || verdictRow).nextSibling);
      }

      // Whether a configured trusted voter is among the people who voted
      // on this exact jump -- direct user feedback, 2026-07-27 ("toevallig
      // mijn trusted voter die heeft gestemd, maar dat zie ik niet terug"),
      // this is exactly the fact that changes auto-install behavior for
      // this jump (see announcer.py's own effective_auto_install_state), so
      // it gets its own line right next to the primary verdict, not folded
      // into that sentence (folding "you" and "trusted voter(s)" into one
      // grammatically correct sentence for every combination of the two
      // wasn't worth the complexity). Not shown if the same person is both
      // "you" and the trusted voter who voted -- a real but rare edge case,
      // left as a minor known simplification rather than plumbing your own
      // linked username through here just to de-duplicate one line.
      if (result.trusted_voters_matched && result.trusted_voters_matched.length) {
        const names = joinUsernames(tr, result.trusted_voters_matched);
        const text =
          result.trusted_vote === "problematic"
            ? tr.community_trusted_vote_problematic(names)
            : tr.community_trusted_vote_healthy(names);
        infoGroup.appendChild(buildVerdictLineRow(verdictIcon(result.trusted_vote === "problematic"), text));
      }

      // Other jumps landing on this same destination version, if any --
      // direct user feedback, 2026-07-24: "in de update dialog wil ik dan
      // ook zien welke sprongen naar de gewenste nieuwe versie wel en niet
      // als veilig zijn beoordeeld", with my own jump (verdictRow above)
      // always shown first/primary. Nothing rendered at all when there
      // simply aren't any yet (no empty-state message) -- this data is
      // inherently sparse early on, and a "nothing here" line would just
      // be noise for the common case.
      if (result.other_jumps && result.other_jumps.length) {
        const otherJumpsHeading = document.createElement("p");
        otherJumpsHeading.className = "hint";
        otherJumpsHeading.textContent = tr.community_other_jumps_heading;
        infoGroup.appendChild(otherJumpsHeading);
        result.other_jumps.forEach((jump) => {
          // Reuses verdictBadge (the exact same healthy/problematic-count
          // derivation the Updates-tab row's own pill and this section's
          // own verdictRow above already use), rather than re-deriving the
          // icon/count/direction logic a third time.
          const badge = verdictBadge(tr, jump);
          if (!badge) return;
          infoGroup.appendChild(buildVerdictLineRow(badge.icon, tr.community_other_jump_line(jump.from_version, badge.title)));
        });
      }

      // Every *other* problematic voter's own reason for this exact jump
      // (your own, if any, is already handled above as my_reason) -- direct
      // user feedback, 2026-07-29: "ik zie in de interface nergens de
      // reden staan. Dat had ik wel verwacht." A vote's reason was
      // collected on submission (see _buildVoteControls/_VOTE_REASON_LABEL_KEYS
      // below) but never read back anywhere until now; reusing that same
      // label map here so the vocabulary reads identically going in and
      // coming back out. A reason from a configured trusted voter is marked
      // as such (found by review, same audit as my_reason above): otherwise
      // it read as an unattributed, seemingly unrelated entry with no link
      // back to the "Trusted vote: @name..." line already shown above it,
      // even though it's the exact same vote. Nothing rendered when there
      // aren't any yet, same reasoning as other_jumps above.
      if (result.problematic_reasons && result.problematic_reasons.length) {
        const reasonsHeading = document.createElement("p");
        reasonsHeading.className = "hint";
        reasonsHeading.textContent = tr.community_problematic_reasons_heading;
        infoGroup.appendChild(reasonsHeading);
        const trustedUsernames = result.trusted_voters_matched || [];
        result.problematic_reasons.forEach((reason) => {
          const trusted = trustedUsernames.includes(reason.username);
          infoGroup.appendChild(buildReasonItem(tr, reason, { trusted }));
        });
      }

      const status = await this._hass.callWS({ type: "update_manager/github_link_status" });
      if (isDialogStale()) return;
      if (status.status !== "linked") {
        const prompt = document.createElement("p");
        prompt.className = "hint";
        prompt.textContent = tr.community_vote_link_prompt;
        controlsContainer.appendChild(prompt);
        return;
      }
      this._buildVoteControls(controlsContainer, tr, entityId, toVersion, allowHealthy, myVerdict, (verdict) => {
        applyMyVerdictRow(verdictRow, verdictText, tr, verdict);
        updateAggregateRow(verdict);
      });
    })();

    return section;
  }

  // The dialog's own vote controls (see _openDetailDialog's Community
  // section), only ever built once the caller already confirmed the
  // account is linked and this exact version is identifiable. Two journeys,
  // asked for by direct user feedback (2026-07-22) after a careful think-
  // through of the actual user flows involved:
  //
  // - Journey A, allowHealthy=false (opened from the Updates tab, for a
  //   still-*pending* update): there's no firsthand experience to report
  //   yet, so no "healthy" button, and the mini-form is collapsed behind a
  //   toggle (same collapse mechanism Journey B's own "problematic" form
  //   already uses, see toggleBtn below) -- direct user feedback,
  //   2026-07-22: an always-open 3-field form made this dialog feel
  //   cluttered for what's a rare, optional action. Limited to the three
  //   reasons knowable before installing at all -- already-documented
  //   release-notes issues (breaking change, requires a newer HA version,
  //   a dev/pre-release build). Letting someone warn others about a known
  //   breaking change before anyone actually has to eat it was the whole
  //   point of adding this: direct user feedback was that requiring an
  //   install-first, break-first, warn-only-after approach would be a
  //   strange way to handle a problem that's already documented in the
  //   release notes ahead of time.
  // - Journey B, allowHealthy=true (opened from the History tab, for a
  //   specific *installed* -- or downgraded-to -- version): full voting,
  //   "healthy" is a single click, "problematic" expands the same mini-form
  //   with all five reasons, matching the real community-votes issue
  //   form's own full set.
  //
  // A successful vote replaces `container`'s own contents with a plain
  // confirmation line, not a toast alone -- direct user feedback,
  // 2026-07-22: community-votes' own verdict count only updates once its
  // Action has actually processed the new issue, which can take a moment,
  // and re-fetching right after voting almost always still showed the
  // pre-vote count/"not yet rated" text, reading as if the vote hadn't
  // registered at all. This is a deliberately optimistic, local
  // confirmation of what was just submitted, not a claim about the real,
  // external vote count (that still updates the normal way, next time this
  // dialog is opened fresh). Every failure surfaces the backend's own
  // specific reason via _showToast (not_linked/not_identifiable/
  // vote_failed, see websocket_api.py's own _handle_vote) instead.
  //
  // `onVoted(verdict)`, called the same optimistic way right before
  // showConfirmed: direct user feedback, 2026-07-27, found live -- Row 1
  // above this (see _buildCommunitySection) kept showing "No one's reported
  // on this jump yet." right next to this exact confirmation text after a
  // successful vote, a flat contradiction. Updates that row locally too,
  // same "don't wait on the real external count" principle as
  // showConfirmed itself already uses.
  // myVerdict: your own already-cast verdict for this exact jump, if any
  // (found by review, 2026-07-29, direct user feedback: "waarom zie ik
  // dan nog steeds de 'mark as healthy' knop? Dat heb ik toch al gedaan" --
  // this method used to always build both options fresh, with no idea
  // whether you'd already voted at all). The button matching your current
  // vote is omitted (re-submitting the exact same verdict has nothing to
  // add); the other one stays, so changing your mind is still one click.
  _buildVoteControls(container, tr, entityId, version, allowHealthy, myVerdict, onVoted) {
    const showConfirmed = (text) => {
      container.innerHTML = "";
      const confirmed = document.createElement("p");
      confirmed.className = "dialog-community-confirmed";
      confirmed.textContent = text;
      container.appendChild(confirmed);
    };

    const submitVote = async (verdict, extra) => {
      try {
        // Returns whether this replaced an earlier vote of yours (see
        // websocket_api.py's own is_vote_update), not derived here --
        // community-votes' own process-vote.yml now updates a repeat vote
        // in place instead of rejecting it as a duplicate (2026-07-23).
        return await this._hass.callWS({ type: "update_manager/vote", entity_id: entityId, version, verdict, ...extra });
      } catch (err) {
        this._showToast((err && err.message) || String(err));
        throw err;
      }
    };

    const formContainer = document.createElement("div");
    formContainer.hidden = true;

    if (allowHealthy && myVerdict !== "healthy") {
      const healthyBtn = document.createElement("ha-progress-button");
      healthyBtn.appearance = "filled";
      healthyBtn.label = tr.community_vote_healthy;
      healthyBtn.addEventListener("click", () =>
        _runProgressAction(healthyBtn, async () => {
          const result = await submitVote("healthy", {});
          onVoted?.("healthy");
          showConfirmed(tr.community_vote_confirmed_healthy(result.updated, result.own_repo_healthy_vote));
        })
      );
      container.appendChild(healthyBtn);
    }

    // Always available, regardless of myVerdict -- unlike healthyBtn above
    // (reverted 2026-07-29, direct user feedback: hiding this once already
    // problematic blocked updating the reason/notes/link, or switching
    // from healthy to problematic, with no way back in either case). A
    // problematic vote always has real fields worth revisiting; a healthy
    // one never does, hence the difference in treatment.
    //
    // Filled, not plain (changed 2026-07-29, direct user feedback: this
    // is an action we genuinely want people to take, a soft-background
    // button reads as more inviting/actionable than a bare text link,
    // matching healthyBtn's own visual weight right next to it).
    const toggleBtn = document.createElement("ha-button");
    toggleBtn.appearance = "filled";
    toggleBtn.textContent = allowHealthy ? tr.community_vote_problematic : tr.community_report_toggle;
    toggleBtn.addEventListener("click", () => {
      formContainer.hidden = !formContainer.hidden;
    });
    container.appendChild(toggleBtn);
    container.appendChild(formContainer);

    if (!allowHealthy) {
      const intro = document.createElement("p");
      intro.className = "hint";
      intro.textContent = tr.community_report_intro;
      formContainer.appendChild(intro);
    }

    // Reason options limited to the three release-notes-knowable ones
    // for Journey A (see this method's own docstring above) -- "broken
    // functionality" and "other" both require having actually run the
    // version, which Journey A's caller never has.
    const reasonOptions = (allowHealthy ? _JOURNEY_B_REASON_ORDER : _JOURNEY_A_REASON_ORDER).map((value) => ({
      value,
      label: tr[_VOTE_REASON_LABEL_KEYS[value]],
    }));

    const formData = { reason_category: "", notes: "", link: "" };
    const form = document.createElement("ha-form");
    form.hass = this._hass;
    form.schema = [
      { name: "reason_category", selector: { select: { options: reasonOptions } } },
      { name: "notes", selector: { text: { multiline: true } } },
      { name: "link", selector: { text: {} } },
    ];
    form.data = formData;
    form.computeLabel = (s) => tr[`vote_field_${s.name}`];
    form.addEventListener("value-changed", (e) => {
      Object.assign(formData, e.detail.value);
      form.data = { ...formData };
    });
    formContainer.appendChild(form);

    const submitBtn = document.createElement("ha-progress-button");
    submitBtn.appearance = "filled";
    submitBtn.label = tr.community_vote_submit;
    submitBtn.addEventListener("click", () =>
      _runProgressAction(submitBtn, async () => {
        if (!formData.reason_category) {
          this._showToast(tr.community_vote_reason_required);
          throw new Error("reason_category required");
        }
        const result = await submitVote("problematic", {
          reason_category: formData.reason_category,
          notes: formData.notes || undefined,
          link: formData.link || undefined,
        });
        onVoted?.("problematic");
        const reasonLabel = tr[_VOTE_REASON_LABEL_KEYS[formData.reason_category]];
        showConfirmed(tr.community_vote_confirmed_problematic(reasonLabel, result.updated));
      })
    );
    formContainer.appendChild(submitBtn);
  }

  // "Update rules": plain and functional -- the earlier "Stoplicht"/
  // traffic-light framing (and its emoji-dot legend) was dropped entirely
  // (direct user feedback: the emoji looked bad throughout, and the
  // metaphor wasn't pulling its weight). Once the community layer exists
  // (Fase 1/3, see FUTURE.md) that becomes its own, separately-named card
  // next to this one -- revisit both cards' naming together then, not now.
  _buildUpdateRulesCard(tr) {
    const card = document.createElement("ha-card");
    card.outlined = true;
    card.header = tr.settings_header;

    const body = document.createElement("div");
    body.className = "card-content";

    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = tr.settings_hint;
    body.appendChild(hint);

    // Back to ha-form's own `type: "expandable"` schema entries (reverted
    // 2026-07-21: a hand-built ha-expansion-panel per size was tried
    // instead, to get an auto-install icon next to the chevron, but direct
    // user feedback was that the native ha-form-expandable version, with
    // its own styling/spacing integrated into the rest of this same form,
    // was better, and losing the icon idea was the right trade).
    // expanded is now false, not true: confirmed against ha-form-expandable's
    // own source, the ha-expansion-panel underneath it already lets you
    // click its header to open/close regardless of this initial value, so
    // it only ever controlled the *default* state, which used to be
    // permanently open for no real reason.
    const form = document.createElement("ha-form");
    form.hass = this._hass;
    form.schema = SIZES.map((size) => ({
      name: size,
      type: "expandable",
      title: tr[`size_${size}_short`],
      expanded: false,
      flatten: true,
      // Stacked, not a "grid" side by side (direct user feedback: each
      // should be free to take the full width, a number field and a
      // checkbox don't need to compete for half the row each).
      schema: [
        { name: `${size}_wait_days`, selector: { number: { min: 0, max: 365, mode: "box" } } },
        { name: `${size}_auto_install`, selector: { boolean: {} } },
      ],
    }));
    form.data = this._formData;
    form.computeLabel = (s) => {
      const kind = fieldKind(s.name);
      if (kind === "wait_days") return tr.field_wait_days;
      if (kind === "auto_install") return tr.field_auto_install;
      return s.name;
    };
    form.computeHelper = (s) => {
      // The per-size expandable section's own description (its `name` is
      // just "small"/"medium"/"large"), rendered by ha-form-expandable as
      // its own line below the header, not squeezed into the title
      // itself, and visible regardless of expanded state.
      if (SIZES.includes(s.name)) return tr[`size_${s.name}_desc`]();
      // No per-field helper for auto_install (direct user feedback:
      // text-heavy page): it used to repeat the exact same sentence
      // identically under Small, Medium, and Large, since all three
      // sections used to be always expanded at once. Said once now, in
      // settings_hint above, instead of three times in a row.
      return "";
    };
    form.addEventListener("value-changed", (e) => {
      this._formData = { ...this._formData, ...e.detail.value };
      form.data = this._formData;
      this._scheduleAutosave();
    });
    body.appendChild(form);
    card.appendChild(body);
    return card;
  }

  // Its own card, always rendered regardless of whether any size's own
  // auto-install toggle is on (see _buildSettingsCard's own comment on
  // this: the trusted-voter override living here is reachable independent
  // of any size toggle, so hiding this card behind one made no sense).
  // Announcement above the entities list, not below (direct user feedback:
  // that list can grow long and would push the announcement setting
  // further down the page).
  _buildAutoInstallCard(tr) {
    const card = document.createElement("ha-card");
    card.outlined = true;
    card.header = tr.auto_install_section_title;

    const body = document.createElement("div");
    body.className = "card-content";

    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = tr.auto_install_section_desc;
    body.appendChild(hint);

    // Manually-drawn label + hint, same pattern as excludedLabel/
    // excludedHint below. Direct user feedback: liked that look enough to
    // want it here too, not just on the field it was originally built for,
    // even though this field's own helper never had the same "renders too
    // far below a tall widget" problem excluded_entities did; just for a
    // consistent look across this card.
    const announceLabel = document.createElement("p");
    announceLabel.className = "field-label";
    announceLabel.textContent = tr.announce_hours_label;
    body.appendChild(announceLabel);

    const announceHint = document.createElement("p");
    announceHint.className = "hint";
    announceHint.textContent = tr.announce_hours_helper;
    body.appendChild(announceHint);

    const announceForm = document.createElement("ha-form");
    announceForm.hass = this._hass;
    announceForm.schema = [{ name: "announce_hours", selector: { number: { min: 1, max: 336, mode: "box" } } }];
    announceForm.data = this._formData;
    announceForm.computeLabel = () => "";
    announceForm.computeHelper = () => "";
    announceForm.addEventListener("value-changed", (e) => {
      this._formData = { ...this._formData, ...e.detail.value };
      announceForm.data = this._formData;
      this._scheduleAutosave();
    });
    body.appendChild(announceForm);

    // A manually-drawn label, not ha-form's own computeLabel for this
    // field (see entitiesForm below, which suppresses it): direct user
    // feedback wanted the explanatory hint to sit under this label but
    // still above the picker itself, and ha-form always renders a field's
    // own label and its widget as a single, inseparable unit. There's no
    // way to slot anything in between the two while still going through
    // the schema.
    const excludedLabel = document.createElement("p");
    excludedLabel.className = "field-label";
    excludedLabel.textContent = tr.field_excluded_entities;
    body.appendChild(excludedLabel);

    const excludedHint = document.createElement("p");
    excludedHint.className = "hint";
    excludedHint.textContent = tr.field_excluded_entities_helper;
    body.appendChild(excludedHint);

    // Home Assistant Core/Supervisor/OS's own update entities are always
    // excluded from auto-install, regardless of this list (see
    // coordinator.py's hard_excluded_entity_ids). Shown here as if
    // already part of it, not as a separate "these are also always
    // excluded" note underneath that direct user feedback said nobody
    // actually read in practice. this._mergedExcludedEntities() adds them
    // to the *displayed* value only; the value-changed handler below
    // filters them back out before they ever reach this._formData or a
    // save, so removing one of these chips is a harmless no-op (still
    // excluded either way, just via the hard rule instead of this list)
    // rather than a real, persisted choice.
    const entitiesForm = document.createElement("ha-form");
    entitiesForm.hass = this._hass;
    entitiesForm.schema = [
      { name: "excluded_entities", selector: { entity: { multiple: true, filter: { domain: "update" } } } },
    ];
    entitiesForm.data = { ...this._formData, excluded_entities: this._mergedExcludedEntities() };
    // Label drawn manually above (excludedLabel), not here: see this
    // section's own comment.
    entitiesForm.computeLabel = () => "";
    entitiesForm.computeHelper = () => "";
    entitiesForm.addEventListener("value-changed", (e) => {
      // `|| []`, not a bare e.detail.value.excluded_entities -- .filter
      // below would throw immediately on the null ha-form's own
      // multiple:true selector emits once the last chip is removed (found
      // live, 2026-07-27). pickKnownSettings has its own LIST_SETTINGS_FIELDS
      // coercion too (for save_settings' own schema, which also rejects a
      // null list outright), but that runs later, at save time -- doesn't
      // help here, where the crash would already have happened.
      const chosen = (e.detail.value.excluded_entities || []).filter((id) => !this._hardExcludedEntities.includes(id));
      this._formData = { ...this._formData, excluded_entities: chosen };
      entitiesForm.data = { ...this._formData, excluded_entities: this._mergedExcludedEntities() };
      this._scheduleAutosave();
    });
    body.appendChild(entitiesForm);

    // Same manually-drawn label + hint pattern as excludedLabel/excludedHint
    // above -- direct user feedback: "installeer altijd automatisch als
    // [klaptafel] een update als healthy heeft beoordeeld, ongeacht mijn
    // eigen rules", then "kan je meerdere mensen vertrouwen?" (yes, a list,
    // see community_verdict.py's own aggregation: any trusted problematic
    // vote wins outright, else any trusted healthy vote does).
    const trustedLabel = document.createElement("p");
    trustedLabel.className = "field-label";
    trustedLabel.textContent = tr.field_trusted_voters;
    body.appendChild(trustedLabel);

    const trustedHint = document.createElement("p");
    trustedHint.className = "hint";
    trustedHint.textContent = tr.field_trusted_voters_helper;
    body.appendChild(trustedHint);

    // selector: { text: { multiple: true } } -- HA's own native way to
    // collect a free-text list as chips (verified against home-assistant/
    // frontend's real StringSelector type, stable tag 20260624.6, not
    // guessed), the same widget shape excluded_entities above uses for
    // entities. No validation against community-votes itself: purely a
    // local, unverified username string, see FUTURE.md's own note on this.
    const trustedForm = document.createElement("ha-form");
    trustedForm.hass = this._hass;
    trustedForm.schema = [{ name: "trusted_voters", selector: { text: { multiple: true } } }];
    trustedForm.data = this._formData;
    trustedForm.computeLabel = () => "";
    trustedForm.computeHelper = () => "";
    trustedForm.addEventListener("value-changed", (e) => {
      // `|| []`, not the bare selector value -- keeps this._formData itself
      // clean (a real array, matching every other field's own always-a-
      // value shape), on top of pickKnownSettings' own LIST_SETTINGS_FIELDS
      // coercion at save time.
      this._formData = { ...this._formData, trusted_voters: e.detail.value.trusted_voters || [] };
      trustedForm.data = this._formData;
      this._scheduleAutosave();
    });
    body.appendChild(trustedForm);

    card.appendChild(body);
    return card;
  }

  // The picker's displayed value: the user's own saved excluded_entities
  // plus the hard-excluded entities (deduplicated), so the latter show up
  // as ordinary chips instead of a separate explanatory note (see
  // _buildAutoInstallCard). Never what actually gets saved: that stays
  // this._formData.excluded_entities on its own, with the hard-excluded
  // ones filtered back out on every change.
  _mergedExcludedEntities() {
    return Array.from(new Set([...(this._formData.excluded_entities || []), ...this._hardExcludedEntities]));
  }

  _styles() {
    // Same typography tokens (--ha-font-*) this project family's other
    // cards already migrated to (see cover-media-card.js) -- so text here
    // matches HA's own scale/weight instead of arbitrary pixel values.
    return `
      :host {
        display: block; height: 100%;
        font-family: var(--ha-font-family-body, inherit);
        -webkit-font-smoothing: var(--ha-font-smoothing, antialiased);
      }
      hass-tabs-subpage { display: block; height: 100%; }

      /* Plain <a> tags this panel builds by hand (release-announcement/
         reason/verification links) used to fall back to the browser's own
         default link color (blue) instead of HA's own -- confirmed
         against more-info-update.ts's own real source (its static styles,
         not guessed): its own "a" rule is exactly this one line, color
         only, underline untouched. ha-markdown's own internal links are
         unaffected -- that's a separate custom element with its own
         shadow root, this rule only ever reaches plain <a> elements
         sitting directly in this panel's own shadow tree. */
      a { color: var(--primary-color); }

      .icon-btn {
        border: none; background: none; color: inherit; cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        width: 40px; height: 40px; border-radius: 50%;
      }
      .icon-btn:hover { background: rgba(0, 0, 0, 0.05); }
      .icon-btn:disabled { cursor: default; opacity: 0.6; }
      .icon-btn ha-icon.spinning { animation: um-spin 1s linear infinite; }
      @keyframes um-spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

      .content { display: block; }
      .loading {
        color: var(--secondary-text-color); padding: 32px 0; text-align: center;
        font-size: var(--ha-font-size-m, 14px);
      }
      /* Every tab shares one padded/centered container (.content--groups/
         --form/--list below all resolve to the same rule). Without this,
         a loading/error message shown there stacked its own vertical
         padding on top of the container's, landing at a different (larger)
         amount than the rest of the page. */
      .content--groups .loading, .content--groups .error,
      .content--form .loading, .content--form .error,
      .content--list .loading, .content--list .error { padding: 0; }
      .error { color: var(--error-color); padding: 16px 0; font-size: var(--ha-font-size-m, 14px); }
      ha-list-base { display: block; }
      /* Confirmed against ha-config-updates.ts's real static styles: without
         this, the "start" slot's own layout box doesn't actually match
         state-badge's real, hardcoded 40x40px size (see state-badge.ts),
         so the icon rendered inside it wasn't vertically centered. */
      ha-list-item-button { --md-list-item-leading-icon-size: 40px; }
      div[slot="start"] { position: relative; }
      .row-end { display: flex; align-items: center; gap: var(--ha-space-2, 8px); }
      .timer-pill {
        display: inline-flex; align-items: center; gap: var(--ha-space-1, 4px);
        padding: var(--ha-space-1, 4px) var(--ha-space-2, 8px);
        border-radius: var(--ha-border-radius-pill, 999px);
        background: var(--secondary-background-color); color: var(--secondary-text-color);
        font-size: var(--ha-font-size-xs, 11px); white-space: nowrap;
      }
      .timer-pill ha-svg-icon { --mdc-icon-size: 14px; }

      ha-form { display: block; }
      /* margin-bottom, not padding-bottom on .content--form: every content--*
         container deliberately has 0 bottom padding of its own (see below)
         and instead relies on its last child for the trailing gap before
         the page ends. .update-groups' own cards each already carry a
         bottom margin, and .history-section-items does the same for its
         last section, but .settings-cards had nothing of its own, so
         Settings was the one tab that ended flush with no space at all
         below its last card. */
      /* Card-to-card gap is --ha-space-6 (24px), not an arbitrary 16px --
         found live, 2026-07-27, direct user feedback: matches Updates' own
         per-card margin-bottom below (confirmed against
         ha-config-section-updates.ts's real static styles: margin-bottom:
         max(24px, var(--safe-area-inset-bottom))) and History's own
         between-section margin, so all three tabs read as one consistent
         rhythm regardless of which one a given card sits on. */
      .settings-cards { display: flex; flex-direction: column; gap: var(--ha-space-6, 24px); }
      /* Same 600px per-card width as .update-groups ha-card below. All
         three tabs' cards read as one consistent-width column regardless
         of which tab put them there (2026-07-21, direct user feedback).
         Explicit width: 100% (not left at the default auto) plus max-width
         and margin: 0 auto together, not align-self -- a flex item's auto
         margins otherwise disable stretch-to-fill and shrink it to content
         width instead (found live), so align-self alone wouldn't reliably
         center every card here the way width: 100% + margin: 0 auto does.
         Same centering mechanism .update-groups ha-card below already uses
         in its own plain block context, just adapted for this flex one. */
      .settings-cards ha-card { width: 100%; max-width: 600px; margin: 0 auto; }
      /* Same "Update Manager vX.Y.Z" link this project's own sibling
         Lovelace cards already put at the bottom of their editor --
         .settings-cards' own flex gap above already gives this the same
         24px breathing room from the last card as every other section, so
         unlike the compact editor version this doesn't need its own
         border-top divider on top of that. */
      .settings-cards .version-link {
        display: block; text-align: center; text-decoration: none;
        font-size: var(--ha-font-size-s, 13px); color: var(--secondary-text-color);
      }
      .settings-cards .version-link:hover { text-decoration: underline; }
      ha-card { margin: 0; }
      .card-content { padding: 0 16px 16px; display: flex; flex-direction: column; }
      .card-content > *:not(:first-child) { margin-top: 16px; }
      .card-actions { display: flex; justify-content: flex-end; padding: 8px 16px 16px; }
      .hint {
        color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 13px);
        line-height: 1.4; margin: 0;
      }
      /* A manually-drawn field label (see _buildAutoInstallCard), for a
         field whose own ha-form label had to be suppressed so a hint
         could sit between it and its control. Normal weight, not bold/
         medium: matches ha-settings-row's own heading slot (confirmed
         against its real source, even though this file doesn't use that
         component directly, since a custom-component detour for the rest
         of this page's fields wasn't wanted, direct user feedback), not a
         heavier typography scale of its own. The following .hint gets a much
         smaller top margin than .card-content's own generic 16px between
         unrelated blocks: this pair reads as one label+description
         unit, not two separate blocks. */
      .field-label { font-size: var(--ha-font-size-m, 14px); color: var(--primary-text-color); margin: 0; }
      .field-label + .hint { margin-top: var(--ha-space-1, 4px); }

      /* One shared page grid for all three tabs (2026-07-21, direct user
         feedback: Updates, History and Settings each had their own
         container width before). Values match ha-config-section-updates.ts's
         own static styles exactly (confirmed against its real source, not
         approximated pixels); Updates just happened to be the first tab
         built against that reference. */
      .content--groups, .content--form, .content--list {
        padding: var(--ha-space-7, 28px) var(--ha-space-5, 20px) 0;
        max-width: 1040px; margin: 0 auto;
      }
      /* .content--form's own bottom padding, not a trailing margin on
         .settings-cards. Updates/History both get their own trailing
         space from a margin on their actual last card/section (a plain
         block context there, see .update-groups/.history-section-items),
         but .settings-cards is itself a flex column with no border/padding
         of its own separating it from .content--form, so a margin-bottom
         on it was liable to collapse straight through and not reliably
         show up in the scrollable area (found live: it didn't). Padding
         never collapses, so this is the more robust fix for this one
         container specifically. */
      .content--form { padding-bottom: var(--ha-space-6, 24px); }
      /* One rule for every capped/centered 600px card/alert on this tab,
         not a separate copy per DOM depth -- found by review: the rollout-
         queue-card fix (below) originally added its own third literal copy
         of this exact declaration next to two that already existed. The
         rollout-queue cards (_buildRolloutGroupCard) and the empty-state
         card are appended directly to .update-groups-outer, not
         .update-groups -- found live, 2026-07-27, direct user feedback
         ("hij staat meer naar rechts"): a selector scoped to only
         .update-groups ha-card doesn't match those, so they fell through
         with no width cap or centering at all, rendering full-width
         instead of the same capped/centered 600px column every other card
         gets. A future sibling-level card type only needs adding to this
         one selector list, not a fourth copy of the declaration -- missed
         once anyway (found live, 2026-08-03, direct user feedback "card
         valt buiten het grid"): History's own empty state
         (buildEmptyStateCard(tr.history_empty), _buildHistoryList's own
         early return) is appended directly to .content--list, a sibling
         level this list didn't cover either, so it rendered at the full
         page width instead of matching every other card on that same tab
         (.history-section-items > ha-card, further below). */
      .update-groups-outer > ha-alert,
      .update-groups-outer > ha-card,
      .content--list > ha-card,
      .update-groups ha-card {
        display: block; max-width: 600px; margin: 0 auto var(--ha-space-6, 24px);
      }
      .update-groups { display: block; }
      .update-groups .card-content { padding: 0; display: block; }
      .update-groups .card-header {
        display: flex; align-items: center; justify-content: space-between;
        gap: var(--ha-space-2, 8px);
        padding: var(--ha-space-4, 16px) var(--ha-space-2, 8px) 0 var(--ha-space-4, 16px);
      }
      .update-groups .title { font-size: var(--ha-font-size-l, 18px); }
      .update-groups ha-list-base { margin-bottom: var(--ha-space-2, 8px); }
      /* Not scoped to .update-groups: the History tab's own empty state
         (see _buildHistoryList) reuses this same class/markup shape, not
         just the Updates tab's. */
      .no-updates { padding: 16px; }

      /* History tab: one outlined ha-card per entry (see _buildHistoryList),
         same 600px width as the Updates/Settings cards above, grouped under
         plain-text date headings (historySections). Card spacing (gap) and
         heading margins both use the same --ha-space-2/-6 tokens the rest
         of this file already leans on. */
      .history-section-items {
        display: flex; flex-direction: column; gap: var(--ha-space-2, 8px);
        margin-bottom: var(--ha-space-6, 24px);
      }
      /* Explicit width: 100% before margin: 0 auto, same reasoning as
         .settings-cards ha-card above: a flex item's auto margins alone
         would shrink it to content width instead of stretching to fill. */
      .history-section-items > ha-card { width: 100%; max-width: 600px; margin: 0 auto; }
      .history-section-items .card-content { padding: 0; display: block; }
      /* No top margin: the gap above a section (including the very first
         one) already comes from the page's own top padding, or from the
         previous section's .history-section-items margin-bottom. */
      .history-section-heading {
        font-size: var(--ha-font-size-l, 18px); font-weight: var(--ha-font-weight-medium, 500);
        max-width: 600px; margin: 0 auto var(--ha-space-2, 8px);
      }

      /* Detail dialog. ha-dialog was rewritten upstream to wrap a
         WebAwesome <wa-dialog> -- confirmed against a current stable
         release tag's real source, not the (already stale by comparison)
         dev-branch snapshot used earlier, which still described the old
         MDC-based implementation. None of that old implementation's custom
         properties (--mdc-dialog-*, --dialog-container-padding,
         --vertical-align-dialog, ...) exist on the current component at
         all, so setting them here was a silent no-op. The bottom-sheet/
         drawer behaviour below ~450px width or ~500px height is now baked
         into ha-dialog itself (its own @media rule keyed off the default
         type="standard" attribute) -- nothing to override for that at
         all. Content sizing already defaults sensibly (min(580px, 95vw)),
         so no width override either. The one thing that *did* need
         fixing: the footer must be real light-DOM content with
         slot="footer" (see the actions.slot assignment in
         _openDetailDialog) -- an unslotted sticky-positioned div was
         landing inside ha-dialog's own scrollable .body along with
         everything else instead of in its dedicated, already-styled
         footer area, which is what was breaking scrolling and cramming
         the action buttons oddly. ::slotted([slot="footer"]) inside
         ha-dialog's own styles already provides the flex/gap/padding for
         that area, so nothing extra is needed here for it either. */
      .dialog-content { display: flex; flex-direction: column; gap: var(--ha-space-4, 16px); }
      .dialog-content h3 {
        margin: 0; font-size: var(--ha-font-size-m, 14px);
        font-weight: var(--ha-font-weight-medium, 500); color: var(--primary-text-color);
      }
      .dialog-content hr { border-color: var(--divider-color); border-bottom: none; margin: 0; }
      /* :not([hidden]), not a bare .dialog-community-section selector --
         found live, 2026-07-22: a bare class selector has the exact same
         specificity as the UA's own [hidden] rule, and since this one comes
         later in the cascade it was winning, silently keeping the section's
         "not yet rated" placeholder text visible even for an entity that
         turned out not identifiable at all (section.hidden = true was never
         actually taking effect). :not([hidden]) only matches while the
         attribute is absent, so [hidden] governs cleanly on its own once
         it's set. */
      /* A wider gap than infoGroup's own (see below) between the divider,
         the info group, and the action controls -- three distinct blocks,
         not one uniform stack. Explicit margin-top on the section's own
         leading divider, on top of that gap, not instead of it -- direct
         user feedback, 2026-07-27: the release-link row right above this
         section read as flush against the divider, with not enough
         breathing room to read as a new section starting. */
      .dialog-community-section:not([hidden]) { display: flex; flex-direction: column; gap: var(--ha-space-3, 12px); }
      .dialog-community-section > hr:first-child { margin-top: var(--ha-space-2, 8px); }
      .dialog-community-section p { margin: 0; }
      /* Tight, not the section's own wider gap: the question and the
         verdict readout read as one connected pair of facts, found live,
         2026-07-22 -- see _buildCommunitySection's own comment. */
      .dialog-community-info { display: flex; flex-direction: column; gap: var(--ha-space-1, 4px); }
      /* Extra space above "Other jumps to this version" specifically, on
         top of infoGroup's own tight 4px -- direct user feedback,
         2026-07-27: the verdict line, the "other jumps" heading, and every
         other-jump row all ran together as one dense block with no visual
         cue that "other jumps" starts a new, separate list. */
      .dialog-community-info > .hint { margin-top: var(--ha-space-2, 8px); }
      /* :not([hidden]), same reasoning as .dialog-community-section above
         (found live there 2026-07-22, same bug independently found here via
         a screenshot 2026-07-29): a bare class selector ties the UA's own
         [hidden] rule in specificity and wins by coming later in the
         cascade, so verdictRow.hidden = true (_buildCommunitySection, for
         "you have no vote of your own, but others do -- the aggregate row
         below already covers it") silently failed to hide anything, leaving
         its stale "No one's reported on this jump yet." placeholder text
         (set at build time, before the real fetch resolves) visibly
         contradicting the aggregate/trusted-vote rows right below it. */
      .dialog-community-verdict-line:not([hidden]) { display: flex; align-items: center; gap: var(--ha-space-2, 8px); }
      .dialog-community-verdict-line ha-svg-icon { --mdc-icon-size: 18px; flex-shrink: 0; }
      /* buildReleaseNotesLoader's own placeholder -- centered, same small
         fixed footprint regardless of how long the notes it's standing in
         for turn out to be, so removing it never itself causes a jump. */
      .release-notes-loader { display: flex; justify-content: center; padding: var(--ha-space-4, 16px) 0; }
      /* Each reported problematic reason (category line + its own optional
         notes/link) as one visually grouped block -- direct user feedback,
         2026-07-29, from an actual screenshot: notes/link floating as
         plain unindented lines read as orphaned, disconnected from the
         category line above them, especially with more than one reason
         stacked back to back. Indented to align under the category text
         itself (18px icon + 8px gap), not under the icon. */
      .community-reason-item:not(:first-child) { margin-top: var(--ha-space-2, 8px); }
      .community-reason-item > .hint { margin-left: 26px; margin-top: var(--ha-space-1, 4px); }
      .dialog-vote { display: flex; flex-wrap: wrap; align-items: center; gap: var(--ha-space-2, 8px); }
      .dialog-vote > div { width: 100%; }
      /* :not(:first-child), not an unconditional margin-top -- found live,
         2026-07-22: Journey B's form has no intro paragraph before it (it's
         formContainer's own first child there), so this used to double up
         with .dialog-vote's own flex gap above it, one gap too many between
         the buttons and the form. Journey A's intro paragraph still gets
         this same spacing below it, since ha-form isn't the first child
         there. */
      .dialog-vote ha-form:not(:first-child) { margin-top: var(--ha-space-2, 8px); }
      .dialog-vote ha-form { display: block; }
      .dialog-community-confirmed { color: var(--primary-text-color); }
      /* Large and letter-spaced, meant to be read off a phone/laptop while
         typing it into GitHub's own device page, see _buildCommunityCard. */
      .community-link-code {
        font-family: var(--ha-font-family-code, monospace); font-size: var(--ha-font-size-2xl, 28px);
        letter-spacing: 0.15em; margin: var(--ha-space-2, 8px) 0;
      }
      /* state-info (icon+name) and .state, exactly the pair state-card-
         update.ts itself renders side by side for every update entity's
         more-info header -- verified against its real source, including
         the .state class's own declarations (color/margin/alignment). */
      .dialog-header {
        display: flex; align-items: center; justify-content: space-between;
      }
      state-info { flex: 0 1 fit-content; min-width: 120px; }
      .state {
        color: var(--primary-text-color); margin-inline-start: var(--ha-space-4, 16px);
        text-align: right; min-width: 50px; flex: 0 1 fit-content; word-break: break-word;
      }
      ha-alert { display: block; }
      .dialog-rows { display: flex; flex-direction: column; }
      /* No gap/padding/font-size overrides -- more-info-update.ts's own
         .row is exactly this and nothing else, confirmed against its real
         static styles, not approximated. */
      .row { margin: 0; display: flex; flex-direction: row; justify-content: space-between; }
      /* Timeline of ha-cards, same building block/spacing as the Settings
         tab's own .settings-cards (direct user feedback: the old plain
         <ul> "felt nothing like HA"). */
      .dialog-history { display: flex; flex-direction: column; gap: var(--ha-space-2, 8px); }
      .dialog-history ha-card { margin: 0; }
      /* padding: 0, not just no extra top override. The shared
         .card-content rule (used by every card in this file, Settings
         included) already sets 0 16px 16px on its own, which must be
         canceled here explicitly, not merely left un-added-to. Changed
         2026-07-22, direct user feedback: "enorme padding om de items".
         ha-list-item-button (every entry now, see _openDetailDialog)
         already carries its own generous, native padding, and 2026-07-23's
         unification means there's no longer a plain-fallback row without
         one to account for separately. */
      .dialog-history-card { padding: 0; font-size: var(--ha-font-size-s, 13px); }
      /* font-size reset, not inherited: .dialog-history-card shrinks its
         whole content area to 13px (a deliberately compact timeline row),
         which would otherwise also shrink ha-list-item-button's own
         headline/supporting-text below the normal size that same
         component uses elsewhere in this file (Updates list), looking and
         feeling noticeably weaker by comparison. Direct user feedback. */
      .dialog-history-card ha-list-item-button { font-size: var(--ha-font-size-m, 14px); }
      /* font-size reset, same reasoning as ha-list-item-button above: the
         community/vote section embedded per entry (2026-07-25) is an
         action, not passive changelog text, and should read the same size
         it does in the pending-update dialog, not shrunk to this card's
         own compact 13px scope. No margin-top here anymore -- see the
         .dialog-history-notes-wrap flex-gap rule further down, which now
         governs spacing between this, the facts block, the divider, the
         heading, and the notes uniformly (2026-08-01, direct user
         feedback: hand-placed margin-top on each of these one at a time,
         every time a gap was found missing somewhere, kept producing a new
         inconsistency each time -- "de witruimte rondom dividers en
         kopjes is nog steeds inconsistent. fix dat. grondig." -- a single
         gap on their shared, already-non-flex parent replaces all of that
         with one rule that can't drift out of sync with itself). */
      /* The chevron every history entry now has, expanding its own facts
         block (and changelog, if any) in place (see ICON_CHEVRON_DOWN/
         _openDetailDialog). Rotates on toggle the same way
         ha-expansion-panel's own built-in chevron would, since this row no
         longer uses that component (see this block's own comment above for
         why). */
      .dialog-history-chevron {
        transition: transform 150ms ease-in-out;
      }
      .dialog-history-chevron.open { transform: rotate(180deg); }
      /* Matches ha-list-item-button's own horizontal inset above it, so the
         expanded changelog's left/right edges line up with the row's own
         text instead of sitting flush against the card's true edges.
         display: flex + gap (2026-08-01, direct user feedback, grondige
         fix): every one of the facts block, the Community section, the
         release-notes divider, its heading, and its markdown content is a
         direct child of this element. It used to have no display/gap of
         its own at all, so each of those needed its own hand-placed
         margin-top to get any spacing from whatever came before it --
         found repeatedly missing, one element at a time, each fix
         producing a new inconsistency somewhere else (a 12px gap here, an
         8px gap there, zero gap somewhere no one had checked yet). One
         gap, on the actual shared parent, is the fix that can't drift back
         out of sync with itself the way five separate margin-top rules
         could. Same reasoning applied to font-size here too (found by
         review): .dialog-community-section, .row, and ha-markdown each had
         their own separate "font-size: var(--ha-font-size-m, 14px)" reset
         scattered across this stylesheet -- one on the shared parent,
         inherited by all three (nothing under it sets its own font-size),
         replaces all of them. :not([hidden]), not a bare selector -- same
         reasoning as .dialog-community-section's own guard earlier in this
         file: a bare class selector has the same specificity as the UA's
         own [hidden] rule, and since this one comes later in the
         stylesheet it would otherwise win and keep a collapsed entry's own
         hidden expand area visible. */
      .dialog-history-notes-wrap:not([hidden]) {
        display: flex; flex-direction: column; gap: var(--ha-space-3, 12px);
        padding: 0 var(--ha-space-4, 16px) var(--ha-space-4, 16px);
        font-size: var(--ha-font-size-m, 14px);
      }
      /* The individual fact rows (Available since/Announced/Installed/
         etc.) within that facts block need their own, smaller gap between
         each other -- scoped to History specifically, not a bare
         .dialog-rows rule: the pending-update dialog's own top-level facts
         block (same buildKeyValueRows, shared) deliberately has none at
         all (see .row's own comment above -- "more-info-update.ts's own
         .row is exactly this and nothing else"), and this must not change
         that. */
      .dialog-history-notes-wrap .dialog-rows { gap: var(--ha-space-2, 8px); }
      /* font-size now inherited from .dialog-history-notes-wrap's own rule
         above, not set here directly -- no padding-top either, that used
         to be this element's only source of spacing from whatever came
         before it, now redundant with (and inconsistent next to) the
         uniform flex-gap above. */
      .dialog-history ha-markdown { display: block; }
    `;
  }
}

if (!customElements.get("update-manager-panel")) {
  customElements.define("update-manager-panel", UpdateManagerPanel);
}
