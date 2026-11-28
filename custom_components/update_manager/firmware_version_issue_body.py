"""Pure, HA-independent construction of a firmware-version-mapping issue's
body text, same split-out reasoning as vote_issue_body.py (unit-testable
without a live hass, and this exact string format is easy to get subtly
wrong and hard to catch by reading alone).

Field labels must match community-votes' own
`.github/ISSUE_TEMPLATE/firmware-version.yml` exactly for every field its
own `process-firmware-version.yml` reads back out by name (Manufacturer,
Model, Raw OTA version, Real firmware version). "Model name" and "Reported
by Update Manager version" have no parsing counterpart at all, same safe
"extra field just sits there unread" reasoning as vote_issue_body.py's own
"Release" field: direct user feedback, 2026-11-25, after a real batch of
these came back readable only as a bare manufacturer/model_id pair ("Philips/
929002477901") with no way to tell which actual product that was without
looking it up by hand. model_id (Model) stays the one thing the conflict
check/matching logic ever keys on, exactly as unambiguous as before; this is
purely a human-readable label alongside it.
"""
from __future__ import annotations

from .vote_issue_body import _field


def build_issue_body(
    manufacturer: str,
    model: str,
    raw_version: int,
    real_version: str,
    integration_version: str,
    model_name: str | None = None,
) -> str:
    return "\n".join(
        [
            _field("Manufacturer", manufacturer),
            _field("Model", model),
            _field("Model name", model_name),
            _field("Raw OTA version", str(raw_version)),
            _field("Real firmware version", real_version),
            _field("Reported by Update Manager version", integration_version),
        ]
    )
