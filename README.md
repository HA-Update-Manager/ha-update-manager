[![Made for Home Assistant](https://img.shields.io/badge/Made%20for-Home%20Assistant-blue?style=for-the-badge&logo=homeassistant)](https://www.home-assistant.io/)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)

# Update Manager: Home Assistant helper integration

Update Manager helps you decide when to install a Home Assistant update, and can optionally install it
for you automatically. Two independent safety nets back that decision: a waiting period per update size
(giving a broken release time to be noticed and fixed before you commit to it), and a community verdict
on the exact version jump you're taking (any reported problem holds auto-install back, regardless of the
wait). See "How auto-install decides" below for exactly how the two combine.

---

## Features

* **Staging rules:** updates are grouped by how big a jump they are, each with its own configurable
  waiting period before it counts as ready.
* **Auto-install, opt-in:** announced first with a cancellable countdown before anything installs,
  with an automatic backup when supported. Core, Supervisor, and OS updates always stay manual.
* **Master pause switch:** pauses all of Update Manager's automatic behavior at once, also available
  as a real switch entity for dashboards and automations.
* **Hide postponed updates:** optionally keeps still-waiting updates out of Home Assistant's own
  sidebar update count until they're actually ready.
* **Zigbee rollout pacing:** identical Zigbee devices (ZHA or Zigbee2MQTT) update one at a time instead
  of all at once, protecting mesh stability.
* **Community verdict and voting:** link your GitHub account to see whether others found your specific
  version *jump* healthy or problematic, and cast your own vote. Covers HACS integrations, Home Assistant
  Core/Supervisor/OS, real vendor Zigbee device firmware, and Supervisor add-ons.
* **Trusted voters and community block:** a trusted GitHub username's *healthy* verdict installs
  regardless of your own rules; any problematic vote from anyone blocks auto-install outright (see "How
  auto-install decides" below).
* **Sidebar panel:** Updates tab with live progress, History tab with a full per-entry audit trail, and
  an autosaving Settings tab.

---

## Installation

This integration isn't in the HACS default store yet, so add it as a custom repository.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HA-Update-Manager&repository=ha-update-manager&category=integration)

1. In HACS, add `https://github.com/HA-Update-Manager/ha-update-manager` as a custom repository
   (category: Integration).
2. Install "Update Manager" and restart Home Assistant.

---

## Configuration

[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=update_manager)

1. Navigate to **Settings > Devices & Services**, add **Update Manager**, and confirm the
   single-instance setup.
2. Open the **Update Manager** entry in the sidebar to review updates and adjust the rules (Settings
   tab).

There's nothing to fill in during setup itself; every actual setting lives on the sidebar panel's own
Settings tab (autosaving, no separate Save button) instead of the usual Devices & Services options
screen:

* **Waiting period per size** (small/medium/big): how many days a small/medium/big update sits before
  it counts as ready.
* **Auto-install, per size**: whether that size installs itself once ready (still announced first, with
  a cancellable countdown).
* **Announcement window**: how many hours' notice you get before an auto-install actually runs.
* **Hide postponed updates**: keeps a still-waiting update out of Home Assistant's own sidebar update
  count until it's actually ready.
* **Excluded entities**: specific `update.*` entities that should always stay manual, regardless of the
  size rules above.
* **Trusted voters**: GitHub usernames whose community verdict on a version jump overrides your own
  auto-install rules (see Features above).
* **Enabled**: the master pause switch, also available as its own switch entity (`switch.update_manager_enabled`).

## How auto-install decides

For a specific entity's pending update, in this exact order:

1. **Hard gates, nothing overrides these:** Core, Supervisor, and OS updates never auto-install; neither
   does anything in Excluded entities or skipped via Home Assistant's own "Skip this version."
2. **A trusted voter's "healthy" vote on this exact jump wins outright**, skipping the waiting period and
   the per-size toggle, even over someone else's problem report on the same jump.
3. **Any problematic community vote blocks it** (unless step 2 already overrode it): one vote, from
   anyone, is enough. No quorum, no percentage, and no trusted voters need to be configured for this.
4. **Otherwise, your own size-based rules apply**: waiting period elapsed, size toggle on, announce, then
   install.

A blocked update shows an "Auto-install held back" alert on its dialog, naming the trusted voter or the
reported count; the Community section on that dialog shows each reported reason.

Scoping note: a vote (and this block) applies to the *exact* version jump, not any known issue along the
way. See Known limitations below.

## Use cases

* You've been burned by a buggy update before and want a buffer before anything installs itself, without
  giving up automatic installs entirely.
* You run a large instance and don't want a wall of individual `update.*` entities to review one by one.
* You have Zigbee devices sharing the same firmware and don't want them all reflashing at once.
* You want a second opinion from others who already made the same version jump, or one specific person's
  judgment to be able to override your own rules automatically.

## How data updates

Updates/History refresh automatically as Home Assistant reports new information. Community-vote data is
cached for up to an hour (the panel's manual refresh button forces a fresh fetch). Staging recomputes
every 15 minutes.

## Known limitations

* Staging rules apply per update *size* (small/medium/big), not per individual entity: an entity can be
  excluded entirely, but can't get its own, different waiting period.
* Voting only works for entities identifiable as a HACS integration, Home Assistant Core/Supervisor/OS,
  a recognized Zigbee device model, or a Supervisor add-on.
* Voting requires linking a GitHub account (a quick one-time device-flow step); reading verdicts doesn't.
* A vote (and the community block) applies to the *exact* version jump. A negative verdict on 1.0.0 to
  1.0.1 has no bearing on a direct 1.0.0 to 1.0.2 jump: those are tracked as entirely separate votes.

## Troubleshooting

* **A pending update isn't showing as "ready" yet**: staging recomputes every 15 minutes, so it can lag
  the exact wait-days boundary by up to that long.
* **No vote controls show for an entity**: it likely isn't identifiable for voting (see Known limitations).
* **An update still auto-installed despite a negative vote I saw**: check the vote was on this exact
  version jump (see Known limitations), and that no trusted voter's "healthy" vote was in play (it always
  wins, see "How auto-install decides").
* **A repair notification says my GitHub link has expired**: re-link it from the Settings tab; it clears
  on its own once you do.
* Check **Settings > System > Logs** (filter on "update_manager") for anything at warning level or above.

## Removal

1. Go to **Settings > Devices & Services**, find **Update Manager**, and remove it (the three-dot menu
   on its card, or open the entry and use Delete).
2. If you added it as a HACS custom repository, remove it from HACS too (Integrations tab, three-dot
   menu on Update Manager's own card).

Nothing outside Home Assistant's own storage is touched by this integration (no separate service,
container, or external account changes), so there's nothing else to clean up.
