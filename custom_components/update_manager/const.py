DOMAIN = "update_manager"

# Fired on hass.bus, domain-prefixed event_types (same convention as
# ha-parcel-integrations' own event contract, checked directly against
# https://ha-parcel-integrations.github.io/contract/#events while designing
# this): one event per genuine, discrete lifecycle moment an automation
# could reasonably want to react to, not a general "something changed"
# firehose. Deliberately no overlapping/duplicate events for the same fact
# -- an install either failed or succeeded, never both, so there's no
# EVENT_INSTALL_FAILED *and* a generic EVENT_STATUS_CHANGED also firing for
# the same transition. Per-status counts/membership (which updates are
# Ready/Postponed/etc. right now) are already covered by sensor.py's own 5
# status sensors and their attributes -- these events are only for the
# moments in between: a countdown starting, an install actually landing, or
# failing.
EVENT_ANNOUNCED = f"{DOMAIN}_announced"
EVENT_INSTALLED = f"{DOMAIN}_installed"
EVENT_INSTALL_FAILED = f"{DOMAIN}_install_failed"

# The master switch (default on): pauses every autonomous action Update
# Manager itself takes -- auto-install (announcing/executing) and the
# hide-postponed auto-skip -- without touching any of the other settings
# that decide *what* would happen once unpaused. Not part of any profile
# preset, same reasoning as CONF_EXCLUDED_ENTITIES/CONF_HIDE_POSTPONED: a
# behavior toggle, not a wait/auto-install tuning value.
CONF_ENABLED = "enabled"

CONF_SMALL_WAIT_DAYS = "small_wait_days"
CONF_SMALL_AUTO_INSTALL = "small_auto_install"
CONF_MEDIUM_WAIT_DAYS = "medium_wait_days"
CONF_MEDIUM_AUTO_INSTALL = "medium_auto_install"
CONF_LARGE_WAIT_DAYS = "large_wait_days"
CONF_LARGE_AUTO_INSTALL = "large_auto_install"

# Two independent settings per size (small/medium/large, see semver.py), not
# three mutually exclusive choices: how long to wait (a traffic light, not
# a judgment call), and whether Update
# Manager presses install itself once that wait elapses, or you do. An
# earlier "always needs a manual look" third option, and a separate
# "unknown version type" category, were both removed the same day: neither
# was really about judging anything, and semver.py's own size
# classification already folds "we can't confidently place this" into
# "large" -- a conservative default wait covers it, no separate settings
# category needed.
CONF_ANNOUNCE_HOURS = "announce_hours"
DEFAULT_ANNOUNCE_HOURS = 24

# User-picked, on top of coordinator.py's own hard, non-configurable
# Core/Supervisor/HAOS exclusion -- entities here are still shown normally
# in Updates/History (a real size/status, real history), install_manager.py
# just never auto-installs them, same as the hard exclusion. A plain list of
# entity_ids, not part of any profile preset: this is a per-instance choice
# about *which* entities, not a wait/auto-install tuning value.
CONF_EXCLUDED_ENTITIES = "excluded_entities"

# On by default (changed 2026-07-21, direct user feedback), opt-out rather
# than opt-in. Not part of any profile preset (same reasoning as
# CONF_EXCLUDED_ENTITIES above: a behavior toggle, not a wait/auto-install
# tuning value). See staging_skip.py for what it actually does.
CONF_HIDE_POSTPONED = "hide_postponed"

# Purely a display filter for the panel's own Updates tab, unlike
# CONF_HIDE_POSTPONED above: neither of these touches Home Assistant's own
# update state/count or any staging rule, they only decide whether the
# panel's own "Skipped"/"Not installable" groups get shown at all -- no
# Python code anywhere else ever reads them, both are read/written by the
# panel JS alone (see update-manager-panel.js's own groupUpdates). Mirrors
# Home Assistant's own native /config/system/updates page (ha-config-
# section-updates.ts's own "Show skipped updates" overflow-menu item),
# deliberately following the same pattern/interaction/placement HA itself
# uses, as two independent toggles rather than HA's own single shared one,
# and saved (unlike HA's own page, whose own toggle resets on every visit)
# so the choice sticks across sessions.
# Default True (shown) for both: matches what every existing install
# already sees today, so nothing changes for anyone until they actually
# open the panel's own Updates-tab menu and turn one off.
CONF_SHOW_SKIPPED_UPDATES = "show_skipped_updates"
CONF_SHOW_NOT_INSTALLABLE_UPDATES = "show_not_installable_updates"

# A plain list of GitHub usernames, empty by default: lets someone say they
# trust a specific person's judgment more than their own general wait/
# auto-install rules for a given jump, not part of any profile preset, same
# reasoning as
# CONF_EXCLUDED_ENTITIES: a per-instance choice about *who*, not a
# wait/auto-install tuning value. Direct user feedback, 2026-07-23: a list,
# not a single username -- more than one person's judgement can be trusted
# at once. See announcer.py's own effective_auto_install_state for how
# disagreement among them is resolved.
CONF_TRUSTED_VOTERS = "trusted_voters"

# The wait/auto-install values a freshly-created config entry (options == {})
# reads as, before anyone's ever opened the Settings tab and saved anything
# of their own -- not a distinct, still-selectable "profile": this used to
# be one of three (conservative/balanced/free), but the picker itself was
# removed from the panel a while back, leaving only this one set of numbers
# actually read anywhere (rules_from_options' own fallback, and the
# Settings tab's own pre-fill for a not-yet-saved field). Found live,
# 2026-07-27, direct user feedback: there were no profiles left to preset
# for -- the old conservative/free presets and the "profile" vocabulary
# around them were dead code, not a real, current feature.
#
# auto_install defaults to False everywhere: auto-install is a large enough
# step up in consequence (Update Manager actually calling update.install)
# that it should never switch on silently; a user has to opt in per size
# by hand.
DEFAULT_WAIT_DAYS: dict[str, int | bool] = {
    CONF_SMALL_WAIT_DAYS: 1,
    CONF_SMALL_AUTO_INSTALL: False,
    CONF_MEDIUM_WAIT_DAYS: 3,
    CONF_MEDIUM_AUTO_INSTALL: False,
    CONF_LARGE_WAIT_DAYS: 7,
    CONF_LARGE_AUTO_INSTALL: False,
    CONF_ANNOUNCE_HOURS: DEFAULT_ANNOUNCE_HOURS,
}
