DOMAIN = "update_manager"

CONF_PROFILE = "profile"
CONF_PATCH_WAIT_DAYS = "patch_wait_days"
CONF_PATCH_BLOCKED = "patch_blocked"
CONF_MINOR_WAIT_DAYS = "minor_wait_days"
CONF_MINOR_BLOCKED = "minor_blocked"
CONF_MAJOR_WAIT_DAYS = "major_wait_days"
CONF_MAJOR_BLOCKED = "major_blocked"
CONF_UNKNOWN_WAIT_DAYS = "unknown_wait_days"
CONF_UNKNOWN_BLOCKED = "unknown_blocked"

PROFILE_CONSERVATIVE = "conservative"
PROFILE_BALANCED = "balanced"
PROFILE_FREE = "free"
PROFILE_CUSTOM = "custom"

# A profile only pre-fills the detailed fields below it -- it never hides
# them (decided 2026-07-15, see FUTURE.md). "custom" means "keep whatever
# is already configured (or the balanced defaults, the first time)" rather
# than a distinct set of values of its own.
PROFILE_PRESETS: dict[str, dict[str, int | bool]] = {
    PROFILE_CONSERVATIVE: {
        CONF_PATCH_WAIT_DAYS: 3,
        CONF_PATCH_BLOCKED: False,
        CONF_MINOR_WAIT_DAYS: 14,
        CONF_MINOR_BLOCKED: False,
        CONF_MAJOR_WAIT_DAYS: 0,
        CONF_MAJOR_BLOCKED: True,
        CONF_UNKNOWN_WAIT_DAYS: 0,
        CONF_UNKNOWN_BLOCKED: True,
    },
    PROFILE_BALANCED: {
        CONF_PATCH_WAIT_DAYS: 0,
        CONF_PATCH_BLOCKED: False,
        CONF_MINOR_WAIT_DAYS: 7,
        CONF_MINOR_BLOCKED: False,
        CONF_MAJOR_WAIT_DAYS: 0,
        CONF_MAJOR_BLOCKED: True,
        CONF_UNKNOWN_WAIT_DAYS: 0,
        CONF_UNKNOWN_BLOCKED: True,
    },
    PROFILE_FREE: {
        CONF_PATCH_WAIT_DAYS: 0,
        CONF_PATCH_BLOCKED: False,
        CONF_MINOR_WAIT_DAYS: 0,
        CONF_MINOR_BLOCKED: False,
        CONF_MAJOR_WAIT_DAYS: 30,
        CONF_MAJOR_BLOCKED: False,
        # Deliberate judgment call, not explicitly discussed: "unknown"
        # stays blocked even under the otherwise-permissive "free" profile,
        # since it means "we can't even parse the version", not "a big
        # jump" -- there's no real risk level to weigh, just a missing
        # signal. Still fully editable by hand if someone disagrees.
        CONF_UNKNOWN_WAIT_DAYS: 0,
        CONF_UNKNOWN_BLOCKED: True,
    },
}
