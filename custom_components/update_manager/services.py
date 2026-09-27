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
"""
from __future__ import annotations

import voluptuous as vol
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import ATTR_TO_VERSION, DOMAIN, SERVICE_CANCEL_SCHEDULED_INSTALL, SERVICE_GET_RELEASE_NOTES
from .runtime_data import UpdateManagerData
from .runtime_data import get_data as _get_data
from .websocket_api import async_fetch_github_release_notes

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

    async def _async_get_release_notes(call: ServiceCall) -> ServiceResponse:
        data = _data_or_raise()
        entity_id = call.data[ATTR_ENTITY_ID]
        cached = _cached_or_raise(data, entity_id)
        # Defaults to the entity's own current latest_version, not a
        # required field -- see const.py's own ATTR_TO_VERSION comment for
        # why.
        to_version = call.data.get(ATTR_TO_VERSION) or cached["latest_version"]
        access_token = await data.github_auth_manager.async_get_valid_access_token()
        # Exactly the same call, with the exact same installed_version ->
        # latest_version range, the update-detail dialog's own
        # release-notes fallback already makes (see
        # update-manager-panel.js's own _fetchGithubReleaseNotesFallback
        # callers) -- an automation gets the identical, already-compiled
        # text a person would see there, not a separately-maintained copy
        # of that logic.
        result = await async_fetch_github_release_notes(
            hass, cached.get("release_url"), access_token, cached.get("installed_version"), to_version
        )
        if result is None:
            return {"notes": None, "owner": None, "repo": None, "release_url": cached.get("release_url")}
        owner, repo, notes, corrected_url = result
        return {
            "notes": notes,
            "owner": owner,
            "repo": repo,
            # corrected_url is only ever set once a to_version match
            # actually corrected it (see async_fetch_github_release_notes'
            # own docstring) -- cached's own release_url otherwise, same
            # fallback the panel's own linkUrl already uses.
            "release_url": corrected_url or cached.get("release_url"),
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
