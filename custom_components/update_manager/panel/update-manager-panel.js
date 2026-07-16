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
// Verified against the real @mdi/js package (mdiDownload/mdiClockOutline),
// same approach as the tab icons above -- used on the trailing timer
// badge/pill (see timerBadge), not the ICON_* tab set.
const ICON_DOWNLOAD = "M5,20H19V18H5M19,9H15V3H9V9H5L12,16L19,9Z";
const ICON_CLOCK_OUTLINE =
  "M12,20A8,8 0 0,0 20,12A8,8 0 0,0 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20M12,2A10,10 0 0,1 22,12A10,10 0 0,1 12,22C6.47,22 2,17.5 2,12A10,10 0 0,1 12,2M12.5,7V12.25L17,14.92L16.25,16.15L11,13V7H12.5Z";

// hass.language-driven, same convention this project family's other files
// use (see cover-media-card.js's TRANSLATIONS/_tr) -- flat keys, English as
// the base/fallback language. Found live: a user with hass.language "en"
// still saw an all-Dutch panel, since nothing here ever looked at
// hass.language at all before this.
const TRANSLATIONS = {
  en: {
    tab_updates: "Updates",
    tab_history: "History",
    tab_settings: "Settings",
    refresh: "Refresh",
    dash: "–",
    // Deliberately generic, not semver's own vocabulary (renamed
    // 2026-07-16, see FUTURE.md): "Small/Medium/Big" is a scale any version
    // scheme maps onto -- semver, calendar versioning, and git commit
    // hashes each have their own notion of "small" (see semver.py). The
    // _desc text is the settings screen's expandable-section *description*
    // (ha-form's own computeHelper for that schema entry, confirmed against
    // ha-form-expandable.ts -- renders as its own line below the header,
    // not squeezed into the header itself, direct user feedback) -- the
    // Updates tab's "Impact" column shows the _short word only, no room/
    // need for the explanation there.
    size_small_short: "Small",
    size_small_desc: "Patch, or a calendar date within the same month.",
    size_medium_short: "Medium",
    size_medium_desc: "Minor, a calendar month/year change, or a commit-hash update.",
    size_big_short: "Big",
    size_big_desc: "Major, or not recognizable.",
    // Used in the detail dialog's status alert (see statusText/
    // _openDetailDialog) -- no emoji prefix here, the alert's own color and
    // icon (a real ha-alert, success/info/warning) already carry that, an
    // emoji on top would be redundant. Green means the wait is over,
    // nothing is literally "done" yet on its own -- it may already be
    // auto-installing (status_pending_install below covers that case
    // specifically, with a matching download icon instead of the alert's
    // default one, see timerBadge). Orange is still waiting it out. Red is
    // reserved for a future signal (e.g. a community verdict, see
    // FUTURE.md's Fase 1/3) that actively discourages an update; nothing
    // in today's local rules produces it (see the settings legend's note).
    status_ready: "Ready to install",
    status_waiting: (n, unit) => `Postponed (${n} ${unit} left)`,
    status_waiting_soon: "Postponed (almost ready)",
    status_blocked: "Discouraged",
    status_pending_install: (when) => `Will be installed automatically ${when}`,
    always_manual_suffix: " (always manual)",
    field_excluded_entities: "Always manual (entities)",
    field_excluded_entities_helper:
      "Still shown normally in Updates and History -- Update Manager just never auto-installs these, regardless of what's configured above.",
    hard_excluded_note: (names) => `Always excluded too, regardless of the list above: ${names}.`,
    field_wait_days: "Postponement period (days)",
    field_auto_install: "Install automatically",
    field_auto_install_helper:
      "Update Manager installs it for you once it counts as ready, always after a cancellable announcement first, see the auto-install section below.",
    auto_install_section_title: "Auto-install",
    auto_install_section_desc: "Only applies to sizes where \"Install automatically\" is checked above.",
    announce_hours_label: "Announcement notice (hours)",
    announce_hours_helper:
      "How far in advance you'll see a scheduled automatic install coming (Updates tab) and can cancel it, before it actually happens. Counted back from the end of each size's own postponement period, not added on top of it -- unless the period itself is shorter than this notice, in which case you still get the full notice.",
    col_impact: "Impact",
    dialog_current_version: "Installed version",
    dialog_new_version: "Latest version",
    dialog_release_announcement: "Release announcement",
    dialog_history_heading: "History",
    dialog_more_info: "More info",
    settings_header: "Update rules",
    settings_hint:
      "Updates are split into 3 categories by impact (below). For each one, you decide how long to " +
      "wait before an update counts as ready, and whether Update Manager then installs it for you " +
      "or you do it yourself.",
    save: "Save",
    cancel_auto_install: "Cancel auto-update",
    dialog_install: "Install",
    dialog_skip: "Skip",
    group_ready: "Ready to install",
    group_waiting: "Postponed",
    group_blocked: "Discouraged",
    group_not_installable: "Not installable",
    updates_empty: "No updates need attention, everything is up to date.",
    history_empty: "No installs logged yet.",
    loading: "Loading…",
    load_error_prefix: "Couldn't load Update Manager: ",
    units: [
      ["year", "years"],
      ["month", "months"],
      ["week", "weeks"],
      ["day", "days"],
      ["hour", "hours"],
      ["minute", "minutes"],
    ],
    relative_ago: (n, unit) => `${n} ${unit} ago`,
    relative_future: (n, unit) => `in ${n} ${unit}`,
    relative_just_now: "just now",
    relative_soon: "very soon",
  },
  nl: {
    tab_updates: "Updates",
    tab_history: "Historie",
    tab_settings: "Instellingen",
    refresh: "Vernieuwen",
    dash: "–",
    size_small_short: "Klein",
    size_small_desc: "Patch, of kalenderdatum binnen dezelfde maand.",
    size_medium_short: "Gemiddeld",
    size_medium_desc: "Minor, kalendermaand/-jaar, of commit-update.",
    size_big_short: "Groot",
    size_big_desc: "Major, of niet te herkennen.",
    status_ready: "Klaar voor installatie",
    status_waiting: (n, unit) => `Uitgesteld (nog ${n} ${unit})`,
    status_waiting_soon: "Uitgesteld (bijna zo ver)",
    status_blocked: "Afgeraden",
    status_pending_install: (when) => `Wordt automatisch geïnstalleerd ${when}`,
    always_manual_suffix: " (altijd handmatig)",
    field_excluded_entities: "Altijd handmatig (entiteiten)",
    field_excluded_entities_helper:
      "Blijven gewoon zichtbaar bij Updates en Historie -- Update Manager installeert ze alleen nooit automatisch, ongeacht wat je hierboven instelt.",
    hard_excluded_note: (names) => `Staan sowieso altijd óók uitgesloten, ongeacht bovenstaande lijst: ${names}.`,
    field_wait_days: "Uitsteltermijn (dagen)",
    field_auto_install: "Automatisch installeren",
    field_auto_install_helper:
      "Update Manager installeert 'm dan zelf zodra die als gereed geldt, altijd pas na een aankondiging die je eerst nog kan annuleren, zie de sectie automatisch installeren hieronder.",
    auto_install_section_title: "Automatisch installeren",
    auto_install_section_desc: "Geldt alleen voor groottes waar hierboven \"Automatisch installeren\" aan staat.",
    announce_hours_label: "Aankondigingstermijn (uren)",
    announce_hours_helper:
      "Hoe lang van tevoren je een geplande automatische installatie ziet aankomen (Updates-tab) en kan annuleren, voordat 'ie echt gebeurt. Wordt afgeteld vanaf het einde van de uitsteltermijn per grootte, niet erbovenop opgeteld -- tenzij die termijn zelf korter is dan deze aankondiging, dan krijg je hem alsnog in volle lengte.",
    col_impact: "Impact",
    dialog_current_version: "Geïnstalleerde versie",
    dialog_new_version: "Nieuwste versie",
    dialog_release_announcement: "Release-aankondiging",
    dialog_history_heading: "Geschiedenis",
    dialog_more_info: "Meer info",
    settings_header: "Update-regels",
    settings_hint:
      "We verdelen updates in 3 categorieën op basis van impact (hieronder). Per categorie stel je in " +
      "hoelang je wilt wachten voordat een update als gereed geldt, en of Update Manager de update " +
      "dan zelf installeert of dat jij dat zelf doet.",
    save: "Opslaan",
    cancel_auto_install: "Automatische update annuleren",
    dialog_install: "Installeren",
    dialog_skip: "Overslaan",
    group_ready: "Klaar voor installatie",
    group_waiting: "Uitgesteld",
    group_blocked: "Afgeraden",
    group_not_installable: "Niet installeerbaar",
    updates_empty: "Geen updates die aandacht nodig hebben, alles is up-to-date.",
    history_empty: "Nog geen installaties gelogd.",
    loading: "Laden…",
    load_error_prefix: "Kon Update Manager niet laden: ",
    units: [
      ["jaar", "jaar"],
      ["maand", "maanden"],
      ["week", "weken"],
      ["dag", "dagen"],
      ["uur", "uur"],
      ["minuut", "minuten"],
    ],
    relative_ago: (n, unit) => `${n} ${unit} geleden`,
    relative_future: (n, unit) => `over ${n} ${unit}`,
    relative_just_now: "zojuist",
    relative_soon: "zo dadelijk",
  },
};
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
const SIZES = ["small", "medium", "big"];

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
  const names = ["announce_hours", "excluded_entities"];
  for (const size of SIZES) {
    names.push(`${size}_wait_days`, `${size}_auto_install`);
  }
  return names;
}

function pickKnownSettings(data) {
  const known = knownSettingsFields();
  const result = {};
  for (const key of known) {
    if (key in data) result[key] = data[key];
  }
  return result;
}

// Status sorts green-orange-red (safest first), requested directly by the
// user. Within "ready"/"blocked", oldest-available first (the longest-
// standing, most "proven" update sinks to the top of its group); within
// "waiting", soonest-to-turn-green first instead (least remaining_seconds)
// -- oldest-available doesn't mean the same thing there (found live: a
// "big" update available 59 days into a 60-day wait sorted above a
// "medium" update 12 hours from ready, since it had simply existed longer,
// not because it was closer to actionable).
const STATUS_SORT_PRIORITY = { ready: 0, waiting: 1, blocked: 2 };

// ha-alert's alertType per status, shown in the detail dialog -- kept next
// to STATUS_SORT_PRIORITY since both need the same fallback for a status
// value this panel doesn't recognize (see _FALLBACK_STATUS below).
const STATUS_ALERT_TYPE = { ready: "success", waiting: "info", blocked: "warning" };

// One shared fallback for an unrecognized/future status value, used by
// every lookup keyed on u.status below (sort priority, grouping, alert
// color) -- previously each had its own independent hardcoded fallback
// (two silently agreed on "blocked", the alert color didn't, defaulting to
// "info" instead), so a new status value added without touching all of
// them would sort/group as blocked but render with the wrong alert color.
const _FALLBACK_STATUS = "blocked";

function updateSortKey(u) {
  const priority = STATUS_SORT_PRIORITY[u.status] ?? STATUS_SORT_PRIORITY[_FALLBACK_STATUS];
  const availableSinceSec = u.available_since ? Math.floor(new Date(u.available_since).getTime() / 1000) : 0;
  const secondary = u.status === "waiting" && u.remaining_seconds != null ? u.remaining_seconds : availableSinceSec;
  return priority * 10_000_000_000 + secondary;
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
function statusText(tr, u) {
  let text;
  // pending_install checked first, regardless of ready/waiting -- direct
  // user feedback: count down to the real action (install, or counting as
  // ready) rather than the moment the announcement itself went out. A
  // "waiting" update can already have an announcement pending near the end
  // of its own postponement period (see announcer.py's decide_action), and
  // that real install moment can land later than the plain "time left"
  // figure would suggest.
  if (u.pending_install) {
    text = tr.status_pending_install(relativeTime(tr, u.pending_install.execute_at));
  } else if (u.status === "waiting") {
    const parts = breakdownDuration(tr, u.remaining_seconds);
    text = parts ? tr.status_waiting(parts.value, parts.unit) : tr.status_waiting_soon;
  } else {
    text = tr[`status_${u.status}`] || u.status;
  }
  if (u.auto_install_excluded) text += tr.always_manual_suffix;
  return text;
}

// The Updates list row's trailing badge/pill (see _buildListRow): a
// download icon + real install time for anything with an actual pending
// auto-install, a clock icon + time-until-green for a plain "waiting"
// update with no auto-install scheduled yet. Same "count to the real
// action moment" priority as statusText above, not to the announcement.
function timerBadge(tr, u) {
  if (u.pending_install) {
    return { icon: ICON_DOWNLOAD, text: relativeTime(tr, u.pending_install.execute_at) };
  }
  if (u.status === "waiting") {
    const parts = breakdownDuration(tr, u.remaining_seconds);
    const text = parts ? tr.relative_future(parts.value, parts.unit) : tr.relative_soon;
    return { icon: ICON_CLOCK_OUTLINE, text };
  }
  return null;
}

// Grouped by status, not by domain/category (changed 2026-07-16, direct
// user feedback: status is what you actually act on, not which
// integration something came from) -- Ready first, then Postponed, then
// Discouraged, same order as the status sort itself. Not-installable
// updates (no UpdateEntityFeature.INSTALL, e.g.
// firmware that must be flashed by hand) are pulled out into their own
// group first and shown last, same as HA's own updates page does for that
// same category (ha-config-section-updates.ts) -- status doesn't mean
// anything actionable for those anyway.
function groupUpdates(tr, updates) {
  const notInstallable = updates.filter((u) => !u.installable);
  const installable = updates.filter((u) => u.installable);

  const byStatus = { ready: [], waiting: [], blocked: [] };
  installable.forEach((u) => {
    (byStatus[u.status] || byStatus[_FALLBACK_STATUS]).push(u);
  });

  const groups = [];
  if (byStatus.ready.length) groups.push({ key: "ready", title: tr.group_ready, entities: byStatus.ready });
  if (byStatus.waiting.length) groups.push({ key: "waiting", title: tr.group_waiting, entities: byStatus.waiting });
  if (byStatus.blocked.length) groups.push({ key: "blocked", title: tr.group_blocked, entities: byStatus.blocked });
  if (notInstallable.length) {
    groups.push({ key: "not_installable", title: tr.group_not_installable, entities: notInstallable });
  }
  return groups;
}

// Shared by relativeTime/breakdownDuration below: picks the largest unit
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

// Same units as relativeTime, but broken into {value, unit} instead of a
// full sentence -- timerBadge composes its own short pill text around this
// ("nog 2 dagen"), direct user feedback: showing only "wacht nog" with no
// indication of how much longer left it, without opening each entity's
// own more-info dialog.
function breakdownDuration(tr, seconds) {
  if (seconds == null) return null;
  return _breakdown(tr, Math.max(0, Math.round(seconds)));
}

function entityState(hass, entityId) {
  return hass && hass.states && hass.states[entityId];
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

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

// Shared by every ha-progress-button click handler below (cancel/skip/
// install/save) -- each one flips the button into its progress state,
// awaits its own action, then reports success/error via the button's own
// real API instead of hand-rolling the same try/catch four times.
async function _runProgressAction(btn, fn) {
  btn.progress = true;
  try {
    await fn();
    btn.actionSuccess();
  } catch (err) {
    btn.actionError();
    btn.progress = false;
  }
}

class UpdateManagerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = "updates";
    this._route = null;
    this._updates = null;
    this._installLog = null;
    this._settings = null;
    this._profiles = null;
    this._hardExcludedEntities = [];
    this._dialogEntityId = null;
    this._formData = null;
    this._loadError = null;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._initialLoad();
    } else {
      this._updateShell();
    }
  }

  get hass() {
    return this._hass;
  }

  get _tr() {
    return TRANSLATIONS[this._hass && this._hass.language] || TRANSLATIONS.en;
  }

  set narrow(narrow) {
    this._narrow = narrow;
    this._updateShell();
  }

  // Set by HA's panel resolver on every navigation under this panel's own
  // URL (e.g. /update-manager/history) -- the same mechanism every other
  // HA settings page uses, see hass-router-page.ts/compute-route.ts.
  set route(route) {
    this._route = route;
    const path = (route && route.path) || "";
    if ((path === "" || path === "/") && route && route.prefix) {
      // Land on the Updates tab by default, same as e.g. /config redirecting
      // to its first sub-page -- don't leave the bare panel URL tab-less.
      history.replaceState(null, "", `${route.prefix}/updates`);
      this._tab = "updates";
    } else {
      this._tab = tabForPath(path);
    }
    this._updateShell();
    this._renderContent();
  }

  set panel(_panel) {}

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
      this._installLog = logResp.entries.slice().reverse();
      this._settings = settingsResp.options;
      this._profiles = settingsResp.profiles;
      this._hardExcludedEntities = settingsResp.hard_excluded_entities || [];
      if (!this._formData) {
        // "balanced" as the silent fallback for anything not actually
        // stored yet, not an empty object -- otherwise a field missing from
        // this._settings (a fresh install, or one of this session's field
        // renames leaving old keys behind) ends up completely absent from
        // _formData, and pickKnownSettings then leaves it out of the save
        // payload entirely: save_settings's vol.Required(...) schema
        // rejected that outright ("required key not provided"), found live.
        // excluded_entities isn't part of any profile preset (it's a plain
        // entity list, not a wait/auto-install tuning value), so it needs
        // its own explicit empty-array default the same way.
        const fallback = (this._profiles && this._profiles.balanced) || {};
        this._formData = { excluded_entities: [], ...fallback, ...pickKnownSettings(this._settings) };
      }
      this._loadError = null;
    } catch (err) {
      this._loadError = (err && err.message) || String(err);
    }
  }

  async _refresh() {
    await this._loadAll();
    this._renderContent();
  }

  // Builds the page chrome once: hass-tabs-subpage, the same layout
  // component /config/devices etc. use (menu button, title, tab bar wired
  // to real HA routing) -- built once and only had its properties updated
  // afterwards, not recreated every render, so it (and any child state like
  // scroll position) survives tab switches and data refreshes.
  _ensureShell() {
    if (this._shellBuilt) return;
    this._shellBuilt = true;

    this.shadowRoot.innerHTML = `<style>${this._styles()}</style>`;

    const subpage = document.createElement("hass-tabs-subpage");
    subpage.tabs = TAB_DEFS.map((t) => ({ path: t.path, name: this._tr[t.nameKey], iconPath: t.iconPath }));

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
    });
    this.shadowRoot.appendChild(dialog);
    this._dialogEl = dialog;
  }

  _updateShell() {
    if (!this._subpageEl) return;
    this._subpageEl.hass = this._hass;
    this._subpageEl.narrow = this._narrow;
    // Only ever forward a real route, never a {prefix:"",path:""} filler --
    // found live: HA's panel resolver sets `hass` before `route`, so
    // _initialLoad's first _updateShell() call used to run before the real
    // route was known yet, handing hass-tabs-subpage an empty route right
    // at first paint. It only recomputed which tab looks active once you
    // clicked one yourself; the real route arriving a moment later (via the
    // `route` setter below) didn't retrigger that highlight on its own.
    if (this._route) this._subpageEl.route = this._route;
  }

  _renderContent() {
    if (!this._contentEl) return;
    const hasData = this._updates !== null;
    this._contentEl.innerHTML = "";
    // History stays a bare, edge-to-edge list (same as /config/devices);
    // Updates is grouped into cards now (see _buildUpdatesList), so it
    // gets the centered/padded treatment settings already used, just
    // wider (more than one card can sit side by side in the same reading
    // width HA's own updates page uses).
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

  // ha-list-base + ha-list-item-button + state-badge -- the same list
  // pattern HA's own /config updates section uses (verified against
  // ha-config-updates.ts's real source, not guessed, direct user feedback
  // that the previous ha-data-table felt inflexible: no real entity icons,
  // and a poor mobile experience since it's fundamentally a multi-column
  // table trying to fit a narrow screen). A plain scrollable list has
  // neither problem: state-badge gives every row its real icon, and there
  // are no columns to hide on a phone in the first place.
  _wrapList(rowElements, emptyText) {
    if (!rowElements.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = emptyText;
      return empty;
    }
    const list = document.createElement("ha-list-base");
    rowElements.forEach((row) => list.appendChild(row));
    return list;
  }

  // The icon+time pill (see timerBadge) -- shared between the Updates list
  // rows and the detail dialog's status alert, so "when does this actually
  // happen" reads identically in both places.
  _buildTimerPill(timerBadgeInfo) {
    const pill = document.createElement("div");
    pill.className = "timer-pill";
    const pillIcon = document.createElement("ha-svg-icon");
    pillIcon.path = timerBadgeInfo.icon;
    pill.appendChild(pillIcon);
    const pillText = document.createElement("span");
    pillText.textContent = timerBadgeInfo.text;
    pill.appendChild(pillText);
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
  _buildListRow(entityId, supportingText, onClick, timerBadgeInfo) {
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
    if (timerBadgeInfo) end.appendChild(this._buildTimerPill(timerBadgeInfo));
    end.appendChild(document.createElement("ha-icon-next"));
    row.appendChild(end);

    row.addEventListener("click", onClick);
    return row;
  }

  // Default sort: safest first (green, then orange, then red), see
  // updateSortKey's own comment for the secondary key -- requested
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
    if (!this._updates.length) {
      const card = document.createElement("ha-card");
      card.outlined = true;
      const empty = document.createElement("div");
      empty.className = "no-updates";
      empty.textContent = tr.updates_empty;
      card.appendChild(empty);
      return card;
    }

    const groups = groupUpdates(tr, this._updates);

    const wrap = document.createElement("div");
    wrap.className = "update-groups";

    groups.forEach((group) => {
      const card = document.createElement("ha-card");
      card.outlined = true;

      const content = document.createElement("div");
      content.className = "card-content";

      const header = document.createElement("div");
      header.className = "card-header";
      const title = document.createElement("div");
      title.className = "title";
      title.setAttribute("role", "heading");
      title.textContent = group.title;
      header.appendChild(title);
      content.appendChild(header);

      const list = document.createElement("ha-list-base");
      group.entities
        .slice()
        .sort((a, b) => updateSortKey(a) - updateSortKey(b))
        .forEach((u) => {
          // Just the version to install, matching HA's own updates list
          // row (ha-config-updates.ts) -- direct user feedback: this used
          // to be a whole sentence (size, both versions, and the full
          // status text), the status/countdown now live in the group
          // heading and the trailing timer badge instead (see timerBadge).
          list.appendChild(
            this._buildListRow(
              u.entity_id,
              u.latest_version,
              () => this._openDetailDialog(u.entity_id),
              timerBadge(tr, u)
            )
          );
        });
      content.appendChild(list);
      card.appendChild(content);
      wrap.appendChild(card);
    });

    return wrap;
  }

  _buildHistoryList() {
    const tr = this._tr;
    const rows = this._installLog.map((entry) => {
      const supporting = `${entry.from_version} → ${entry.to_version} ⋅ ${relativeTime(tr, entry.installed_at)}`;
      return this._buildListRow(entry.entity_id, supporting, () => this._openDetailDialog(entry.entity_id));
    });
    return this._wrapList(rows, tr.history_empty);
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
  _openDetailDialog(entityId) {
    const tr = this._tr;
    const dialog = this._dialogEl;
    // Tracks which entity the dialog is currently showing -- lets an
    // in-flight release-notes fetch (see below) recognize itself as stale
    // if the dialog closes or gets reopened for a different entity before
    // it resolves.
    this._dialogEntityId = entityId;
    dialog.innerHTML = "";
    dialog.headerTitle = friendlyEntityName(this._hass, entityId);

    const body = document.createElement("div");
    body.className = "dialog-content";

    const state = entityState(this._hass, entityId);
    const u = this._updates.find((x) => x.entity_id === entityId);
    const sizeShort = u ? tr[`size_${u.version_size}_short`] || u.version_size : null;

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
      header.appendChild(stateInfo);

      if (u) {
        // Just the version to install, matching the Updates list rows
        // (direct user feedback) -- not the size/installed/latest sentence
        // this used to show.
        const summary = document.createElement("span");
        summary.textContent = u.latest_version;
        stateInfo.appendChild(summary);

        const stateValue = document.createElement("div");
        stateValue.className = "state";
        stateValue.textContent = tr[`status_${u.status}`] || u.status;
        header.appendChild(stateValue);
      }
      body.appendChild(header);
    }

    if (u) {
      // The entity's own "title" attribute (e.g. "Frontend"), not
      // necessarily the same string as its friendly name in state-info
      // above -- more-info-update.ts shows both, so we do too.
      const attrTitle = state && state.attributes && state.attributes.title;
      if (attrTitle) {
        const titleEl = document.createElement("h3");
        titleEl.textContent = attrTitle;
        body.appendChild(titleEl);
      }

      const statusAlertType = STATUS_ALERT_TYPE[u.status] || STATUS_ALERT_TYPE[_FALLBACK_STATUS];
      const statusAlert = document.createElement("ha-alert");
      statusAlert.alertType = statusAlertType;
      // ha-alert's own default icon (checkmark/info/warning, based on
      // alertType) is replaced by the same icon the Updates list's pill
      // uses (see timerBadge) whenever there's a real countdown to show --
      // ha-alert supports this via its own slot="icon" (confirmed against
      // its real source), the text itself already explains what's
      // happening (statusText), the icon just ties it visually to the
      // same download/clock icon used elsewhere for "when".
      const dialogBadge = timerBadge(tr, u);
      if (dialogBadge) {
        const customIcon = document.createElement("ha-svg-icon");
        customIcon.slot = "icon";
        customIcon.path = dialogBadge.icon;
        statusAlert.appendChild(customIcon);
      }
      statusAlert.appendChild(document.createTextNode(statusText(tr, u)));
      if (u.pending_install) {
        const cancelBtn = document.createElement("ha-progress-button");
        cancelBtn.slot = "action";
        cancelBtn.label = tr.cancel_auto_install;
        cancelBtn.addEventListener("click", () =>
          _runProgressAction(cancelBtn, async () => {
            await this._hass.callWS({ type: "update_manager/cancel_pending_install", entity_id: entityId });
            await this._loadAll();
            dialog.open = false;
            this._renderContent();
          })
        );
        statusAlert.appendChild(cancelBtn);
      }
      body.appendChild(statusAlert);

      const rows = document.createElement("div");
      rows.className = "dialog-rows";
      [
        [tr.dialog_current_version, u.installed_version],
        [tr.dialog_new_version, u.latest_version],
        [tr.col_impact, sizeShort],
      ].forEach(([key, value]) => {
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
      body.appendChild(rows);

      // A link-only row, exactly like more-info-update.ts's own
      // release_url row (a .row with just a .key containing an <a>, no
      // .value) -- not something we compute ourselves, straight from the
      // entity's own attribute.
      const releaseUrl = state && state.attributes && state.attributes.release_url;
      if (releaseUrl) {
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
        body.appendChild(row);
      }

      // Release notes. UpdateEntityFeature.RELEASE_NOTES = 16
      // (homeassistant/components/update/const.py): entities that support
      // it generate notes on demand (e.g. fetched from a changelog API),
      // fetched the same real way HA's own more-info dialog does --
      // update/release_notes, a core websocket command (verified against
      // frontend's data/update.ts's updateReleaseNotes, not guessed), not
      // something we compute ourselves. Entities without that feature just
      // expose a plain release_summary attribute instead -- more-info-
      // update.ts falls back to exactly that same attribute when the
      // feature isn't supported, so we do too.
      const supportsReleaseNotes = state && (state.attributes.supported_features || 0) & 16;
      if (supportsReleaseNotes) {
        body.appendChild(document.createElement("hr"));
        const notesContainer = document.createElement("div");
        body.appendChild(notesContainer);
        this._hass
          .callWS({ type: "update/release_notes", entity_id: entityId })
          .then((notes) => {
            // Stale by the time it resolves (dialog closed, or reopened
            // for a different entity) -- drop it rather than inserting
            // into a container nobody's looking at anymore.
            if (this._dialogEntityId !== entityId || !notes) return;
            const markdown = document.createElement("ha-markdown");
            markdown.content = notes;
            notesContainer.appendChild(markdown);
          })
          .catch(() => {});
      } else {
        const releaseSummary = state && state.attributes && state.attributes.release_summary;
        if (releaseSummary) {
          body.appendChild(document.createElement("hr"));
          const markdown = document.createElement("ha-markdown");
          markdown.content = releaseSummary;
          body.appendChild(markdown);
        }
      }

      body.appendChild(document.createElement("hr"));
    }

    // Skipped entirely when there's no history at all, not shown with an
    // empty-state message -- direct user feedback: a heading for a section
    // with nothing under it just added noise, especially for a purely
    // historical entity that's otherwise short on content anyway.
    const entries = this._installLog.filter((entry) => entry.entity_id === entityId);
    if (entries.length) {
      const historyHeading = document.createElement("h3");
      historyHeading.textContent = tr.dialog_history_heading;
      body.appendChild(historyHeading);

      const list = document.createElement("ul");
      list.className = "dialog-history";
      entries.forEach((entry) => {
        const li = document.createElement("li");
        const main = document.createElement("div");
        main.className = "dialog-history-main";
        main.textContent = `${entry.from_version} → ${entry.to_version} ⋅ ${relativeTime(tr, entry.installed_at)}`;
        li.appendChild(main);
        let notes = null;
        if (entry.release_summary) notes = entry.release_summary;
        else if (entry.release_notes) notes = entry.release_notes.slice(0, 200);
        else if (entry.release_url) notes = entry.release_url;
        if (notes) {
          const notesEl = document.createElement("div");
          notesEl.className = "dialog-history-notes";
          notesEl.textContent = notes;
          li.appendChild(notesEl);
        }
        list.appendChild(li);
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
    // update.install/update.skip services HA's own dialog calls (verified
    // against update/services.yaml, not guessed) -- More info and Skip are
    // plain/text-style (secondary), Install is filled (primary, the one
    // action that actually changes something right now).
    const actions = document.createElement("div");
    actions.slot = "footer";

    const moreInfoBtn = document.createElement("ha-progress-button");
    moreInfoBtn.appearance = "plain";
    moreInfoBtn.label = tr.dialog_more_info;
    moreInfoBtn.addEventListener("click", () => {
      dialog.open = false;
      this._openMoreInfo(entityId);
    });
    actions.appendChild(moreInfoBtn);

    if (u) {
      const skipBtn = document.createElement("ha-progress-button");
      skipBtn.appearance = "plain";
      skipBtn.label = tr.dialog_skip;
      skipBtn.addEventListener("click", () =>
        _runProgressAction(skipBtn, async () => {
          await this._hass.callService("update", "skip", { entity_id: entityId });
          await this._loadAll();
          dialog.open = false;
          this._renderContent();
        })
      );
      actions.appendChild(skipBtn);

      if (u.installable) {
        const installBtn = document.createElement("ha-progress-button");
        installBtn.appearance = "filled";
        installBtn.label = tr.dialog_install;
        installBtn.addEventListener("click", () =>
          _runProgressAction(installBtn, async () => {
            // UpdateEntityFeature.BACKUP = 8 (homeassistant/components/
            // update/const.py) -- same condition install_manager.py's own
            // auto-install already uses, kept consistent here.
            const serviceData = { entity_id: entityId };
            if (state && (state.attributes.supported_features || 0) & 8) {
              serviceData.backup = true;
            }
            await this._hass.callService("update", "install", serviceData);
            await this._loadAll();
            dialog.open = false;
            this._renderContent();
          })
        );
        actions.appendChild(installBtn);
      }
    }

    dialog.appendChild(actions);

    dialog.open = true;
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

    const autoInstallSlot = document.createElement("div");
    // Rebuilds the sibling card only when anyAutoInstall actually flips, not
    // on every value-changed event -- the "Update rules" form also fires
    // this for unrelated edits (e.g. a wait-days number), which doesn't
    // change whether this card should exist at all.
    let lastAnyAutoInstall = null;
    const syncAutoInstallCard = () => {
      const anyAutoInstall = SIZES.some((size) => this._formData[`${size}_auto_install`]);
      if (anyAutoInstall === lastAnyAutoInstall) return;
      lastAnyAutoInstall = anyAutoInstall;
      autoInstallSlot.innerHTML = "";
      if (anyAutoInstall) autoInstallSlot.appendChild(this._buildAutoInstallCard(tr));
    };

    wrap.appendChild(this._buildUpdateRulesCard(tr, syncAutoInstallCard));
    wrap.appendChild(autoInstallSlot);
    syncAutoInstallCard();

    const actions = document.createElement("div");
    actions.className = "card-actions";
    const saveBtn = document.createElement("ha-progress-button");
    saveBtn.appearance = "filled";
    saveBtn.label = tr.save;
    saveBtn.addEventListener("click", () =>
      _runProgressAction(saveBtn, async () => {
        const settingsOnly = pickKnownSettings(this._formData);
        await this._hass.callWS({ type: "update_manager/save_settings", ...settingsOnly });
        this._settings = { ...settingsOnly };
        // Re-fetch Updates/History too, not just settings -- new rules can
        // change an entity's ready/waiting/blocked verdict immediately
        // (see coordinator.py's async_update_rules), and without this the
        // other two tabs kept showing whatever was loaded before the save
        // until you hit the manual refresh button yourself.
        await this._loadAll();
      })
    );
    actions.appendChild(saveBtn);
    wrap.appendChild(actions);

    return wrap;
  }

  // "Update rules": plain and functional -- the earlier "Stoplicht"/
  // traffic-light framing (and its emoji-dot legend) was dropped entirely
  // (direct user feedback: the emoji looked bad throughout, and the
  // metaphor wasn't pulling its weight). Once the community layer exists
  // (Fase 1/3, see FUTURE.md) that becomes its own, separately-named card
  // next to this one -- revisit both cards' naming together then, not now.
  // `onAutoInstallChange` fires
  // after every edit so the sibling auto-install card (a separate ha-card,
  // not a schema entry of this form) can appear/disappear live as
  // ${size}_auto_install toggles, without rebuilding this card itself.
  _buildUpdateRulesCard(tr, onAutoInstallChange) {
    const card = document.createElement("ha-card");
    card.outlined = true;
    card.header = tr.settings_header;

    const body = document.createElement("div");
    body.className = "card-content";

    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = tr.settings_hint;
    body.appendChild(hint);

    const form = document.createElement("ha-form");
    form.hass = this._hass;
    form.schema = SIZES.map((size) => ({
      name: size,
      type: "expandable",
      title: tr[`size_${size}_short`],
      expanded: true,
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
      // just "small"/"medium"/"big") -- confirmed against
      // ha-form-expandable.ts: renders as its own line below the header,
      // not squeezed into the title itself, direct user feedback.
      if (SIZES.includes(s.name)) return tr[`size_${s.name}_desc`];
      const kind = fieldKind(s.name);
      return kind === "auto_install" ? tr.field_auto_install_helper : "";
    };
    form.addEventListener("value-changed", (e) => {
      this._formData = { ...this._formData, ...e.detail.value };
      form.data = this._formData;
      onAutoInstallChange();
    });
    body.appendChild(form);
    card.appendChild(body);
    return card;
  }

  // Its own card, only once some size actually has auto-install on --
  // neither field has any effect otherwise (nothing to announce, and
  // nothing to exclude from auto-installing when nothing auto-installs at
  // all). Announcement above the entities list, not below (direct user
  // feedback: that list can grow long and would push the announcement
  // setting further down the page).
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

    const form = document.createElement("ha-form");
    form.hass = this._hass;
    form.schema = [
      { name: "announce_hours", selector: { number: { min: 1, max: 336, mode: "box" } } },
      { name: "excluded_entities", selector: { entity: { multiple: true, filter: { domain: "update" } } } },
    ];
    form.data = this._formData;
    form.computeLabel = (s) => {
      if (s.name === "excluded_entities") return tr.field_excluded_entities;
      return s.name === "announce_hours" ? tr.announce_hours_label : s.name;
    };
    form.computeHelper = (s) => {
      if (s.name === "excluded_entities") return tr.field_excluded_entities_helper;
      return s.name === "announce_hours" ? tr.announce_hours_helper : "";
    };
    form.addEventListener("value-changed", (e) => {
      this._formData = { ...this._formData, ...e.detail.value };
      form.data = this._formData;
    });
    body.appendChild(form);

    // Read-only, not part of the entity picker itself -- these can't be
    // added/removed from that list (they're excluded regardless of it), so
    // showing them as ordinary, removable chips there would be misleading.
    // Direct user feedback: the helper text said they're always excluded,
    // but nothing actually showed *which* entities that meant.
    if (this._hardExcludedEntities.length) {
      const names = this._hardExcludedEntities
        .map((entityId) => friendlyEntityName(this._hass, entityId))
        .join(", ");
      const note = document.createElement("p");
      note.className = "hint";
      note.textContent = tr.hard_excluded_note(names);
      body.appendChild(note);
    }
    card.appendChild(body);
    return card;
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

      .icon-btn {
        border: none; background: none; color: inherit; cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        width: 40px; height: 40px; border-radius: 50%;
      }
      .icon-btn:hover { background: rgba(0, 0, 0, 0.05); }

      .content { display: block; }
      .content--list { padding: 0; }
      .content--form { padding: var(--ha-space-4, 16px); max-width: 640px; margin: 0 auto; }
      .loading, .empty {
        color: var(--secondary-text-color); padding: 32px 0; text-align: center;
        font-size: var(--ha-font-size-m, 14px);
      }
      .content--list .loading, .content--list .empty, .content--list .error { padding: 32px 16px; }
      /* .content--groups already has its own top/side padding (see below) --
         without this, a loading/error message shown there stacked its own
         vertical padding on top of the container's, landing at a different
         (larger) amount than every other tab instead of matching them. */
      .content--groups .loading, .content--groups .empty, .content--groups .error { padding: 0; }
      .error { color: var(--error-color); padding: 16px 0; font-size: var(--ha-font-size-m, 14px); }
      ha-list-base { display: block; }
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
      .settings-cards { display: flex; flex-direction: column; gap: 16px; }
      ha-card { margin: 0; }
      .card-content { padding: 0 16px 16px; display: flex; flex-direction: column; }
      .card-content > *:not(:first-child) { margin-top: 16px; }
      .card-actions { display: flex; justify-content: flex-end; padding: 8px 16px 16px; }
      .hint {
        color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 13px);
        line-height: 1.4; margin: 0;
      }

      /* Updates tab: matches ha-config-section-updates.ts's own static
         styles exactly (values and --ha-space-* tokens, not approximated
         pixels), not just "close enough". Deliberately scoped under
         .update-groups so it can't leak into the unrelated .card-content
         rules the settings cards above already use. */
      .content--groups {
        padding: var(--ha-space-7, 28px) var(--ha-space-5, 20px) 0;
        max-width: 1040px; margin: 0 auto;
      }
      .update-groups { display: block; }
      .update-groups ha-card {
        max-width: 600px; margin: 0 auto var(--ha-space-6, 24px);
      }
      .update-groups .card-content { padding: 0; display: block; }
      .update-groups .card-header {
        display: flex; align-items: center; justify-content: space-between;
        gap: var(--ha-space-2, 8px);
        padding: var(--ha-space-4, 16px) var(--ha-space-2, 8px) 0 var(--ha-space-4, 16px);
      }
      .update-groups .title { font-size: var(--ha-font-size-l, 18px); }
      .update-groups ha-list-base { margin-bottom: var(--ha-space-2, 8px); }
      .update-groups .no-updates { padding: 16px; }

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
      .dialog-history { list-style: none; margin: 0; padding: 0; }
      .dialog-history li {
        padding: var(--ha-space-2, 8px) 0; border-bottom: 1px solid var(--divider-color);
        font-size: var(--ha-font-size-s, 13px);
      }
      .dialog-history li:last-child { border-bottom: none; }
      .dialog-history-notes {
        color: var(--secondary-text-color); margin-top: 2px;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      }
    `;
  }
}

if (!customElements.get("update-manager-panel")) {
  customElements.define("update-manager-panel", UpdateManagerPanel);
}
