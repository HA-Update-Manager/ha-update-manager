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
# a judgment call, see FUTURE.md's 2026-07-16 note), and whether Update
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
# in Updates/Historie (a real size/status, real history), install_manager.py
# just never auto-installs them, same as the hard exclusion. A plain list of
# entity_ids, not part of any profile preset: this is a per-instance choice
# about *which* entities, not a wait/auto-install tuning value.
CONF_EXCLUDED_ENTITIES = "excluded_entities"

# On by default (changed 2026-07-21, direct user feedback), opt-out rather
# than opt-in. Not part of any profile preset (same reasoning as
# CONF_EXCLUDED_ENTITIES above: a behavior toggle, not a wait/auto-install
# tuning value). See staging_skip.py for what it actually does.
CONF_HIDE_POSTPONED = "hide_postponed"

# A plain list of GitHub usernames, empty by default -- "I trust @someone's
# judgement more than my own rules" (see FUTURE.md's "vertrouwenspersoon"
# note), not part of any profile preset, same reasoning as
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
# 2026-07-27, direct user feedback: "we hebben helemaal geen profiles meer"
# -- the old conservative/free presets and the "profile" vocabulary around
# them were dead code, not a real, current feature.
#
# auto_install defaults to False everywhere: auto-install is a large enough
# step up in consequence (Update Manager actually calling update.install)
# that it should never switch on silently; a user has to opt in per size
# by hand (see FUTURE.md's auto-install design note, 2026-07-15).
DEFAULT_WAIT_DAYS: dict[str, int | bool] = {
    CONF_SMALL_WAIT_DAYS: 1,
    CONF_SMALL_AUTO_INSTALL: False,
    CONF_MEDIUM_WAIT_DAYS: 3,
    CONF_MEDIUM_AUTO_INSTALL: False,
    CONF_LARGE_WAIT_DAYS: 7,
    CONF_LARGE_AUTO_INSTALL: False,
    CONF_ANNOUNCE_HOURS: DEFAULT_ANNOUNCE_HOURS,
}
