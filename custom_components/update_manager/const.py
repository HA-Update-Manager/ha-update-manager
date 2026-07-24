DOMAIN = "update_manager"

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
CONF_BIG_WAIT_DAYS = "big_wait_days"
CONF_BIG_AUTO_INSTALL = "big_auto_install"

# Two independent settings per size (small/medium/big, see semver.py), not
# three mutually exclusive choices: how long to wait (a traffic light, not
# a judgment call, see FUTURE.md's 2026-07-16 note), and whether Update
# Manager presses install itself once that wait elapses, or you do. An
# earlier "always needs a manual look" third option, and a separate
# "unknown version type" category, were both removed the same day: neither
# was really about judging anything, and semver.py's own size
# classification already folds "we can't confidently place this" into
# "big" -- a conservative default wait covers it, no separate settings
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

PROFILE_CONSERVATIVE = "conservative"
PROFILE_BALANCED = "balanced"
PROFILE_FREE = "free"

# A profile only pre-fills the detailed fields below it -- it never hides
# them (decided 2026-07-15, see FUTURE.md). "custom" means "keep whatever
# is already configured (or the balanced defaults, the first time)" rather
# than a distinct set of values of its own.
#
# Every profile defaults auto_install to False everywhere: auto-install is
# a large enough step up in consequence (Update Manager actually calling
# update.install) that no profile should switch it on silently; a user has
# to opt in per size by hand (see FUTURE.md's auto-install design note,
# 2026-07-15).
PROFILE_PRESETS: dict[str, dict[str, int | bool]] = {
    PROFILE_CONSERVATIVE: {
        CONF_SMALL_WAIT_DAYS: 3,
        CONF_SMALL_AUTO_INSTALL: False,
        CONF_MEDIUM_WAIT_DAYS: 14,
        CONF_MEDIUM_AUTO_INSTALL: False,
        CONF_BIG_WAIT_DAYS: 60,
        CONF_BIG_AUTO_INSTALL: False,
        CONF_ANNOUNCE_HOURS: DEFAULT_ANNOUNCE_HOURS,
    },
    PROFILE_BALANCED: {
        CONF_SMALL_WAIT_DAYS: 0,
        CONF_SMALL_AUTO_INSTALL: False,
        CONF_MEDIUM_WAIT_DAYS: 1,
        CONF_MEDIUM_AUTO_INSTALL: False,
        CONF_BIG_WAIT_DAYS: 3,
        CONF_BIG_AUTO_INSTALL: False,
        CONF_ANNOUNCE_HOURS: DEFAULT_ANNOUNCE_HOURS,
    },
    PROFILE_FREE: {
        CONF_SMALL_WAIT_DAYS: 0,
        CONF_SMALL_AUTO_INSTALL: False,
        CONF_MEDIUM_WAIT_DAYS: 0,
        CONF_MEDIUM_AUTO_INSTALL: False,
        CONF_BIG_WAIT_DAYS: 30,
        CONF_BIG_AUTO_INSTALL: False,
        CONF_ANNOUNCE_HOURS: DEFAULT_ANNOUNCE_HOURS,
    },
}
