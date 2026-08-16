"""Links a GitHub account via OAuth Device Flow, so the voting feature
(community_vote.py) can submit a vote as that real, identifiable account,
with no fork, no App installation, and no client secret needed anywhere
(confirmed via a live test against the community-votes repo).

Device Flow was chosen specifically because it needs no client secret at
all, unlike the ordinary OAuth redirect flow: an integration that runs
entirely inside the user's own HA instance (a "public client" in OAuth
terms) can't hold a secret safely, and GitHub's own docs recommend Device
Flow for exactly this situation (CLI tools, headless apps). That property
holds for the whole token lifecycle, not just the initial link: refreshing
a device-flow-issued token also needs no client secret (verified against
GitHub's current docs, not guessed).

Token lifetimes (also verified, not guessed): the access token expires
after 8 hours, the refresh token after 6 months. Refreshing uses the exact
same /login/oauth/access_token endpoint as the initial device-flow poll,
just a different grant_type, and **rotates** both tokens on every refresh:
the old access+refresh pair stops working the instant a refresh succeeds,
so only ever the newest pair may be kept.

Read-only linking only. Submitting a vote itself is a separate, later
feature; this module's only job is producing a valid access token on
demand for that future feature to use.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Literal

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_github_auth"

# Repair issue raised the moment the link becomes unusable in a way only a
# fresh device-flow re-link (not a plain retry) can fix -- see
# _async_create_link_expired_issue's own docstring for exactly which two
# failure modes count. Not raised for a plain network hiccup on the refresh
# call itself, that's the existing debug-log-and-retry-next-time path,
# unchanged (quality_scale.yaml's own reauthentication-flow/repair-issues
# entries, closed 2026-07-27: no reauth flow fits here, this integration's
# own config_flow collects no credential at all for HA's reauth mechanism
# to re-run, this is the real, proportionate fix for the actual gap that
# rule was pointing at).
_ISSUE_LINK_EXPIRED = "github_link_expired"


def _async_create_link_expired_issue(hass: HomeAssistant) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        _ISSUE_LINK_EXPIRED,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=_ISSUE_LINK_EXPIRED,
    )


def _async_clear_link_expired_issue(hass: HomeAssistant) -> None:
    ir.async_delete_issue(hass, DOMAIN, _ISSUE_LINK_EXPIRED)

# Public value, safe to commit: Device Flow's whole design relies on this
# being the case (a public client can't hold a secret safely, so GitHub
# never asks Device Flow apps for one). Registered under the HA-Update-
# Manager org, "Issues: write" only, installed on community-votes.
GITHUB_APP_CLIENT_ID = "Iv23liezHv9WgSn8uz2G"

_DEVICE_CODE_URL = "https://github.com/login/device/code"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_USER_URL = "https://api.github.com/user"

# A little slack before the token's own real expiry, so a call already in
# flight doesn't get a token that expires mid-request.
_EXPIRY_SAFETY_MARGIN = timedelta(minutes=2)

LinkStatus = Literal["idle", "pending", "linked", "failed", "expired"]


def _expiry_fields(payload: dict[str, Any], now: datetime) -> dict[str, str]:
    """access_token_expires_at/refresh_token_expires_at from a token
    response's own expires_in/refresh_token_expires_in, shared by
    _async_store_tokens and async_get_valid_access_token's own refresh path
    (found by review: both computed this identically)."""
    return {
        "access_token_expires_at": (now + timedelta(seconds=payload["expires_in"])).isoformat(),
        "refresh_token_expires_at": (now + timedelta(seconds=payload["refresh_token_expires_in"])).isoformat(),
    }


class GitHubAuthManager:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {}
        # Not persisted: only meaningful for the lifetime of one in-progress
        # (or just-finished) linking attempt, reset to "idle" on every
        # fresh async_start_device_flow call.
        self._link_status: LinkStatus = "idle"

    async def async_load(self) -> None:
        self._data = await self._store.async_load() or {}

    @property
    def is_linked(self) -> bool:
        return bool(self._data.get("access_token"))

    @property
    def linked_username(self) -> str | None:
        return self._data.get("username")

    def link_status(self) -> dict[str, Any]:
        """Read by websocket_api.py's own github_link_status command,
        polled client-side while the panel shows a device-flow code (a
        rare, short-lived, user-watched flow, no push mechanism needed).

        "expired" (found live, 2026-08-15: Settings kept showing "Linked as
        X" with only an Unlink action, no way to re-link, even after
        async_get_valid_access_token had already raised the repair issue
        below): is_linked only ever checked whether an access_token was
        stored at all, never whether it's actually still usable, so a
        broken refresh never changed what this reported. self._data["broken"]
        (set at both failure points in async_get_valid_access_token, cleared
        on the next successful link or refresh) is the one extra bit needed
        to tell the two apart here."""
        if self.is_linked and self._data.get("broken"):
            status: LinkStatus = "expired"
        else:
            status = "linked" if self.is_linked else self._link_status
        return {
            "status": status,
            "username": self.linked_username,
        }

    async def async_start_device_flow(self) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        # No "scope" param here (found live, 2026-08-15, same audit as
        # community_vote.py's dropped "labels"): verified against GitHub's
        # own GitHub-App-specific device-flow docs -- a GitHub App's user
        # access token "does not use scopes... it uses fine-grained
        # permissions" instead (the app's own configured permissions), and
        # the token's own returned `scope` field "will always be an empty
        # string" regardless of what's sent here. Only OAuth Apps (a
        # different, older GitHub concept this integration doesn't use) act
        # on this parameter at all.
        async with session.post(
            _DEVICE_CODE_URL,
            data={"client_id": GITHUB_APP_CLIENT_ID},
            headers={"Accept": "application/json"},
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)

        self._link_status = "pending"
        self.hass.async_create_task(
            self._async_poll_and_link(payload["device_code"], payload["interval"], payload["expires_in"])
        )
        return {
            "user_code": payload["user_code"],
            "verification_uri": payload["verification_uri"],
            "expires_in": payload["expires_in"],
        }

    async def _async_poll_and_link(self, device_code: str, interval: int, expires_in: int) -> None:
        session = async_get_clientsession(self.hass)
        deadline = dt_util.utcnow() + timedelta(seconds=expires_in)
        # GitHub's own device-flow polling contract: keep asking at
        # `interval` seconds (bumped whenever it replies "slow_down") until
        # either a real token comes back, the user denies it, or the whole
        # device_code itself expires (expires_in, separate from the access
        # token's own, much longer expiry).
        while dt_util.utcnow() < deadline:
            await asyncio.sleep(interval)
            try:
                async with session.post(
                    _TOKEN_URL,
                    data={
                        "client_id": GITHUB_APP_CLIENT_ID,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                    headers={"Accept": "application/json"},
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
            except Exception:
                _LOGGER.debug("GitHub device-flow poll failed", exc_info=True)
                continue

            error = payload.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval = payload.get("interval", interval + 5)
                continue
            if error in ("expired_token", "access_denied"):
                self._link_status = "failed"
                return
            if error:
                _LOGGER.warning("GitHub device-flow linking failed: %s", error)
                self._link_status = "failed"
                return

            await self._async_store_tokens(payload)
            return

        self._link_status = "failed"

    async def _async_store_tokens(self, payload: dict[str, Any]) -> None:
        now = dt_util.utcnow()
        username = await self._async_fetch_username(payload["access_token"])
        self._data = {
            "access_token": payload["access_token"],
            "refresh_token": payload["refresh_token"],
            **_expiry_fields(payload, now),
            "username": username,
        }
        await self._store.async_save(self._data)
        self._link_status = "linked"
        # A fresh device-flow link always fixes whatever the old one's
        # repair issue (if any) was complaining about -- nothing left to
        # act on.
        _async_clear_link_expired_issue(self.hass)

    async def _async_fetch_username(self, access_token: str) -> str | None:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                _USER_URL,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"},
                timeout=10,
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
                return payload.get("login")
        except Exception:
            _LOGGER.debug("Couldn't fetch the linked GitHub username", exc_info=True)
            return None

    async def async_get_valid_access_token(self) -> str | None:
        """A valid access token, refreshing first if needed, or None if
        there's no way to get one right now (never linked, or the refresh
        token itself has expired after 6 months unused: only a fresh
        async_start_device_flow, not this method, can recover from that).
        Called by websocket_api.py wherever a vote is actually submitted.

        Raises the _ISSUE_LINK_EXPIRED repair issue for the two failure
        modes below that only a fresh re-link can fix -- not for a plain
        network exception on the refresh call itself (caught further down),
        which is just as likely a transient blip as a real problem, and
        would resolve itself on the very next call anyway."""
        if not self.is_linked:
            return None

        expires_at = dt_util.parse_datetime(self._data.get("access_token_expires_at", ""))
        if expires_at is not None and dt_util.utcnow() < expires_at - _EXPIRY_SAFETY_MARGIN:
            return self._data["access_token"]

        refresh_expires_at = dt_util.parse_datetime(self._data.get("refresh_token_expires_at", ""))
        if refresh_expires_at is not None and dt_util.utcnow() >= refresh_expires_at:
            await self._async_mark_broken()
            return None

        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                _TOKEN_URL,
                data={
                    "client_id": GITHUB_APP_CLIENT_ID,
                    "refresh_token": self._data["refresh_token"],
                    "grant_type": "refresh_token",
                },
                headers={"Accept": "application/json"},
            ) as response:
                response.raise_for_status()
                payload = await response.json(content_type=None)
        except Exception:
            _LOGGER.debug("Couldn't refresh the GitHub access token", exc_info=True)
            return None

        if "error" in payload:
            _LOGGER.warning("GitHub token refresh failed: %s", payload["error"])
            await self._async_mark_broken()
            return None

        now = dt_util.utcnow()
        # Both tokens rotate on every refresh, the old pair stops working
        # the instant this succeeds, so the username is kept as-is (it
        # can't have changed) but both tokens are fully replaced, never
        # merged with the old record. "broken" (see _async_mark_broken) is
        # explicitly dropped here too, not just left out of this dict: a
        # successful refresh recovering from an earlier failed one (a
        # transient GitHub-side error, not a real 6-month expiry) must clear
        # it, and the **self._data spread below would otherwise carry a
        # stale True straight through.
        self._data = {
            **self._data,
            "access_token": payload["access_token"],
            "refresh_token": payload["refresh_token"],
            **_expiry_fields(payload, now),
            "broken": False,
        }
        await self._store.async_save(self._data)
        _async_clear_link_expired_issue(self.hass)
        return self._data["access_token"]

    async def _async_mark_broken(self) -> None:
        """Persists that the current link is unusable until a fresh re-link
        (see link_status's own docstring for why this exists as a separate,
        stored bit rather than being derived), and raises the user-facing
        repair issue. Shared by both failure points in
        async_get_valid_access_token above."""
        self._data["broken"] = True
        await self._store.async_save(self._data)
        _async_create_link_expired_issue(self.hass)

    async def async_unlink(self) -> None:
        self._data = {}
        self._link_status = "idle"
        await self._store.async_save(self._data)
