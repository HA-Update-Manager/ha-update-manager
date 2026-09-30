"""Real Home Assistant services (Developer Tools > Actions), not just the
websocket commands the panel itself calls -- see const.py's own
SERVICE_GET_RELEASE_NOTES/SERVICE_CANCEL_SCHEDULED_INSTALL comment for why
these exist at all: they let an automation react to EVENT_ANNOUNCED on its
own (e.g. feeding the release notes to a locally-run LLM) without needing
this project's own panel involved at all.

Both take a single entity_id, not a target selector matching several --
unlike the update.* entities' own services, these operate on Update
Manager's own per-entity bookkeeping for one specific entity at a time, and
get_release_notes' own response is inherently single-entity shaped (one set
of notes), so there's no sensible multi-entity behavior to define.

get_release_notes is built to return exactly what the update-detail
dialog's own Release notes section shows, not an approximation of it --
direct user feedback, 2026-09-29 ("het moet exact gelijk zijn aan wat we
tonen, want daar hebben we veel werk en optimalisaties in zitten"), after
two earlier passes each still missed a real piece of the dialog's own
pipeline. Mirrors every step, in the same order:
  1. Native entity notes if it supports UpdateEntityFeature.RELEASE_NOTES,
     else its plain release_summary attribute (_fetchNativeReleaseNotes/
     the dialog's own supportsReleaseNotes branch).
  2. Falls back to the GitHub-compiled range whenever step 1 has nothing
     (async_fetch_github_release_notes, already shared with
     websocket_api.py's own dialog-facing handler).
  3. Trims whichever of the two actually produced something down to just
     this jump (changelog_trim.py, a port of _trimChangelogToVersion).
  4. Chases exactly one embedded external upstream release reference, if
     any (embedded_upstream_release.py, a port of
     _findEmbeddedUpstreamRelease/_appendUpstreamReleaseNotes -- an add-on
     whose own notes are just a one-line "bumped to X" pointing at a real
     upstream project like Zigbee2MQTT or Mealie).
  5. Decorates the result (release_notes_decoration.py, a port of
     _decorateReleaseNotes: linkifies #1234/@username references, expands
     :shortcode: emoji), each section decorated against its own repo.
  6. For Home Assistant Core specifically, resolves the real blog
     announcement link (async_fetch_core_announcement, already shared with
     websocket_api.py's own dialog-facing handler) in place of the plain
     GitHub releases tag link, same as withCoreAnnouncement.
An automation gets the identical text (and link) a person would see there,
not a separately-maintained approximation of it.
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components.update import DATA_COMPONENT, UpdateEntityFeature
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .changelog_trim import trim_changelog_to_version
from .const import ATTR_TO_VERSION, DOMAIN, SERVICE_CANCEL_SCHEDULED_INSTALL, SERVICE_GET_RELEASE_NOTES
from .coordinator import home_assistant_component_for_entity
from .embedded_upstream_release import find_embedded_upstream_release
from .github_release_notes import parse_release_url
from .release_notes_decoration import decorate_release_notes
from .runtime_data import UpdateManagerData
from .runtime_data import get_data as _get_data
from .websocket_api import async_fetch_core_announcement, async_fetch_github_release_notes

_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Optional(ATTR_TO_VERSION): str,
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Idempotent, same guard other single-instance setup helpers in this
    project already use -- harmless if async_setup_entry ever runs more
    than once for this integration's own lifetime (a reload does not
    re-run this module's import, so re-registering the exact same service
    callback again would otherwise be silently redundant, not broken, but
    there's no reason to)."""
    if hass.services.has_service(DOMAIN, SERVICE_GET_RELEASE_NOTES):
        return

    def _data_or_raise() -> UpdateManagerData:
        data = _get_data(hass)
        if not data:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_set_up")
        return data

    def _cached_or_raise(data: UpdateManagerData, entity_id: str) -> dict:
        """coordinator.cache's own entry for entity_id -- the same one the
        panel itself reads installed_version/latest_version/release_url
        from. Missing for anything that isn't a currently tracked update
        entity (a typo, an excluded entity, or one from another domain
        entirely)."""
        cached = data.coordinator.cache.get(entity_id)
        if cached is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_update_entity",
                translation_placeholders={"entity_id": entity_id},
            )
        return cached

    async def _async_main_notes(entity_id: str) -> str | None:
        """Mirrors update-manager-panel.js's own supportsReleaseNotes
        branch exactly: an entity that declares UpdateEntityFeature.
        RELEASE_NOTES generates notes on demand (fetched here straight off
        the entity itself -- homeassistant/components/update/__init__.py's
        own websocket_release_notes, called directly instead of through a
        websocket round-trip to ourselves); one that doesn't just exposes
        a plain release_summary attribute instead. Checked off the
        entity's own *state* attribute (matching how every other feature
        check in this project already reads supported_features, and
        exactly what the dialog itself branches on), not the live entity
        object's own property -- the two should always agree, but the
        state is what the dialog's own branching decision is actually
        keyed off.

        Neither is guaranteed to actually have anything (confirmed live:
        HACS's own async_release_notes() returns None whenever
        pending_restart is still true, or the installed version isn't in
        its own published_tags; Home Assistant Supervisor's update entity
        supports neither at all), so the caller falls back to the
        GitHub-compiled range whenever this comes back empty either way.
        Found live, 2026-09-27: skipping the RELEASE_NOTES branch entirely
        returned nothing at all for a Supervisor add-on, which (like every
        add-on) never sets release_url either, so the GitHub-only fallback
        had nothing to work with even though the entity's own real release
        notes were right there."""
        state = hass.states.get(entity_id)
        supports_release_notes = bool(state) and bool(
            (state.attributes.get("supported_features") or 0) & UpdateEntityFeature.RELEASE_NOTES
        )
        if not supports_release_notes:
            return state.attributes.get("release_summary") if state else None
        entity = hass.data.get(DATA_COMPONENT)
        entity = entity.get_entity(entity_id) if entity else None
        if entity is None or entity.available is False:
            return None
        try:
            return await entity.async_release_notes()
        # Third-party entity code (whatever integration provides
        # update.<x>) -- never let it crash this service, same "don't let
        # this crash the service" reasoning update-manager-panel.js's own
        # try/except already applies to the exact same call.
        except Exception:  # noqa: BLE001
            return None

    async def _async_with_upstream_addendum(
        notes: str | None,
        own_owner: str | None,
        own_repo: str | None,
        from_version: str | None,
        to_version: str | None,
        access_token: str | None,
    ) -> str | None:
        """Mirrors update-manager-panel.js's own _appendUpstreamReleaseNotes:
        looks for exactly one embedded external GitHub release reference
        in `notes` (already trimmed to this jump by the caller, same order
        the dialog itself scans in, and not yet decorated -- matching the
        dialog's own undecorated `notes`/`finalNotes` variable at that
        point), and appends its own notes, labeled and decorated against
        its own repo, when found. Never raises, never removes anything --
        same "nothing to add" graceful no-op as every other release-notes
        enrichment in this project, returns `notes` completely unchanged
        on any failure (no link found, ambiguous, unfetchable, or
        empty)."""
        if not notes:
            return notes
        found = find_embedded_upstream_release(notes, own_owner, own_repo, from_version)
        if found is None:
            return notes
        tag = found.tag or to_version
        if not tag:
            return notes
        upstream_url = f"https://github.com/{found.owner}/{found.repo}/releases/tag/{tag}"
        # No from_version/to_version here -- a single release's own body,
        # never a compiled range, same as the dialog's own call.
        result = await async_fetch_github_release_notes(hass, upstream_url, access_token, None, None)
        if result is None:
            return notes
        _owner, _repo, upstream_notes, _corrected_url = result
        if not upstream_notes:
            return notes
        upstream_notes = decorate_release_notes(upstream_notes, found.owner, found.repo)
        return f"{notes}\n\n---\n\n**{found.owner}/{found.repo}'s own release notes:**\n\n{upstream_notes}"

    async def _async_get_release_notes(call: ServiceCall) -> ServiceResponse:
        data = _data_or_raise()
        entity_id = call.data[ATTR_ENTITY_ID]
        cached = _cached_or_raise(data, entity_id)
        release_url = cached.get("release_url")
        from_version = cached.get("installed_version")
        # Defaults to the entity's own current latest_version, not a
        # required field -- see const.py's own ATTR_TO_VERSION comment for
        # why.
        to_version = call.data.get(ATTR_TO_VERSION) or cached["latest_version"]
        # Used for decoration (both here and in the upstream addendum) --
        # always this entity's own base, cached release_url, never a
        # GitHub-fallback's own corrected_url, exactly what the dialog's
        # own _decorateReleaseNotes(notes, releaseUrl) call does too (it
        # reads the same outer-scope, uncorrected releaseUrl regardless of
        # which of the three sources actually produced the notes).
        own = parse_release_url(release_url)
        own_owner, own_repo = (own[0], own[1]) if own else (None, None)
        # Needed by both the GitHub-compiled fallback below and the
        # upstream-release chase, so fetched once regardless of which path
        # actually ends up using it.
        access_token = await data.github_auth_manager.async_get_valid_access_token()

        owner: str | None = None
        repo: str | None = None
        corrected_url: str | None = None
        main_notes = await _async_main_notes(entity_id)
        if main_notes:
            notes = main_notes
        else:
            # Exactly the same call, with the exact same installed_version
            # -> latest_version range, the update-detail dialog's own
            # release-notes fallback already makes (see
            # update-manager-panel.js's own _fetchGithubReleaseNotesFallback
            # callers) -- an automation gets the identical, already-compiled
            # text a person would see there, not a separately-maintained
            # copy of that logic.
            result = await async_fetch_github_release_notes(hass, release_url, access_token, from_version, to_version)
            notes, owner, repo, corrected_url = (None, None, None, None) if result is None else result

        # Trim -> chase an embedded upstream release -> decorate, same
        # order and same "operates on the undecorated, already-trimmed
        # text" reasoning as the dialog's own pipeline -- see each
        # function's own docstring.
        notes = trim_changelog_to_version(notes, from_version, to_version)
        notes = await _async_with_upstream_addendum(notes, own_owner, own_repo, from_version, to_version, access_token)
        notes = decorate_release_notes(notes, own_owner, own_repo)

        # For Home Assistant Core specifically, the real blog announcement
        # link takes over from the plain GitHub releases tag link, same as
        # withCoreAnnouncement -- home_assistant_component_for_entity, not
        # a hardcoded entity_id, so this still matches on an instance whose
        # registry is still carrying an older unique_id/entity_id scheme
        # (see that function's own drift comment). Keyed on this entity's
        # own current latest_version, not `to_version` -- the dialog's own
        # call does the exact same thing, even when a caller here asks
        # about a specific, different to_version explicitly.
        final_release_url = corrected_url or release_url
        if home_assistant_component_for_entity(hass, entity_id) == "core":
            announcement = await async_fetch_core_announcement(hass, cached["latest_version"])
            if announcement and announcement.get("url"):
                final_release_url = announcement["url"]

        return {
            "notes": notes,
            "owner": owner,
            "repo": repo,
            "release_url": final_release_url,
            "from_version": from_version,
            "to_version": to_version,
        }

    async def _async_cancel_scheduled_install(call: ServiceCall) -> None:
        data = _data_or_raise()
        entity_id = call.data[ATTR_ENTITY_ID]
        to_version = call.data.get(ATTR_TO_VERSION)
        if to_version is None:
            to_version = _cached_or_raise(data, entity_id)["latest_version"]
        await data.install_manager.async_cancel(entity_id, to_version)

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_RELEASE_NOTES,
        _async_get_release_notes,
        schema=_SERVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CANCEL_SCHEDULED_INSTALL, _async_cancel_scheduled_install, schema=_SERVICE_SCHEMA
    )
