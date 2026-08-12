/**
 * Update Manager panel: all user-facing copy (English + Dutch), kept in its
 * own file so it's easy to find and edit without wading through the rest of
 * the panel's rendering logic -- direct user feedback, 2026-08-07: "Ik wil
 * alle copy, bij alle projecten, centraal kunnen beheren per taal."
 *
 * Loaded via a dynamic import from update-manager-panel.js's own module
 * scope (see that file's own comment right above where it does so), not a
 * plain static `import`: a static import would fetch this file as its own,
 * independently-cached resource, with none of panel.py's own
 * `_panel_js_cache_key` cache-busting -- exactly the "edited but the
 * browser keeps serving the old one" class of bug that mechanism already
 * exists to prevent for the main panel file itself. The dynamic import
 * instead reuses that exact same `?v=` query string (via import.meta.url),
 * so editing this file busts the browser's cache exactly like editing the
 * main file already does.
 */

// The real current year/month, not a hardcoded example that would
// otherwise silently go stale (e.g. "2026.7" still shown as the calendar-
// versioning example long after that month has passed). Used by
// TRANSLATIONS' own size_small_desc/size_medium_desc below, direct user
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

// hass.language-driven, same convention this project family's other files
// use (see cover-media-card.js's TRANSLATIONS/_tr) -- flat keys, English as
// the base/fallback language. Found live: a user with hass.language "en"
// still saw an all-Dutch panel, since nothing here ever looked at
// hass.language at all before this.
export const TRANSLATIONS = {
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
    checking_updates_toast: "Checking for updates…",
    refreshed_toast: "Update Manager refreshed",
    // "Update all" button's own click confirmation (see _updateAllInGroup)
    // -- fired immediately, before the actual dispatch/reload work, direct
    // user feedback: clicking it didn't show anything happening right away.
    update_all_started_toast: (count) => (count === 1 ? "Installing 1 update…" : `Installing ${count} updates…`),
    // Updates tab's own overflow (⋮) menu, next to the refresh button --
    // same interaction/component as Home Assistant's own native
    // /config/system/updates page (ha-config-section-updates.ts), deliberately
    // following its pattern. menu_show_skipped_updates matches HA's own real
    // string verbatim (confirmed against home-assistant/frontend's own
    // src/translations/en.json, ui.panel.config.updates.show_skipped: "Show
    // skipped updates") -- menu_show_not_installable_updates has no HA
    // equivalent to match (HA's own page shares one toggle for both groups,
    // ours are independent), written to match that same string's own
    // "Show ... updates" shape and HA's own title_not_installable
    // vocabulary ("not installable").
    menu_show_skipped_updates: "Show skipped updates",
    menu_show_not_installable_updates: "Show not installable updates",
    dash: "–",
    // Deliberately generic, not semver's own vocabulary (renamed
    // 2026-07-16): "Small/Medium/Large" is a scale any version
    // scheme maps onto -- semver, calendar versioning, and git commit
    // hashes each have their own notion of "small" (see semver.py). The
    // _desc text is a small (?) tooltip's own content next to the size's
    // own name in the Postponement/Auto-update settings rows
    // (buildSizeHelpTooltip, 2026-08-11), not a standalone paragraph --
    // the detail dialog's "Jump" fact row shows the _short word only, no
    // room/need for the explanation there either.
    size_small_short: "Small",
    // Functions, not plain strings, for the two with a calendar-version
    // example (currentCalendarVersion): always today's real year/month,
    // never a hardcoded date that quietly goes stale. size_large_desc stays
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
    size_large_short: "Large",
    size_large_desc: () => "A major release (e.g. 1.0.0 → 2.0.0) or a jump too different to classify.",
    // Used in the detail dialog's status alert (see statusText/
    // _openDetailDialog) -- no emoji prefix here, the alert's own color and
    // icon (a real ha-alert, success/info/warning) already carry that, an
    // emoji on top would be redundant. Green means the wait is over,
    // nothing is literally "done" yet on its own -- it may already be
    // auto-installing (status_pending_install below covers that case
    // specifically, with a matching download icon instead of the alert's
    // default one, see timerBadge). Orange is still waiting it out. Red is
    // for status_blocked ("Discouraged", e.g. a problematic community
    // verdict) that actively discourages an update; nothing
    // in today's local rules produces it on their own (see the settings legend's note).
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
    field_wait_days_unit: "days",
    field_auto_install: "Update automatically",
    auto_install_section_title: "Auto-update",
    // Same reasoning as postponement_sizes_label -- a heading over its own
    // group of size rows, not left to the card header alone.
    auto_install_sizes_label: "Which sizes install automatically?",
    field_hide_postponed: "Hide postponed updates",
    field_hide_postponed_helper: "Hides it from Home Assistant's own update count until it's ready.",
    field_ready_days_add: "Add a day",
    field_ready_remove: (day) => `Remove ${day}`,
    settings_schedule_hint: "Optional: only let an update become ready on specific days.",
    weekday_monday_short: "Monday",
    weekday_tuesday_short: "Tuesday",
    weekday_wednesday_short: "Wednesday",
    weekday_thursday_short: "Thursday",
    weekday_friday_short: "Friday",
    weekday_saturday_short: "Saturday",
    weekday_sunday_short: "Sunday",
    field_trusted_voters: "Trusted voters",
    field_trusted_voters_helper:
      "A GitHub username you trust more than your own rules. Their healthy vote overrides your rules above and auto-installs that jump immediately, even over someone else's problematic report.",
    announce_hours_label: "Announcement notice",
    announce_hours_unit: "hours",
    announce_hours_helper: "How long you still have to cancel a scheduled automatic install.",
    // "Jump" (not "Impact", renamed 2026-08-07, direct user feedback while
    // reviewing the big->large rename): this fact row shows the size of the
    // version *jump* itself (small/medium/large, see semver.py), not a
    // judgment about how impactful/consequential that jump turned out to
    // be -- same reasoning as dropping "big" for the neutral "large".
    col_jump: "Jump",
    // Noun, not "Announced" -- deliberately different label for the
    // projected-but-not-yet-real case (see projectedAnnouncementTime's own
    // comment), direct user feedback, 2026-08-01: "Announced" asserts it
    // already happened, which isn't true yet for a still-"waiting" update.
    dialog_announcement_label: "Announcement",
    dialog_current_version: "Installed version",
    dialog_new_version: "Latest version",
    dialog_community_verdict_disclaimer:
      "A collected opinion from other users, not a guarantee. Be extra careful with safety-relevant devices (locks, alarms, smoke detectors).",
    // Also the "nothing at all" row of the Community section's own fact
    // stack (see _buildCommunitySection) -- same wording either way, direct
    // user feedback, 2026-07-27: replaces the old question+"not yet rated"
    // pairing, which read as a non-answer with no clear next step.
    community_not_yet_rated: "No one's reported on this jump yet.",
    community_vote_link_prompt: "Link your GitHub account in Settings to vote.",
    // Surfaces whether a configured trusted voter is among the people who
    // voted on this exact jump -- direct user feedback, 2026-07-27: "dat
    // zie ik niet terug", after a trusted voter's own vote didn't show up
    // anywhere even though it's exactly what changes auto-install behavior
    // for this jump (see announcer.py's own effective_auto_install_state).
    // "Trusted vote:" prefix, not "Trusted voter(s)": names can be one or
    // several, this avoids needing a separate singular/plural form.
    community_trusted_vote_healthy: (names) => `Trusted vote: ${names} reported this jump as healthy.`,
    community_trusted_vote_problematic: (names) => `Trusted vote: ${names} reported this jump as problematic.`,
    community_trusted_voter_label: "Trusted voter",
    community_other_jumps_heading: "Other jumps to this version",
    community_other_jump_line: (fromVersion, badgeTitle) => `From ${fromVersion}: ${badgeTitle}`,
    community_problematic_reasons_heading: "Reported reasons",
    community_report_toggle: "Report a known issue",
    community_report_intro:
      "Already know this update will cause problems, e.g. from the release notes? Report it before installing, so others are warned before they update too.",
    community_vote_healthy: "Mark as healthy",
    community_vote_problematic: "Report as problematic",
    community_vote_submit: "Submit",
    // `updated` (see websocket_api.py's own is_vote_update): a repeat vote
    // on the same version now replaces your earlier one instead of being
    // rejected, 2026-07-23, direct user feedback asking whether a vote
    // could be changed -- said plainly here instead of leaving the previous
    // vote's confirmation text up as if this were the first time.
    // ownRepoHealthyVote (see websocket_api.py's own is_own_repo_healthy_vote):
    // mirrors community-votes' own "asymmetric weight for the repo owner"
    // rule -- a maintainer's own healthy vote on their own release is
    // recorded but never counts toward the tally, so said here instead of
    // showing a generic confirmation the standing then silently contradicts.
    community_vote_confirmed_healthy: (updated, ownRepoHealthyVote) => {
      if (ownRepoHealthyVote) {
        return "Marked as healthy. As the maintainer, this doesn't count toward the community tally, but thanks!";
      }
      return updated ? "Vote updated to healthy." : "Marked as healthy. Thanks for helping others decide.";
    },
    community_vote_confirmed_problematic: (reason, updated) =>
      updated ? `Vote updated to problematic: ${reason}.` : `Reported: ${reason}. Thanks for the heads-up.`,
    community_vote_reason_required: "Pick a reason first.",
    vote_field_reason_category: "Reason",
    vote_field_notes: "Notes (optional)",
    vote_field_link: "Issue or changelog link (optional)",
    vote_reason_broken: "Broken functionality",
    vote_reason_requires_newer: "Requires a newer HA version",
    vote_reason_dev_build: "Dev/pre-release build",
    vote_reason_breaking_change: "Breaking change",
    vote_reason_other: "Other",
    // Used to match real HA's own more-info-update.ts wording exactly
    // ("Read release announcement", confirmed live 2026-07-27). Changed to
    // "Open", 2026-08-01, direct user feedback: unlike HA's own dialog,
    // this link can now sit right below release notes we've *already*
    // shown (see appendReleaseNotesSection) -- "Read" implies you haven't
    // seen it yet, which reads oddly right under content you're looking
    // at; "Open" is just about visiting the source, correct either way,
    // whether the notes above are shown or this link is the section's only
    // content.
    dialog_release_announcement: "Open release announcement",
    dialog_history_heading: "History",
    // No reason recorded at all: an entry logged before this field existed
    // (2026-07-23) -- the generic fallback, not "unknown".
    dialog_history_auto: "Automatically updated",
    dialog_history_changelog: "View changelog",
    dialog_history_available_since: "Available since",
    dialog_history_announced: "Announced",
    dialog_history_installed_at: "Installed",
    dialog_history_method_label: "Install method",
    dialog_history_method_manual: "Manual",
    dialog_history_method_rules: "Automatic, your own rules",
    dialog_history_method_trusted: (names) => `Automatic, trusted vote from ${names}`,
    dialog_history_backup_label: "Backup",
    dialog_history_backup_yes: "Taken before installing",
    dialog_history_backup_no: "Not supported by this entity",
    dialog_release_notes_heading: "Release notes",
    dialog_upstream_release_notes: (repo) => `${repo}'s own release notes:`,
    dialog_community_heading: "Community",
    list_and: "and",
    dialog_auto_install_held_back: (names) => `Auto-install held back: ${names} reported this jump as problematic.`,
    dialog_auto_install_held_back_community: (count) =>
      count === 1
        ? "Auto-install held back: 1 person reported this jump as problematic."
        : `Auto-install held back: ${count} people reported this jump as problematic.`,
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
    community_section_title: "Help others",
    community_section_desc:
      "Become part of the community: link your GitHub account to vote on whether an update turned out healthy or problematic.",
    community_link: "Link GitHub account",
    community_unlink: "Unlink",
    community_linked_as: (username) => `Linked as @${username}`,
    community_link_instructions: "Go to the page below and enter this code:",
    community_link_waiting: "Waiting for you to approve on GitHub...",
    community_link_timed_out: "The linking code expired before it was approved, try again.",
    community_link_failed: "Linking failed or was declined, try again.",
    enabled_section_title: "General",
    field_enabled: "Update Manager",
    field_enabled_helper:
      "Pauses every automatic action below: no announcements, no automatic installs, and postponed updates stop being hidden from Home Assistant's own update count. Everything you've configured stays saved, it just isn't applied until you turn this back on.",
    sizes_section_title: "Update sizes",
    // Lead-in only -- the bullet list itself (what Small/Medium/Large
    // actually mean) is composed in JS from size_*_short/size_*_desc
    // directly, not duplicated here as static text: those already carry
    // live calendar-version examples (currentCalendarVersion), and this
    // used to be a per-row (?) tooltip reusing the exact same two
    // functions before it became its own card instead (2026-08-11, direct
    // user feedback: "die tooltips vind ik niks").
    sizes_intro_lead: "Every update is grouped into one of these three sizes, based on how big the version jump is.",
    settings_header: "Postponement",
    settings_hint:
      "Postponing is worth it: it gives a release with a bug time to be noticed and fixed before you commit to it.",
    // A real heading over the size rows, not just the intro paragraph above
    // them -- direct user feedback, 2026-08-11 ("de hierarchie is iets wat
    // op de pagina goed is maar in de secties/cards zelf nog niet"): a group
    // of related rows needs its own label to read as one group, the same
    // way excludedLabel/trustedLabel already head their own groups below in
    // Auto-update.
    postponement_sizes_label: "How long do you want to postpone?",
    save: "Save",
    settings_saved_toast: "Settings saved",
    cancel_auto_install: "Cancel",
    // The pending-update dialog's own "Ready now" button, next to Cancel --
    // forces this one jump to evaluate as ready immediately, skipping the
    // rest of its postponement period.
    dialog_force_ready: "Ready",
    dialog_open_update: "Open update",
    dialog_skip: "Skip",
    dialog_unskip: "Clear skipped",
    group_ready: "Ready to update",
    group_waiting: "Postponed",
    group_blocked: "Discouraged",
    update_all: "Update all",
    // The "Installing" section's own title (see _buildInstallingCard) --
    // everything currently installing or held back (the tier gate or the
    // Zigbee model gate, both server-side in rollout_manager.py), pulled
    // out of "Ready to update" entirely rather than reordered there.
    // Generalizes what used to be a per-Zigbee-group-only card.
    installing_section_title: "Installing",
    // Shown instead of the normal timer badge for an entity held back by
    // install_tiers.py's own tier gate -- deliberately generic, not naming
    // which specific update it's waiting for, unlike the Zigbee rollout
    // queue's own single-file "waiting for X" below (always exactly one
    // thing directly in front): the tier ahead here can be several
    // entities at once (every "safe" update in the same batch), so
    // there's no one name to point at.
    tier_waiting_text: "Waiting for other updates to finish first",
    // Shown once an entity crosses rollout_manager.py's own
    // _STUCK_THRESHOLD (a Repair issue is raised at the same time, see
    // that module's own _async_maybe_raise_stuck_issue) -- deliberately
    // different text than tier_waiting_text above: this entity isn't
    // waiting on anything, it IS the obstacle everything else is waiting
    // behind.
    stuck_waiting_text: (duration) => `Installing for ${duration}, longer than usual`,
    duration_hours_minutes: (hours, minutes) => `${hours}h ${minutes}m`,
    duration_minutes: (minutes) => `${minutes}m`,
    // The detail dialog's own stuck alert (see the pending-update dialog's
    // own stuckInfo block) -- states the plain fact, never a guessed
    // cause; dialog_stuck_body_zigbee/_neutral below is where the real,
    // per-entity explanation (or the honest absence of one) lives.
    dialog_stuck_title: (duration) => `Taking longer than usual (${duration})`,
    dialog_stuck_body_zigbee:
      "Is this a battery-powered device? It may need to be woken up first (for example by pressing a button on the device) before the update can actually start.",
    dialog_stuck_body_neutral: "This can still finish on its own. If you'd rather not wait, the rest of the queue can continue.",
    // Deliberately not called "Skip" -- that already exists and means
    // something else (stop suggesting this version). Doesn't cancel the
    // install, which may still finish on its own, it only stops this
    // entity from holding anything else back.
    dialog_stop_waiting: "Stop waiting",
    // Rollout-pacing (see rollout_manager.py): one Zigbee firmware install
    // at a time per network, not several at once (real radio traffic that
    // can destabilize the mesh). Only ever relevant once a second device
    // on the same Zigbee network is asked to install while one is already
    // in flight -- see _buildInstallingCard's own rolloutStatus handling.
    // Reused verbatim for the dialog's own Install button while an entity
    // is queued (not yet its turn): no override, direct user feedback,
    // the queue must stay authoritative, not something a hurried click can
    // jump. "...to finish" (not just the bare name) -- direct user
    // feedback, 2026-08-09: read ambiguously on its own.
    rollout_queue_waiting: (name) => `Waiting for ${name} to finish`,
    // Community-verdict fact rows (see _buildCommunitySection, and
    // aggregateVerdictText for how these four get picked), read-only slice
    // added 2026-07-22: https://github.com/HA-Update-Manager/community-votes.
    // Redesigned 2026-07-27, direct user feedback: rather than one sentence
    // that silently drops whichever count loses (problematic used to always
    // win, even when e.g. 2 people said healthy and only 1 said
    // problematic), "people"/"others" perspective + a "_mixed" variant show
    // both numbers whenever both exist.
    community_verdict_healthy: (count) =>
      `${count} ${count === 1 ? "person" : "people"} reported this jump as healthy.`,
    community_verdict_problematic: (count) =>
      `${count} ${count === 1 ? "person" : "people"} reported this jump as problematic.`,
    community_verdict_mixed: (healthyCount, problematicCount) =>
      `${healthyCount} reported this jump as healthy, ${problematicCount} as problematic.`,
    // "others" perspective: used instead of the three above whenever a
    // separate "You reported..." row (below) is already shown, so these
    // counts exclude your own vote instead of restating it.
    community_verdict_others_healthy: (count) =>
      `${count} ${count === 1 ? "other person" : "others"} reported this jump as healthy.`,
    community_verdict_others_problematic: (count) =>
      `${count} ${count === 1 ? "other person" : "others"} reported this jump as problematic.`,
    community_verdict_others_mixed: (healthyCount, problematicCount) =>
      `${healthyCount} ${healthyCount === 1 ? "other person" : "others"} reported this jump as healthy, ${problematicCount} as problematic.`,
    // Your own vote, shown as its own fact regardless of whether it agrees
    // with everyone else (direct user feedback, 2026-07-22: "I can't see
    // that I voted myself"; redesigned 2026-07-27 to always show, even when
    // your vote is the dissenting one -- it used to silently disappear from
    // the sentence entirely whenever it didn't match the leading direction,
    // see my_votes.py). The wider picture, if any, is the separate
    // aggregate row above/below this, not merged into this same sentence.
    community_verdict_you_healthy: "You reported this jump as healthy.",
    community_verdict_you_problematic: "You reported this jump as problematic.",
    // Count+pluralized, matching ha-config-section-updates.ts's own real
    // title_skipped/title_not_installable convention (confirmed against its
    // source: both are passed {count} and pluralize the same way
    // ui.card.updates.count_updates does) -- direct user feedback: "HA doet
    // '3 skipped updates' en '1 not installable update'. Waarom heb je deze
    // logica niet overgenomen?".
    group_skipped: (count) => `${count} ${count === 1 ? "skipped update" : "skipped updates"}`,
    group_not_installable: (count) => `${count} ${count === 1 ? "not installable update" : "not installable updates"}`,
    updates_empty: "No updates need attention, everything is up to date.",
    // Shown instead of updates_empty whenever there genuinely are updates
    // but every one of them is currently hidden by the overflow (⋮) menu's
    // own Show skipped/Show not installable toggles -- direct user
    // feedback: with both switched off, the tab used to render nothing at
    // all, no message, indistinguishable from an actual empty state.
    updates_hidden_by_filter: "Every update is currently hidden. Open the ⋮ menu to show skipped or not installable updates.",
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
    load_error_title: "Couldn't load Update Manager",
    // home-assistant-js-websocket's own ERR_CONNECTION_LOST case (see
    // WS_ERR_CONNECTION_LOST's own comment) -- a dropped connection, not a
    // genuine backend error, so this says so plainly and suggests the
    // actual fix instead of showing the raw, meaningless numeric code.
    load_error_connection_lost: "Connection to Home Assistant was lost. Reload the page once it's back.",
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
    // `time` is null whenever the target is exactly midnight (see
    // absoluteWhen's own comment) -- dropped instead of shown as "00:00",
    // which read as genuinely ambiguous (start or end of that day?).
    when_today: (time) => (time ? `Today ${time}` : "Today"),
    when_tomorrow: (time) => (time ? `Tomorrow ${time}` : "Tomorrow"),
    when_weekday: (weekday, time) => (time ? `${weekday} ${time}` : weekday),
    when_date: (date, time) => (time ? `${date}, ${time}` : date),
  },
  nl: {
    locale: "nl",
    tab_updates: "Updates",
    tab_history: "Historie",
    tab_settings: "Instellingen",
    refresh: "Vernieuwen",
    checking_updates_toast: "Bezig met controleren op updates…",
    refreshed_toast: "Update Manager ververst",
    update_all_started_toast: (count) => (count === 1 ? "1 update wordt geïnstalleerd…" : `${count} updates worden geïnstalleerd…`),
    menu_show_skipped_updates: "Overgeslagen updates tonen",
    menu_show_not_installable_updates: "Niet-installeerbare updates tonen",
    dash: "–",
    size_small_short: "Klein",
    size_small_desc: () => {
      const { year, month } = currentCalendarVersion();
      return `Een patch-release (bijv. 1.0.0 → 1.0.1), of dezelfde kalendermaand (bijv. ${year}.${month}.0 → ${year}.${month}.1).`;
    },
    size_medium_short: "Middel",
    size_medium_desc: () => {
      const { year, month, nextYear, nextMonth } = currentCalendarVersion();
      return (
        `Een minor-release (bijv. 1.0.0 → 1.1.0), een nieuwe kalendermaand/-jaar (bijv. ${year}.${month}.0 → ` +
        `${nextYear}.${nextMonth}.0), of een commit-update (bijv. 7sg82tw → 8dhw8wg).`
      );
    },
    size_large_short: "Groot",
    size_large_desc: () => "Een major-release (bijv. 1.0.0 → 2.0.0), of een sprong die niet te classificeren is.",
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
    field_wait_days_unit: "dagen",
    field_auto_install: "Automatisch updaten",
    auto_install_section_title: "Auto-update",
    auto_install_sizes_label: "Welke groottes installeer je automatisch?",
    field_trusted_voters: "Vertrouwde stemmers",
    field_trusted_voters_helper:
      "Een GitHub-gebruikersnaam die je meer vertrouwt dan je eigen regels. Hun probleemloze stem overrult je eigen regels hierboven en installeert die sprong meteen automatisch, ook als iemand anders 'm als problematisch meldde.",
    field_hide_postponed: "Uitgestelde updates verbergen",
    field_hide_postponed_helper: "Verbergt 'm uit Home Assistants eigen update-telling tot 'ie klaar is.",
    field_ready_days_add: "Dag toevoegen",
    field_ready_remove: (day) => `${day} verwijderen`,
    settings_schedule_hint: "Optioneel: laat een update alleen op specifieke dagen ready worden.",
    weekday_monday_short: "Maandag",
    weekday_tuesday_short: "Dinsdag",
    weekday_wednesday_short: "Woensdag",
    weekday_thursday_short: "Donderdag",
    weekday_friday_short: "Vrijdag",
    weekday_saturday_short: "Zaterdag",
    weekday_sunday_short: "Zondag",
    announce_hours_label: "Aankondigingstermijn",
    announce_hours_unit: "uur",
    announce_hours_helper: "Hoelang je nog hebt om een geplande automatische installatie te annuleren.",
    col_jump: "Sprong",
    dialog_announcement_label: "Aankondiging",
    dialog_current_version: "Geïnstalleerde versie",
    dialog_new_version: "Nieuwste versie",
    dialog_community_verdict_disclaimer:
      "Een verzamelde mening van andere gebruikers, geen garantie. Wees extra voorzichtig bij veiligheidsgevoelige apparaten (sloten, alarmen, rookmelders).",
    community_not_yet_rated: "Niemand heeft nog iets over deze sprong gemeld.",
    community_vote_link_prompt: "Koppel je GitHub-account in Instellingen om te stemmen.",
    community_trusted_vote_healthy: (names) =>
      `Vertrouwde stem: deze sprong is door ${names} als probleemloos beoordeeld.`,
    community_trusted_vote_problematic: (names) =>
      `Vertrouwde stem: deze sprong is door ${names} als problematisch beoordeeld.`,
    community_trusted_voter_label: "Vertrouwde stemmer",
    community_other_jumps_heading: "Andere sprongen naar deze versie",
    community_other_jump_line: (fromVersion, badgeTitle) => `Van ${fromVersion}: ${badgeTitle}`,
    community_problematic_reasons_heading: "Gerapporteerde redenen",
    community_report_toggle: "Meld een bekend probleem",
    community_report_intro:
      "Weet je al dat deze update problemen gaat geven, bijvoorbeeld via de release notes? Meld dat vast voordat je 'm installeert, zodat anderen gewaarschuwd zijn voordat ze zelf updaten.",
    community_vote_healthy: "Markeer als probleemloos",
    community_vote_problematic: "Meld als problematisch",
    community_vote_submit: "Versturen",
    community_vote_confirmed_healthy: (updated, ownRepoHealthyVote) => {
      if (ownRepoHealthyVote) {
        return "Gemarkeerd als probleemloos. Als maker telt dit niet mee voor de community-telling, maar toch bedankt!";
      }
      return updated ? "Stem gewijzigd naar probleemloos." : "Gemarkeerd als probleemloos. Bedankt dat je anderen hiermee helpt.";
    },
    community_vote_confirmed_problematic: (reason, updated) =>
      updated ? `Stem gewijzigd naar problematisch: ${reason}.` : `Gemeld: ${reason}. Bedankt voor de tip.`,
    community_vote_reason_required: "Kies eerst een reden.",
    vote_field_reason_category: "Reden",
    vote_field_notes: "Toelichting (optioneel)",
    vote_field_link: "Issue- of changelog-link (optioneel)",
    vote_reason_broken: "Functionaliteit kapot",
    vote_reason_requires_newer: "Vereist nieuwere HA-versie",
    vote_reason_dev_build: "Dev/pre-release-build",
    vote_reason_breaking_change: "Breaking change",
    vote_reason_other: "Anders",
    dialog_release_announcement: "Release-aankondiging openen",
    dialog_history_heading: "Geschiedenis",
    dialog_history_auto: "Automatisch geüpdatet",
    dialog_history_changelog: "Changelog bekijken",
    dialog_history_available_since: "Beschikbaar sinds",
    dialog_history_announced: "Aangekondigd",
    dialog_history_installed_at: "Geïnstalleerd",
    dialog_history_method_label: "Installatiemethode",
    dialog_history_method_manual: "Handmatig",
    dialog_history_method_rules: "Automatisch, je eigen regels",
    dialog_history_method_trusted: (names) => `Automatisch, vertrouwde stem van ${names}`,
    dialog_history_backup_label: "Back-up",
    dialog_history_backup_yes: "Gemaakt voor het installeren",
    dialog_history_backup_no: "Niet ondersteund door deze entiteit",
    dialog_release_notes_heading: "Release notes",
    dialog_upstream_release_notes: (repo) => `Eigen release notes van ${repo}:`,
    dialog_community_heading: "Community",
    list_and: "en",
    // Passive voice ("door X beoordeeld als"), not "X beoordeelde" -- avoids
    // needing separate singular/plural verb forms for a variable-length,
    // possibly multi-name subject.
    dialog_auto_install_held_back: (names) =>
      `Auto-installatie tegengehouden: deze sprong is door ${names} als problematisch beoordeeld.`,
    dialog_auto_install_held_back_community: (count) =>
      count === 1
        ? "Auto-installatie tegengehouden: 1 persoon heeft deze sprong als problematisch gerapporteerd."
        : `Auto-installatie tegengehouden: ${count} mensen hebben deze sprong als problematisch gerapporteerd.`,
    dialog_more_info: "Meer info",
    paused_banner: "Update Manager staat gepauzeerd. Niets hieronder wordt automatisch geüpdatet, aangekondigd of verborgen.",
    community_section_title: "Help anderen",
    community_section_desc:
      "Word onderdeel van de community: koppel je GitHub-account om te stemmen of een update probleemloos of problematisch bleek.",
    community_link: "GitHub-account koppelen",
    community_unlink: "Ontkoppelen",
    community_linked_as: (username) => `Gekoppeld als @${username}`,
    community_link_instructions: "Ga naar onderstaande pagina en voer deze code in:",
    community_link_waiting: "Wachten tot je akkoord geeft op GitHub...",
    community_link_timed_out: "De koppelcode is verlopen voordat 'm werd goedgekeurd, probeer het opnieuw.",
    community_link_failed: "Koppelen is mislukt of geweigerd, probeer het opnieuw.",
    enabled_section_title: "Algemeen",
    field_enabled: "Update Manager",
    field_enabled_helper:
      "Pauzeert alle automatische acties hieronder: geen aankondigingen, geen automatische installaties, en uitgestelde updates worden niet langer verborgen voor Home Assistants eigen update-telling. Alles wat je hebt ingesteld blijft opgeslagen, het wordt alleen niet toegepast totdat je dit weer aanzet.",
    sizes_section_title: "Update-groottes",
    sizes_intro_lead: "Elke update valt in een van deze drie groottes, op basis van hoe groot de versiesprong is.",
    settings_header: "Uitstel",
    settings_hint:
      "Uitstellen loont: het geeft een release met een fout de tijd om opgemerkt en gerepareerd te " +
      "worden voordat jij 'm installeert.",
    postponement_sizes_label: "Hoelang wil je uitstellen?",
    save: "Opslaan",
    settings_saved_toast: "Instellingen opgeslagen",
    cancel_auto_install: "Annuleren",
    dialog_force_ready: "Klaar",
    dialog_open_update: "Update openen",
    dialog_skip: "Overslaan",
    dialog_unskip: "Overslaan ongedaan maken",
    group_ready: "Klaar om te updaten",
    group_waiting: "Uitgesteld",
    group_blocked: "Afgeraden",
    update_all: "Alles updaten",
    installing_section_title: "Bezig met installeren",
    tier_waiting_text: "Wacht tot andere updates eerst klaar zijn",
    stuck_waiting_text: (duration) => `Installeert al ${duration}, langer dan gebruikelijk`,
    duration_hours_minutes: (hours, minutes) => `${hours}u ${minutes}m`,
    duration_minutes: (minutes) => `${minutes}m`,
    dialog_stuck_title: (duration) => `Duurt langer dan gebruikelijk (${duration})`,
    dialog_stuck_body_zigbee:
      "Is dit een batterij-gevoed apparaat? Dan moet het misschien eerst wakker gemaakt worden (bijvoorbeeld door op een knopje op het apparaat te drukken) voordat de update daadwerkelijk kan starten.",
    dialog_stuck_body_neutral: "Dit kan nog gewoon goedkomen. Wil je niet langer wachten, dan gaat de rest van de wachtrij verder.",
    dialog_stop_waiting: "Stop met wachten",
    rollout_queue_waiting: (name) => `Wacht tot ${name} klaar is`,
    community_verdict_healthy: (count) =>
      `${count} ${count === 1 ? "persoon meldt" : "mensen melden"} deze sprong als probleemloos.`,
    community_verdict_problematic: (count) =>
      `${count} ${count === 1 ? "persoon meldt" : "mensen melden"} deze sprong als problematisch.`,
    community_verdict_mixed: (healthyCount, problematicCount) =>
      `${healthyCount} ${healthyCount === 1 ? "persoon meldt" : "mensen melden"} deze sprong als probleemloos, ${problematicCount} als problematisch.`,
    community_verdict_others_healthy: (count) =>
      `${count} ${count === 1 ? "andere persoon meldt" : "anderen melden"} deze sprong als probleemloos.`,
    community_verdict_others_problematic: (count) =>
      `${count} ${count === 1 ? "andere persoon meldt" : "anderen melden"} deze sprong als problematisch.`,
    community_verdict_others_mixed: (healthyCount, problematicCount) =>
      `${healthyCount} ${healthyCount === 1 ? "andere persoon meldt" : "anderen melden"} deze sprong als probleemloos, ${problematicCount} als problematisch.`,
    community_verdict_you_healthy: "Jij meldde deze sprong als probleemloos.",
    community_verdict_you_problematic: "Jij meldde deze sprong als problematisch.",
    group_skipped: (count) => `${count} ${count === 1 ? "overgeslagen update" : "overgeslagen updates"}`,
    group_not_installable: (count) =>
      `${count} ${count === 1 ? "niet installeerbare update" : "niet installeerbare updates"}`,
    updates_empty: "Geen updates die aandacht nodig hebben, alles is up-to-date.",
    updates_hidden_by_filter: "Alle updates zijn nu verborgen. Open het ⋮-menu om overgeslagen of niet-installeerbare updates te tonen.",
    history_empty: "Nog geen updates gelogd.",
    history_section_today: "Vandaag",
    history_section_yesterday: "Gisteren",
    history_section_this_week: "Deze week",
    history_section_this_month: "Deze maand",
    history_section_earlier: "Eerder",
    loading: "Laden…",
    load_error_title: "Kon Update Manager niet laden",
    load_error_connection_lost: "Verbinding met Home Assistant is verbroken. Herlaad de pagina zodra die terug is.",
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
    when_today: (time) => (time ? `vandaag ${time}` : "vandaag"),
    when_tomorrow: (time) => (time ? `morgen ${time}` : "morgen"),
    when_weekday: (weekday, time) => (time ? `${weekday} ${time}` : weekday),
    when_date: (date, time) => (time ? `${date}, ${time}` : date),
  },
};
