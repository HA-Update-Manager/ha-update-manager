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
// mdiChevronDown: the history dialog's own "expand this row's changelog"
// chevron (see _openDetailDialog), rotated 180deg via .open instead of
// relying on ha-expansion-panel's own built-in one: that component's row
// looked visually distinct from the plain ha-list-item-button used for
// entries with only a release_url (different padding/typography), which
// read as inconsistent sitting side by side in the same timeline. Direct
// user feedback. Both now render as the exact same ha-list-item-button
// row; only the trailing icon (this rotating chevron vs. ICON_OPEN_IN_NEW
// below) signals which of the two actually happens on click.
const ICON_CHEVRON_DOWN = "M7.41,8.58L12,13.17L16.59,8.58L18,10L12,16L6,10L7.41,8.58Z";
// mdiOpenInNew: the entries in that same history timeline whose row opens
// an external release page instead of expanding in place. Direct user
// feedback: ha-icon-next (a plain chevron, this file's usual "opens more
// detail" signal, e.g. _buildListRow) doesn't actually say "leaves the
// app" the way this universally-recognized external-link glyph does.
const ICON_OPEN_IN_NEW = "M14,3V5H17.59L7.76,14.83L9.17,16.24L19,6.41V10H21V3M19,19H5V5H12V3H5C3.89,3 3,3.9 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V12H19V19Z";
// mdiThumbUp/mdiAlert, verified against api.iconify.design (2026-07-22): the
// community-verdict badge (see verdictBadge), read-only slice, no vote UI
// yet. Thumb-up for zero problematic reports, alert for one or more.
const ICON_THUMB_UP =
  "M23 10a2 2 0 0 0-2-2h-6.32l.96-4.57c.02-.1.03-.21.03-.32c0-.41-.17-.79-.44-1.06L14.17 1L7.59 7.58C7.22 7.95 7 8.45 7 9v10a2 2 0 0 0 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73zM1 21h4V9H1z";
const ICON_ALERT = "M13 14h-2V9h2m0 9h-2v-2h2M1 21h22L12 2z";

// hass.language-driven, same convention this project family's other files
// use (see cover-media-card.js's TRANSLATIONS/_tr) -- flat keys, English as
// the base/fallback language. Found live: a user with hass.language "en"
// still saw an all-Dutch panel, since nothing here ever looked at
// hass.language at all before this.
const TRANSLATIONS = {
  en: {
    // Explicit BCP-47 locale for absoluteWhen's own toLocaleDateString/
    // toLocaleTimeString calls -- found live: passing `undefined` there
    // uses the browser's own OS-level locale instead, which isn't
    // necessarily the same as hass.language (a user can easily have
    // these two disagree), producing a mixed-language result (e.g. an
    // English "today" from our own tr object right next to a Dutch
    // weekday name from the browser's locale).
    locale: "en",
    tab_updates: "Updates",
    tab_history: "History",
    tab_settings: "Settings",
    refresh: "Refresh",
    refreshed_toast: "Update Manager refreshed",
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
    // Functions, not plain strings, for the two with a calendar-version
    // example (currentCalendarVersion): always today's real year/month,
    // never a hardcoded date that quietly goes stale. size_big_desc stays
    // a function too, purely so every size_*_desc can be called the same
    // way (see computeHelper below) rather than branching per size.
    size_small_desc: () => {
      const { year, month } = currentCalendarVersion();
      return `A patch release (e.g. 1.0.0 → 1.0.1), or the same calendar month (e.g. ${year}.${month}.0 → ${year}.${month}.1).`;
    },
    size_medium_short: "Medium",
    size_medium_desc: () => {
      const { year, month, nextYear, nextMonth } = currentCalendarVersion();
      return (
        `A minor release (e.g. 1.0.0 → 1.1.0), a new calendar month/year (e.g. ${year}.${month}.0 → ` +
        `${nextYear}.${nextMonth}.0), or a commit-hash update (e.g. 7sg82tw → 8dhw8wg).`
      );
    },
    size_big_short: "Big",
    size_big_desc: () => "A major release (e.g. 1.0.0 → 2.0.0) or a jump too different to classify.",
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
    status_ready: "Ready to update",
    status_waiting_manual: (when) => `Ready to update ${when}`,
    status_waiting_soon: "Postponed (almost ready)",
    // Short, unparameterized form -- for the dialog header's brief .state
    // value (matching state-card-update.ts's own short state text, not a
    // full sentence -- the countdown itself already lives in the alert
    // body below via statusText).
    status_waiting_short: "Postponed",
    status_blocked: "Discouraged",
    status_skipped: "Skipped",
    // Lowercase, distinct from the Title Case group heading above -- matches
    // ha-config-updates.ts's own row template, confirmed against its real
    // source: `${title} ${latest_version} (${localize("ui.panel.config.updates.skipped")})`.
    status_skipped_suffix: "skipped",
    // Overrides every other status while attributes.in_progress is true
    // (see statusText/timerBadge's own installing check) -- HA's own
    // ui.panel.config.updates.update_in_progress is only ever used as an
    // accessibility label (a spinner's aria-label/ha-progress-ring's own
    // label, confirmed against ha-config-updates.ts's real source), never
    // shown as visible text anywhere in HA itself -- this is our own
    // dialog's status-alert text specifically, which (unlike HA's) has no
    // other way to say what's happening right now.
    status_installing: "Installing…",
    status_pending_install: (when) => `Will update automatically ${when}`,
    // Plain " ⋅ " separator, not a parenthetical -- same separator already
    // used elsewhere in this file (e.g. the history entry's
    // "from → to ⋅ when" line) to combine two independent facts.
    always_manual_suffix: " ⋅ Always manual",
    field_excluded_entities: "Always manual",
    field_excluded_entities_helper:
      "Still shown normally in Updates and History. Update Manager just never auto-installs these, regardless of what's configured above.",
    field_wait_days: "Postponement period (days)",
    field_auto_install: "Update automatically",
    auto_install_section_title: "Auto-update",
    field_hide_postponed: "Hide postponed updates",
    field_hide_postponed_helper:
      "Marks a postponed update as skipped in Home Assistant itself until it's actually ready. Postponing is worth it: it gives a release with a bug time to be noticed and fixed before you commit to it.",
    auto_install_section_desc: "Only applies to sizes where \"Update automatically\" is checked above.",
    announce_hours_label: "Announcement notice (hours)",
    announce_hours_helper:
      "How long you have to cancel a scheduled automatic install (Updates tab) before it actually happens, once the postponement period is over.",
    col_impact: "Impact",
    dialog_current_version: "Installed version",
    dialog_new_version: "Latest version",
    dialog_community_verdict: "Community verdict",
    dialog_community_verdict_disclaimer:
      "A collected opinion from other users, not a guarantee. Be extra careful with safety-relevant devices (locks, alarms, smoke detectors).",
    dialog_release_announcement: "Release announcement",
    dialog_history_heading: "History",
    dialog_history_auto: "Automatically updated",
    dialog_history_release_link: "Release page",
    dialog_history_changelog: "View changelog",
    dialog_more_info: "More info",
    paused_banner: "Update Manager is paused. Nothing below will be updated, announced, or hidden automatically.",
    // Renamed from "Update Manager" (2026-07-21, direct user feedback): now
    // that this card also covers hide_postponed (merged in from its own
    // former "Visibility in Home Assistant" card), "the settings page's
    // own name repeated as a card title on the settings page" read as odd,
    // and "General" is what this actually is: the settings that aren't
    // specific to any one size, as opposed to "Update rules" (per size)
    // and "Auto-update" (the auto-install mechanism's own details) below
    // it.
    enabled_section_title: "General",
    field_enabled: "Enabled",
    field_enabled_helper:
      "Pauses every automatic action below: no announcements, no automatic installs, and postponed updates stop being hidden from Home Assistant's own update count. Everything you've configured stays saved, it just isn't applied until you turn this back on.",
    settings_header: "Update rules",
    settings_hint:
      "Every update is grouped into one of these three sizes, based on how big the version jump " +
      "is. For each, choose how many days to postpone it, and whether Update Manager should then " +
      "install it for you.",
    save: "Save",
    settings_saved_toast: "Settings saved",
    cancel_auto_install: "Cancel",
    dialog_install: "Update",
    dialog_skip: "Skip",
    dialog_unskip: "Clear skipped",
    group_ready: "Ready to update",
    group_waiting: "Postponed",
    group_blocked: "Discouraged",
    update_all: "Update all",
    // Rollout-pacing queue cards (see rollout_manager.py): one Zigbee
    // firmware install at a time per network, not several at once (real
    // radio traffic that can destabilize the mesh). Only ever shown once a
    // second device from the same network/model/version is asked to
    // install while one is already in flight.
    rollout_queue_title_zha: "ZHA update queue",
    rollout_queue_title_z2m: "Zigbee2MQTT update queue",
    rollout_queue_subtitle: "Installs one at a time to avoid overloading the Zigbee network.",
    // Reused verbatim for the dialog's own Install button while an entity
    // is queued (not yet its turn): no override, direct user feedback,
    // the queue must stay authoritative, not something a hurried click can
    // jump.
    rollout_queue_waiting: (name) => `Waiting for ${name}`,
    // Community-verdict badge tooltips (see verdictBadge), read-only slice
    // added 2026-07-22: https://github.com/HA-Update-Manager/community-votes.
    community_verdict_healthy: (count) =>
      `${count} ${count === 1 ? "person" : "people"} reported this version as healthy`,
    community_verdict_problematic: (count) =>
      `${count} ${count === 1 ? "person" : "people"} reported this version as problematic`,
    // Count+pluralized, matching ha-config-section-updates.ts's own real
    // title_skipped/title_not_installable convention (confirmed against its
    // source: both are passed {count} and pluralize the same way
    // ui.card.updates.count_updates does) -- direct user feedback: "HA doet
    // '3 skipped updates' en '1 not installable update'. Waarom heb je deze
    // logica niet overgenomen?".
    group_skipped: (count) => `${count} ${count === 1 ? "skipped update" : "skipped updates"}`,
    group_not_installable: (count) => `${count} ${count === 1 ? "not installable update" : "not installable updates"}`,
    updates_empty: "No updates need attention, everything is up to date.",
    history_empty: "No updates logged yet.",
    // History's own date sections (see historySections), relative rather
    // than a fixed calendar date range in the heading itself, same spirit
    // as relativeTime/absoluteWhen elsewhere in this file: "This week"
    // stays true and readable all week, a literal date range would need
    // recomputing (and re-reading) every single day.
    history_section_today: "Today",
    history_section_yesterday: "Yesterday",
    history_section_this_week: "This week",
    history_section_this_month: "This month",
    history_section_earlier: "Earlier",
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
    when_today: (time) => `today ${time}`,
    when_tomorrow: (time) => `tomorrow ${time}`,
    when_weekday: (weekday, time) => `${weekday} ${time}`,
    when_date: (date, time) => `${date}, ${time}`,
  },
  nl: {
    locale: "nl",
    tab_updates: "Updates",
    tab_history: "Historie",
    tab_settings: "Instellingen",
    refresh: "Vernieuwen",
    refreshed_toast: "Update Manager ververst",
    dash: "–",
    size_small_short: "Klein",
    size_small_desc: () => {
      const { year, month } = currentCalendarVersion();
      return `Een patch-release (bijv. 1.0.0 → 1.0.1), of dezelfde kalendermaand (bijv. ${year}.${month}.0 → ${year}.${month}.1).`;
    },
    size_medium_short: "Gemiddeld",
    size_medium_desc: () => {
      const { year, month, nextYear, nextMonth } = currentCalendarVersion();
      return (
        `Een minor-release (bijv. 1.0.0 → 1.1.0), een nieuwe kalendermaand/-jaar (bijv. ${year}.${month}.0 → ` +
        `${nextYear}.${nextMonth}.0), of een commit-update (bijv. 7sg82tw → 8dhw8wg).`
      );
    },
    size_big_short: "Groot",
    size_big_desc: () => "Een major-release (bijv. 1.0.0 → 2.0.0), of een sprong die niet te classificeren is.",
    status_ready: "Klaar om te updaten",
    status_waiting_manual: (when) => `Klaar om te updaten ${when}`,
    status_waiting_soon: "Uitgesteld (bijna zo ver)",
    status_waiting_short: "Uitgesteld",
    status_blocked: "Afgeraden",
    status_skipped: "Overgeslagen",
    status_skipped_suffix: "overgeslagen",
    status_installing: "Bezig met installeren…",
    status_pending_install: (when) => `Wordt automatisch geüpdatet ${when}`,
    always_manual_suffix: " ⋅ Altijd handmatig",
    field_excluded_entities: "Altijd handmatig",
    field_excluded_entities_helper:
      "Blijven gewoon zichtbaar bij Updates en Historie. Update Manager installeert ze alleen nooit automatisch, ongeacht wat je hierboven instelt.",
    field_wait_days: "Uitsteltermijn (dagen)",
    field_auto_install: "Automatisch updaten",
    auto_install_section_title: "Auto-update",
    auto_install_section_desc: "Geldt alleen voor groottes waar hierboven \"Automatisch updaten\" aan staat.",
    field_hide_postponed: "Uitgestelde updates verbergen",
    field_hide_postponed_helper:
      "Markeert een uitgestelde update zelf als overgeslagen in Home Assistant, tot 'ie echt klaar is. Uitstellen loont: het geeft een release met een fout de tijd om opgemerkt en gerepareerd te worden voordat jij 'm installeert.",
    announce_hours_label: "Aankondigingstermijn (uren)",
    announce_hours_helper:
      "Hoelang je hebt om een geplande automatische installatie (Updates-tab) te annuleren voordat die echt gebeurt, zodra de uitsteltermijn voorbij is.",
    col_impact: "Impact",
    dialog_current_version: "Geïnstalleerde versie",
    dialog_new_version: "Nieuwste versie",
    dialog_community_verdict: "Community-oordeel",
    dialog_community_verdict_disclaimer:
      "Een verzamelde mening van andere gebruikers, geen garantie. Wees extra voorzichtig bij veiligheidsgevoelige apparaten (sloten, alarmen, rookmelders).",
    dialog_release_announcement: "Release-aankondiging",
    dialog_history_heading: "Geschiedenis",
    dialog_history_auto: "Automatisch geüpdatet",
    dialog_history_release_link: "Release-pagina",
    dialog_history_changelog: "Changelog bekijken",
    dialog_more_info: "Meer info",
    paused_banner: "Update Manager staat gepauzeerd. Niets hieronder wordt automatisch geüpdatet, aangekondigd of verborgen.",
    enabled_section_title: "Algemeen",
    field_enabled: "Ingeschakeld",
    field_enabled_helper:
      "Pauzeert alle automatische acties hieronder: geen aankondigingen, geen automatische installaties, en uitgestelde updates worden niet langer verborgen voor Home Assistants eigen update-telling. Alles wat je hebt ingesteld blijft opgeslagen, het wordt alleen niet toegepast totdat je dit weer aanzet.",
    settings_header: "Update-regels",
    settings_hint:
      "Elke update valt in een van deze drie groottes, op basis van hoe groot de versiesprong is. " +
      "Per grootte kies je hoeveel dagen je 'm uitstelt, en of Update Manager 'm daarna zelf " +
      "installeert.",
    save: "Opslaan",
    settings_saved_toast: "Instellingen opgeslagen",
    cancel_auto_install: "Annuleren",
    dialog_install: "Updaten",
    dialog_skip: "Overslaan",
    dialog_unskip: "Overslaan ongedaan maken",
    group_ready: "Klaar om te updaten",
    group_waiting: "Uitgesteld",
    group_blocked: "Afgeraden",
    update_all: "Alles updaten",
    rollout_queue_title_zha: "ZHA-wachtrij",
    rollout_queue_title_z2m: "Zigbee2MQTT-wachtrij",
    rollout_queue_subtitle: "Installeert één voor één om het Zigbee-netwerk niet te overbelasten.",
    rollout_queue_waiting: (name) => `Wacht op ${name}`,
    community_verdict_healthy: (count) =>
      `${count} ${count === 1 ? "persoon meldt" : "mensen melden"} deze versie als probleemloos`,
    community_verdict_problematic: (count) =>
      `${count} ${count === 1 ? "persoon meldt" : "mensen melden"} deze versie als problematisch`,
    group_skipped: (count) => `${count} ${count === 1 ? "overgeslagen update" : "overgeslagen updates"}`,
    group_not_installable: (count) =>
      `${count} ${count === 1 ? "niet installeerbare update" : "niet installeerbare updates"}`,
    updates_empty: "Geen updates die aandacht nodig hebben, alles is up-to-date.",
    history_empty: "Nog geen updates gelogd.",
    history_section_today: "Vandaag",
    history_section_yesterday: "Gisteren",
    history_section_this_week: "Deze week",
    history_section_this_month: "Deze maand",
    history_section_earlier: "Eerder",
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
    when_today: (time) => `vandaag ${time}`,
    when_tomorrow: (time) => `morgen ${time}`,
    when_weekday: (weekday, time) => `${weekday} ${time}`,
    when_date: (date, time) => `${date}, ${time}`,
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
  const names = ["enabled", "announce_hours", "excluded_entities", "hide_postponed"];
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

function updateSortKey(u, settings) {
  const priority = STATUS_SORT_PRIORITY[u.status] ?? STATUS_SORT_PRIORITY[_FALLBACK_STATUS];
  const availableSinceSec = u.available_since ? Math.floor(new Date(u.available_since).getTime() / 1000) : 0;
  // Same number the badge itself displays, not always plain remaining_seconds
  // -- found live: two auto-install-projected updates sorted apart, with an
  // unrelated manual one in between, because remaining_seconds alone (time
  // to "ready") no longer matches what's shown once projectedAutoInstallTime
  // (remaining_seconds + announce_hours) is what the badge actually counts
  // down to.
  const projected = u.status === "waiting" ? projectedAutoInstallTime(u, settings) : null;
  const waitingSeconds = projected
    ? Math.round((new Date(projected).getTime() - Date.now()) / 1000)
    : u.remaining_seconds;
  const secondary = u.status === "waiting" && waitingSeconds != null ? waitingSeconds : availableSinceSec;
  return priority * 10_000_000_000 + secondary;
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
    if (projected) return { icon: ICON_AUTO_DOWNLOAD, text: capitalize(absoluteWhen(tr, projected, hass)) };
    if (u.remaining_seconds != null) {
      const readyAt = new Date(Date.now() + u.remaining_seconds * 1000).toISOString();
      return { icon: ICON_CLOCK_OUTLINE, text: capitalize(absoluteWhen(tr, readyAt, hass)) };
    }
    return { icon: ICON_CLOCK_OUTLINE, text: tr.relative_soon };
  }
  if (u.pending_install) {
    return { icon: ICON_AUTO_DOWNLOAD, text: capitalize(absoluteWhen(tr, u.pending_install.execute_at, hass)) };
  }
  return null;
}

// A second, independent pill (see _buildListRow's own verdictBadgeInfo
// parameter), read from community_verdict.py's read-only community-votes
// lookup (https://github.com/HA-Update-Manager/community-votes, added
// 2026-07-22). No badge at all when null (not HACS-identified, or not yet
// rated): a neutral pill on every single row would be more clutter than
// signal for the common "nobody's voted yet" case.
function verdictBadge(tr, u) {
  const verdict = u.community_verdict;
  if (!verdict || (verdict.healthy_count === 0 && verdict.problematic_count === 0)) return null;
  if (verdict.problematic_count > 0) {
    return {
      icon: ICON_ALERT,
      text: String(verdict.problematic_count),
      title: tr.community_verdict_problematic(verdict.problematic_count),
    };
  }
  return {
    icon: ICON_THUMB_UP,
    text: String(verdict.healthy_count),
    title: tr.community_verdict_healthy(verdict.healthy_count),
  };
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

// The real current year/month, not a hardcoded example that would
// otherwise silently go stale (e.g. "2026.7" still shown as the calendar-
// versioning example long after that month has passed). Used by
// TRANSLATIONS' own size_small_desc/size_medium_desc, direct user
// feedback. month is already 1-indexed (getMonth() + 1). Also includes the
// following month/year (found by review, 2026-07-22: this exact rollover
// arithmetic was independently duplicated in both the en and nl
// size_medium_desc entries), so both locales can just consume the values
// instead of each re-deriving them.
function currentCalendarVersion() {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;
  const nextMonth = month === 12 ? 1 : month + 1;
  const nextYear = month === 12 ? year + 1 : year;
  return { year, month, nextYear, nextMonth };
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
function absoluteWhen(tr, iso, hass) {
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
  const dayDiff = Math.round((startOfDay(date) - startOfDay(new Date())) / 86400000);
  if (dayDiff === 0) return tr.when_today(time);
  if (dayDiff === 1) return tr.when_tomorrow(time);
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
function installProgressBar(state) {
  if (!updateIsInstalling(state)) return null;
  const bar = document.createElement("ha-progress-bar");
  const supportsProgress = (state.attributes.supported_features || 0) & 4 && state.attributes.update_percentage != null;
  if (supportsProgress) {
    bar.loading = true;
    bar.value = state.attributes.update_percentage;
  } else {
    bar.indeterminate = true;
  }
  return bar;
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
    this._rolloutGroups = [];
    this._installLog = null;
    this._settings = null;
    this._profiles = null;
    this._hardExcludedEntities = [];
    this._dialogEntityId = null;
    this._dialogLastState = null;
    this._dialogProgressContainer = null;
    this._dialogInstallBtn = null;
    this._dialogStatusTextNode = null;
    this._dialogActionButtons = [];
    this._installSnapshots = null;
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
      this._updateDialogProgress();
      this._updateInstallProgress();
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
        this._formData = {
          enabled: true,
          excluded_entities: [],
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

  async _refresh() {
    // Re-fetches our own already-computed state (updates/history/settings)
    // and redraws -- it does not itself poll HA Core/HACS for brand new
    // versions (that's each underlying integration's own update coordinator,
    // typically hourly), just makes sure the page reflects whatever this
    // integration's own coordinator already knows right now, including
    // anything the 15-minute periodic recheck picked up since the page was
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
  _updateDialogProgress() {
    if (!this._dialogEntityId || !this._dialogProgressContainer) return;
    const state = entityState(this._hass, this._dialogEntityId);
    if (state === this._dialogLastState) return;
    this._dialogLastState = state;

    this._dialogProgressContainer.innerHTML = "";
    const bar = installProgressBar(state);
    if (bar) this._dialogProgressContainer.appendChild(bar);

    const installing = updateIsInstalling(state);
    if (this._dialogInstallBtn) {
      this._dialogInstallBtn.progress = installing;
      this._dialogInstallBtn.disabled = updateButtonIsDisabled(state);
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
    for (const u of this._updates) {
      const state = entityState(this._hass, u.entity_id);
      const installing = updateIsInstalling(state);
      const installedVersion = state && state.attributes && state.attributes.installed_version;
      next.set(u.entity_id, { installing, installedVersion });
      const prev = previous.get(u.entity_id);
      if (!prev) continue;
      if (prev.installing !== installing) installingChanged = true;
      if (prev.installedVersion !== installedVersion) anyVersionChanged = true;
    }
    this._installSnapshots = next;
    if (anyVersionChanged) {
      this._loadAll().then(() => this._renderContent());
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
    if (this._dialogEntityId === entityId) this._openDetailDialog(entityId);
    this._renderContent();
  }

  _renderContent() {
    if (!this._contentEl) return;
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
      const card = document.createElement("ha-card");
      card.outlined = true;
      const empty = document.createElement("div");
      empty.className = "no-updates";
      empty.textContent = tr.updates_empty;
      card.appendChild(empty);
      outer.appendChild(card);
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
        .sort((a, b) => updateSortKey(a, this._settings) - updateSortKey(b, this._settings))
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
              verdictBadge(tr, u)
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
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = tr.history_empty;
      return empty;
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
        const badge = entry.auto_installed ? { icon: ICON_AUTO_DOWNLOAD, title: tr.dialog_history_auto } : null;
        const row = this._buildListRow(
          entry.entity_id,
          supporting,
          () => this._openDetailDialog(entry.entity_id),
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
  _openDetailDialog(entityId) {
    const tr = this._tr;
    const dialog = this._dialogEl;
    // Tracks which entity the dialog is currently showing -- lets an
    // in-flight release-notes fetch (see below) recognize itself as stale
    // if the dialog closes or gets reopened for a different entity before
    // it resolves.
    this._dialogEntityId = entityId;
    // Live-updated by _updateDialogProgress (see set hass) as real
    // state_changed pushes stream in, exactly like more-info-update.ts's
    // own reactive stateObj -- not something this one-shot render call
    // itself keeps current.
    this._dialogLastState = entityState(this._hass, entityId) || null;
    this._dialogInstallBtn = null;
    this._dialogStatusTextNode = null;
    this._dialogActionButtons = [];
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
        // alert body below via statusText).
        const stateValue = document.createElement("div");
        stateValue.className = "state";
        stateValue.textContent = (u.status === "waiting" ? tr.status_waiting_short : tr[`status_${u.status}`]) || u.status;
        header.appendChild(stateValue);
      }
      body.appendChild(header);
    }

    if (u) {
      // A live install-progress bar (indeterminate, or percentage-based
      // when the entity supports it) -- matching more-info-update.ts's own
      // placement exactly (confirmed against its real source): below the
      // shared entity header (state-info above, icon/name/state -- that's
      // a separate, domain-agnostic component in real HA too, not part of
      // more-info-update.ts itself), at the very top of the domain-
      // specific content, before the title. Shown only while
      // attributes.in_progress is true, updated in place as that changes
      // (see _updateDialogProgress) rather than by rebuilding this whole
      // dialog on every hass push.
      this._dialogProgressContainer = document.createElement("div");
      this._dialogProgressContainer.className = "dialog-progress";
      const initialBar = installProgressBar(this._dialogLastState);
      if (initialBar) this._dialogProgressContainer.appendChild(initialBar);
      body.appendChild(this._dialogProgressContainer);

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
      this._dialogStatusTextNode = document.createTextNode(statusText(tr, u, this._settings, this._hass));
      statusAlert.appendChild(this._dialogStatusTextNode);
      // Buttons pushed onto this._dialogActionButtons below (reset
      // unconditionally at the top of this method) get disabled while
      // actually installing (see _updateDialogProgress), same as
      // more-info-update.ts's own Skip button
      // (.disabled=${... || updateIsInstalling(stateObj)}) -- none of
      // these actions make sense mid-install.
      // Cancellable even before a real announcement exists yet -- still
      // "waiting" but auto-install is projected to happen (see
      // projectedAutoInstallTime above), not just once actually "ready"
      // and formally announced. Direct user feedback: seeing "will update
      // automatically" with no way to act on it read as a real gap.
      // install_manager.py's async_cancel already supports this (records
      // the cancellation regardless of whether a PendingAnnouncement
      // exists yet), so only the to_version to send needs picking: the
      // real announcement's own target once one exists, else whatever
      // version is currently projected.
      const cancelToVersion = u.pending_install
        ? u.pending_install.to_version
        : projectedAutoInstallTime(u, this._settings)
          ? u.latest_version
          : null;
      if (cancelToVersion) {
        const cancelBtn = document.createElement("ha-progress-button");
        cancelBtn.slot = "action";
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
      // A real, user-initiated skip (see coordinator.py's own
      // is_own_skip distinction -- our own staging_skip.py auto-skips
      // never reach this status at all, they just read as "waiting") --
      // one-click undo via HA's own real update.clear_skipped, not
      // something you'd otherwise have to remember to do from HA's own
      // device page instead.
      if (u.status === "skipped") {
        const unskipBtn = document.createElement("ha-progress-button");
        unskipBtn.slot = "action";
        unskipBtn.label = tr.dialog_unskip;
        unskipBtn.disabled = updateIsInstalling(this._dialogLastState);
        unskipBtn.addEventListener("click", () =>
          _runProgressAction(unskipBtn, async () => {
            await this._hass.callWS({ type: "update_manager/unskip", entity_id: entityId });
            await this._afterDialogAction(entityId);
          })
        );
        statusAlert.appendChild(unskipBtn);
        this._dialogActionButtons.push(unskipBtn);
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

      // Its own section, own heading, own divider, not folded into the rows
      // above: direct user feedback, 2026-07-22, this is also where a
      // future vote button belongs once voting itself is built (not this
      // read-only slice), so it needs a real home now rather than being
      // squeezed into the version/impact rows.
      const dialogVerdictInfo = verdictBadge(tr, u);
      if (dialogVerdictInfo) {
        body.appendChild(document.createElement("hr"));
        const communityHeading = document.createElement("h3");
        communityHeading.textContent = tr.dialog_community_verdict;
        body.appendChild(communityHeading);

        // Same friendly sentence the list badge's own tooltip already uses
        // (see verdictBadge/community_verdict_healthy/_problematic), not a
        // terser "N healthy, N problematic": direct user feedback,
        // 2026-07-22, a full sentence reads better once it has its own
        // section, not just a compact hover hint.
        const communityContent = document.createElement("div");
        communityContent.className = "dialog-community";
        const communityIcon = document.createElement("ha-svg-icon");
        communityIcon.path = dialogVerdictInfo.icon;
        communityContent.appendChild(communityIcon);
        const communityText = document.createElement("span");
        communityText.textContent = dialogVerdictInfo.title;
        communityContent.appendChild(communityText);
        body.appendChild(communityContent);

        // Found by review, 2026-07-22: FUTURE.md's own disclaimer
        // requirement for this feature ("a clear, unavoidable disclaimer
        // with every verdict, not just in the README") had no visible text
        // anywhere in this UI at all. Placed here, not just the badge's
        // hover tooltip: unlike a tooltip, this is always visible whenever
        // a verdict is shown, no hover needed.
        const communityDisclaimer = document.createElement("p");
        communityDisclaimer.className = "hint";
        communityDisclaimer.textContent = tr.dialog_community_verdict_disclaimer;
        body.appendChild(communityDisclaimer);
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

      // One ha-card per entry, not a plain <ul>. Direct user feedback
      // (2026-07-17): felt "spuug lelijk", didn't read as HA at all. Same
      // outlined-card building block the Settings tab already uses, read
      // top-to-bottom as a timeline (newest first, same order the log
      // itself is already in). Each card is fully clickable when there's
      // anywhere to go (release notes to expand, or a release page to
      // open), collapsed by default. Only the version jump + when +
      // auto/manual pill is always visible, matching direct user feedback
      // that a card should open to show its details rather than dumping
      // everything inline.
      const list = document.createElement("div");
      list.className = "dialog-history";
      entries.forEach((entry) => {
        const card = document.createElement("ha-card");
        card.outlined = true;

        const content = document.createElement("div");
        content.className = "card-content dialog-history-card";

        const versionText = `${entry.from_version} → ${entry.to_version}`;
        const whenText = relativeTime(tr, entry.installed_at);
        const pill = entry.auto_installed
          ? this._buildTimerPill({ icon: ICON_AUTO_DOWNLOAD, title: tr.dialog_history_auto })
          : null;

        // A timeline of versions is only worth having if you can actually
        // get to what changed. Direct user feedback: the version+time
        // line used to sit there inert, with a separate small "View
        // changelog" toggle and a separate link line competing for
        // attention below it. Now the whole row is the one thing you'd
        // tap: reads the changelog in place if there is one to read, else
        // opens the original release page, else it's plain, unclickable
        // fact (no chevron promising an action that doesn't exist).
        if (entry.release_notes || entry.release_url) {
          // One row shape for both interactive cases, not ha-expansion-panel
          // for one and ha-list-item-button for the other. Direct user
          // feedback: those two components' own different padding/
          // typography made entries look inconsistent sitting right next
          // to each other in the same timeline. Only the trailing icon
          // differs: a chevron that rotates (expands the changelog in
          // place, below) versus the external-link glyph (opens the
          // release page, see ICON_OPEN_IN_NEW's own comment).
          const hasNotes = !!entry.release_notes;
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
          const chevron = document.createElement("ha-svg-icon");
          if (hasNotes) {
            chevron.path = ICON_CHEVRON_DOWN;
            chevron.className = "dialog-history-chevron";
          } else {
            chevron.path = ICON_OPEN_IN_NEW;
            chevron.title = tr.dialog_history_release_link;
          }
          end.appendChild(chevron);
          row.appendChild(end);
          content.appendChild(row);

          if (hasNotes) {
            // Collapsed by default, toggled by hand (not ha-expansion-panel's
            // own built-in toggle, see this block's own comment above) --
            // just a hidden attribute and a rotated icon, not a new
            // component of its own.
            const notesWrap = document.createElement("div");
            notesWrap.className = "dialog-history-notes-wrap";
            notesWrap.hidden = true;
            const markdown = document.createElement("ha-markdown");
            markdown.content = entry.release_notes;
            notesWrap.appendChild(markdown);
            // Still reachable even while primarily reading the notes in
            // place, same .row/.key link-only pattern as the release_url
            // row above for the entity's *currently* pending update,
            // confirmed against more-info-update.ts's own source, not a
            // one-off style of its own.
            if (entry.release_url) {
              const linkRow = document.createElement("div");
              linkRow.className = "row";
              const linkKey = document.createElement("div");
              linkKey.className = "key";
              const link = document.createElement("a");
              link.href = entry.release_url;
              link.target = "_blank";
              link.rel = "noreferrer";
              link.textContent = tr.dialog_history_release_link;
              linkKey.appendChild(link);
              linkRow.appendChild(linkKey);
              notesWrap.appendChild(linkRow);
            }
            content.appendChild(notesWrap);
            row.addEventListener("click", () => {
              notesWrap.hidden = !notesWrap.hidden;
              chevron.classList.toggle("open", !notesWrap.hidden);
            });
          } else {
            row.addEventListener("click", () => window.open(entry.release_url, "_blank", "noopener,noreferrer"));
          }

          if (entry.release_summary && !hasNotes) {
            const notesEl = document.createElement("div");
            notesEl.className = "dialog-history-notes";
            notesEl.textContent = entry.release_summary;
            content.appendChild(notesEl);
          }
        } else {
          // Nothing to read, nowhere to go: a plain, unclickable fact --
          // no chevron, no ha-list-item-button ripple/hover promising an
          // action that isn't there.
          const main = document.createElement("div");
          main.className = "dialog-history-main";
          const versions = document.createElement("span");
          versions.className = "dialog-history-versions";
          versions.textContent = versionText;
          main.appendChild(versions);
          const when = document.createElement("span");
          when.className = "dialog-history-when";
          when.textContent = whenText;
          main.appendChild(when);
          if (pill) main.appendChild(pill);
          content.appendChild(main);
          if (entry.release_summary) {
            const notesEl = document.createElement("div");
            notesEl.className = "dialog-history-notes";
            notesEl.textContent = entry.release_summary;
            content.appendChild(notesEl);
          }
        }

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
      // Already skipped: the alert's own "Clear skipped" button (see
      // above) covers the only relevant action here, showing this too
      // would just be a redundant, no-op way to skip an already-skipped
      // update again. Install stays available either way (skipping
      // doesn't prevent installing, it's only "don't bug me about this").
      if (u.status !== "skipped") {
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

      if (u.installable) {
        // A queued (not yet dispatched) Zigbee rollout entry can't jump
        // the line from here either (no-override decision, see
        // rollout_manager.py's own docstring): same "waiting for X" text
        // the queue card itself shows, button disabled instead of a
        // working Install.
        const rolloutStatus = this._rolloutStatusFor(entityId);
        const isQueued = !!(rolloutStatus && rolloutStatus.status === "queued");
        const installBtn = document.createElement("ha-progress-button");
        installBtn.appearance = "filled";
        installBtn.label = isQueued
          ? tr.rollout_queue_waiting(friendlyEntityName(this._hass, rolloutStatus.frontEntityId))
          : tr.dialog_install;
        installBtn.disabled = isQueued || updateButtonIsDisabled(this._dialogLastState);
        installBtn.progress = updateIsInstalling(this._dialogLastState);
        this._dialogInstallBtn = installBtn;
        // Fire-and-forget, not awaited before reacting -- matches
        // more-info-update.ts's own _handleInstall exactly (confirmed
        // against its real source): it doesn't await this call either.
        // Direct user feedback: HA's own dialog shows a live progress bar
        // and eventually the entity's new state right there, it doesn't
        // just wait on the service call and then close -- some updates
        // (e.g. a slow HAOS/add-on install) can run long after the
        // service call itself returns, so gating our own UI on that
        // promise either closed the dialog too early or left it stuck
        // spinning for no visible reason. The button's own .progress/
        // .disabled now instead track the entity's real in_progress/state
        // attributes live (see _updateDialogProgress, driven by set hass),
        // same as HA's own .loading=${updateIsInstalling(stateObj)}.
        installBtn.addEventListener("click", () => {
          const msg = { type: "update_manager/install", entity_id: entityId };
          // UpdateEntityFeature.BACKUP = 8 (homeassistant/components/
          // update/const.py) -- same condition install_manager.py's own
          // auto-install already uses, kept consistent here.
          if (state && (state.attributes.supported_features || 0) & 8) {
            msg.backup = true;
          }
          // update_manager/install, not a plain hass.callService -- this
          // entity might currently be postponed or skipped (either a real
          // user skip, or our own hide_postponed auto-skip); the websocket
          // command clears that immediately as part of installing, instead
          // of leaving it looking postponed/skipped until the install
          // itself finishes. Not awaited before reacting, same reasoning
          // as before: the command dispatches update.install as its own
          // task rather than blocking on the full install either.
          this._hass.callWS(msg).catch((err) => {
            this._showToast((err && err.message) || String(err));
          });
        });
        actions.appendChild(installBtn);
      }
    }

    dialog.appendChild(actions);

    dialog.open = true;
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
    // No explicit Save button -- every field autosaves itself (debounced,
    // see _scheduleAutosave), direct user feedback: "kunnen we niet direct
    // saven bij elke edit ipv via een losse button?".

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
      // just "small"/"medium"/"big"), rendered by ha-form-expandable as
      // its own line below the header, not squeezed into the title
      // itself, and visible regardless of expanded state.
      if (SIZES.includes(s.name)) return tr[`size_${s.name}_desc`]();
      // No per-field helper for auto_install (direct user feedback:
      // text-heavy page): it used to repeat the exact same sentence
      // identically under Small, Medium, and Big, since all three
      // sections used to be always expanded at once. Said once now, in
      // settings_hint above, instead of three times in a row.
      return "";
    };
    form.addEventListener("value-changed", (e) => {
      this._formData = { ...this._formData, ...e.detail.value };
      form.data = this._formData;
      this._scheduleAutosave();
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
      const chosen = e.detail.value.excluded_entities.filter((id) => !this._hardExcludedEntities.includes(id));
      this._formData = { ...this._formData, excluded_entities: chosen };
      entitiesForm.data = { ...this._formData, excluded_entities: this._mergedExcludedEntities() };
      this._scheduleAutosave();
    });
    body.appendChild(entitiesForm);

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
      .loading, .empty {
        color: var(--secondary-text-color); padding: 32px 0; text-align: center;
        font-size: var(--ha-font-size-m, 14px);
      }
      /* Every tab shares one padded/centered container (.content--groups/
         --form/--list below all resolve to the same rule). Without this,
         a loading/error message shown there stacked its own vertical
         padding on top of the container's, landing at a different (larger)
         amount than the rest of the page. */
      .content--groups .loading, .content--groups .empty, .content--groups .error,
      .content--form .loading, .content--form .empty, .content--form .error,
      .content--list .loading, .content--list .empty, .content--list .error { padding: 0; }
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
      .settings-cards { display: flex; flex-direction: column; gap: 16px; }
      /* Same 600px per-card width as .update-groups ha-card below. All
         three tabs' cards read as one consistent-width column regardless
         of which tab put them there (2026-07-21, direct user feedback).
         Explicit width: 100% (not left at the default auto) plus
         max-width and margin: 0 auto together, not align-self: the
         "Auto-update" card isn't a direct child of .settings-cards (it
         sits inside its own autoInstallSlot wrapper div, see
         _buildSettingsCard, so it can be shown/hidden without disturbing
         its siblings). A plain descendant selector reaches it too, but
         align-self only has any effect on a flex container's own direct
         children, so it would have centered every other card while
         leaving this one flush left. width: 100% first (a flex item's
         auto margins would otherwise disable stretch-to-fill and shrink
         it to content width instead, found live) means margin: 0 auto can
         do the centering here exactly like it already does for
         .update-groups ha-card below, in a plain block context. */
      .settings-cards ha-card { width: 100%; max-width: 600px; margin: 0 auto; }
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
      .update-groups-outer > ha-alert { display: block; max-width: 600px; margin: 0 auto var(--ha-space-6, 24px); }
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
      .dialog-community { display: flex; align-items: center; gap: var(--ha-space-2, 8px); color: var(--primary-text-color); }
      /* Empty (and invisible) whenever nothing's installing -- only ever
         holds a single ha-progress-bar, inserted/removed live by
         _updateDialogProgress, same spot more-info-update.ts's own
         in_progress bar occupies (top of its content). */
      .dialog-progress:empty { display: none; }
      .dialog-progress ha-progress-bar { margin-bottom: var(--ha-space-4, 16px); }
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
         ha-list-item-button (both interactive cases now, see
         _openDetailDialog) already carries its own generous, native
         padding. This card's own 16px on top of that was stacking two
         insets into one that read as excessive. The one case with no
         built-in padding of its own, the plain unclickable fallback
         (.dialog-history-main), gets its padding set directly on itself
         instead, below. */
      .dialog-history-card { padding: 0; font-size: var(--ha-font-size-s, 13px); }
      .dialog-history-main {
        display: flex; align-items: center; gap: var(--ha-space-2, 8px);
        color: var(--primary-text-color); padding: var(--ha-space-4, 16px);
      }
      /* .dialog-history-versions' own flex: 1 already pushes .dialog-history-when
         and the trailing auto-install pill (see _buildTimerPill above) to the
         row's far right as a group, no separate margin-left: auto needed. Only
         used by the plain, unclickable fallback now (no release_notes or
         release_url at all): the interactive case above builds its own row
         entirely out of ha-list-item-button instead. */
      .dialog-history-versions { flex: 1; font-weight: var(--ha-font-weight-medium, 500); }
      /* Same size as everything else here, not demoted. Direct user
         feedback: "it's a timeline of versions, the time isn't irrelevant."
         An earlier pass shrank this to try to de-emphasize it; reverted. */
      .dialog-history-when { color: var(--secondary-text-color); }
      .dialog-history-notes {
        color: var(--secondary-text-color); margin-top: var(--ha-space-2, 8px);
        white-space: pre-wrap;
      }
      /* font-size reset, not inherited: .dialog-history-card shrinks its
         whole content area to 13px (a deliberately compact timeline row),
         which would otherwise also shrink ha-list-item-button's own
         headline/supporting-text below the normal size that same
         component uses elsewhere in this file (Updates list), looking and
         feeling noticeably weaker by comparison. Direct user feedback. */
      .dialog-history-card ha-list-item-button { font-size: var(--ha-font-size-m, 14px); }
      /* The chevron for the "expand this row's changelog in place" case
         (see ICON_CHEVRON_DOWN/_openDetailDialog). Rotates on toggle the
         same way ha-expansion-panel's own built-in chevron would, since
         this row no longer uses that component (see this block's own
         comment above for why). */
      .dialog-history-chevron {
        transition: transform 150ms ease-in-out;
      }
      .dialog-history-chevron.open { transform: rotate(180deg); }
      /* Matches ha-list-item-button's own horizontal inset above it, so the
         expanded changelog's left/right edges line up with the row's own
         text instead of sitting flush against the card's true edges. */
      .dialog-history-notes-wrap {
        padding: 0 var(--ha-space-4, 16px) var(--ha-space-4, 16px);
      }
      .dialog-history-notes-wrap .row { margin-top: var(--ha-space-2, 8px); }
      .dialog-history ha-markdown { display: block; padding-top: var(--ha-space-2, 8px); }
    `;
  }
}

if (!customElements.get("update-manager-panel")) {
  customElements.define("update-manager-panel", UpdateManagerPanel);
}
