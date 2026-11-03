[![Made for Home Assistant](https://img.shields.io/badge/Made%20for-Home%20Assistant-blue?style=for-the-badge&logo=homeassistant)](https://www.home-assistant.io/)
[![marketplace_badge](https://img.shields.io/badge/Marketplace-Default-orange.svg?style=for-the-badge)](https://contributors.home-assistant.io/marketplace/)

# Update Manager: Home Assistant helper integration

Updates pile up, and it's never quite obvious which ones are safe to just let happen. Update Manager
watches them for you and decides when an update has actually earned your trust: it gives a fresh release
time to prove itself, listens for anyone else who's already made the same jump and hit trouble, and
installs everything in an order that won't leave Home Assistant restarting mid-update. Turn on
auto-install and most of that becomes something you never have to think about again, all from a panel
that looks and feels like it's always been part of Home Assistant.

---

| Home | Dialog | History |
| :---:         |     :---:      |          :---: |
| [![Update Manager](images/home.png)](images/home.png)  | [![Update Manager](images/dialog_autoupdate.png)](images/dialog_autoupdate.png)     | [![Update Manager](images/history.png)](images/history.png)    |

---

## Why you'll like it

* **A second opinion before you commit.** See whether others already made your exact jump safely, vote
  yourself, and let someone you trust override your own rules the moment they vouch for a release.
* **Nothing installs in a risky order.** Core, Supervisor, OS, and device firmware queue up to avoid a
  restart cutting off something else mid-install; Zigbee devices on the same network never reflash at once.
* **A waiting period sized to the risk.** A small bump and a major Core jump don't deserve the same
  caution, so each size gets its own buffer before it counts as ready. Restrict further to specific
  weekdays or times, e.g. only ever ready on Saturdays.
* **Auto-install that still asks first.** A cancellable countdown announces what's coming, with an
  automatic backup when the update supports one, and a master switch to pause all of it in one click.
* **Release notes worth reading.** Real GitHub notes compiled across every skipped version, plus a
  wrapped app's own upstream notes (Zigbee2MQTT, Mealie, Matterbridge) alongside the short version.

---

## Installation

This integration is available via Home Assistant's built-in [Marketplace](https://contributors.home-assistant.io/marketplace/).

[![Open your Home Assistant instance and open a repository inside the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=HA-Update-Manager&repository=ha-update-manager&category=integration)

1. Go to the Marketplace in your Home Assistant.
2. Search for "Update Manager" and download it.
3. Restart Home Assistant.

---

## Configuration

[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=update_manager)

1. Navigate to **Settings > Devices & Services**, add **Update Manager**, and confirm the
   single-instance setup.
2. Open the **Update Manager** entry in the sidebar to review updates and adjust the rules (Settings
   tab).

There's nothing to fill in during setup itself; every actual setting lives on Update Manager's own
Settings tab.

## How auto-install decides

For a specific entity's pending update, in this exact order:

1. **Hard gates:** Excluded entities and anything skipped via Home Assistant's own "Skip this version"
   never auto-install. Core, Supervisor, and OS start out excluded by default; remove them from that
   list to make them eligible like anything else.
2. **A trusted voter's "healthy" vote on this exact jump wins outright**, skipping the wait and the size
   toggle, even over someone else's problem report on the same jump.
3. **Any problematic community vote blocks it** (unless step 2 already overrode it): one vote from
   anyone is enough, no quorum needed.
4. **Otherwise, your own size-based rules apply**: waiting period elapsed, size toggle on, announce, then
   install.

A blocked update shows an "Auto-install held back" alert naming the trusted voter or reported count; the
Community section on that dialog shows each reported reason. A vote (and this block) applies to the
*exact* version jump, not any known issue along the way.

## Automating

Every entity Update Manager creates lives under its own "Update Manager" device.

* **Status sensors**: one per status the Updates tab groups by (`sensor.update_manager_ready`, `_waiting`,
  `_blocked`, `_skipped`, `_not_installable`). Each sensor's state is that status's own count, with
  affected entities listed in its attributes; point a `numeric_state` trigger at one directly, e.g. to
  notify when anything becomes Discouraged. `sensor.update_manager_needs_manual_action` separately counts
  "Ready to update" entities that won't auto-install on their own, i.e. what's left for you to do yourself.
* **Events**, fired on `hass.bus` for the three discrete moments an automation might want to react to:

  | Event | Fired when | Data |
  | --- | --- | --- |
  | `update_manager_announced` | An auto-install countdown starts | `entity_id`, `from_version`, `to_version`, `release_url`, `execute_at` |
  | `update_manager_installed` | An install completes, auto or manual alike | `entity_id`, `from_version`, `to_version`, `auto_installed`, `install_method`, `auto_install_reason`, `trusted_voter_usernames` |
  | `update_manager_install_failed` | An auto-install's `update.install` call raised | `entity_id`, `to_version` |

  Ongoing status is already covered by the sensors above; these events are only for the moments in
  between. `install_method` is `auto`, `manual`, or `external` (updated itself outside Home Assistant,
  e.g. a device with its own separate auto-update setting).
* **Services** (Developer Tools > Actions), so an automation can act on `update_manager_announced` without
  the panel involved, e.g. analyzing release notes before letting a scheduled auto-install proceed:

  | Service | Does |
  | --- | --- |
  | `update_manager.get_release_notes` | Returns the same compiled release notes the update-detail dialog itself shows, from the currently installed version up to `to_version` (defaults to the entity's own current latest version if omitted). |
  | `update_manager.cancel_scheduled_install` | Cancels a scheduled auto-install for `to_version` (same default as above). |

**Example: send yourself a notification for every scheduled auto-install**, the same message the built-in
persistent notification already shows, just on your phone instead:

```yaml
automation:
  - alias: "Update Manager: notify on scheduled auto-install"
    trigger:
      - trigger: event
        event_type: update_manager_announced
    variables:
      device_name: >-
        {{ state_attr(trigger.event.data.entity_id, 'friendly_name') | regex_replace("\\s*Update$", "") }}
    action:
      - action: notify.notify  # replace with your own target, e.g. notify.mobile_app_your_phone
        data:
          title: "Scheduled update"
          message: >-
            Update Manager wants to update {{ device_name }} to version {{ trigger.event.data.to_version }}
            on {{ as_timestamp(trigger.event.data.execute_at) | timestamp_custom('%d-%m-%Y %H:%M') }}.
          data:
            url: /update-manager/updates
            clickAction: /update-manager/updates
            group: update_manager_announced  # bundles these together in the notification shade
            tag: "{{ device_name }}"         # a newer announcement for the same device replaces the old one
```

## How data updates

Updates/History refresh automatically as Home Assistant reports new information. Community-vote data is
cached for up to an hour (the panel's manual refresh button forces a fresh fetch). Staging recomputes
every 15 minutes.

## Known limitations

* Staging rules apply per update *size* (small/medium/large), not per individual entity: an entity can be
  excluded entirely, but can't get its own, different waiting period.
* Voting only works for entities identifiable as a Marketplace integration, Home Assistant Core/Supervisor/OS,
  a recognized Zigbee device model, or an app.
* Voting requires linking a GitHub account (a quick one-time device-flow step); reading verdicts doesn't.
* A vote (and the community block) applies to the *exact* version jump. A negative verdict on 1.0.0 to
  1.0.1 has no bearing on a direct 1.0.0 to 1.0.2 jump: those are tracked as entirely separate votes.
* Zigbee rollout pacing and the safe install order only apply when Update all, auto-install, or this
  panel's own dialog triggers the install. A single click anywhere else opens Home Assistant's own native
  update dialog instead, which Update Manager can't see or pace.
* An update needing a newer Home Assistant Core than you're running shows as "Postponed" (required version
  included) instead of being retried or failing; resumes automatically once your Core catches up.
* An entity with Home Assistant's own per-entity "Auto update" on (common for some Apps) is installed by
  Home Assistant itself, so Update Manager never announces or auto-installs it, to avoid racing that. Hide
  postponed updates still can't hide it though: Home Assistant's own skip service refuses to run on any
  entity with this toggle on, turn it off for anything you want Update Manager to actually manage. A live
  toggle can take up to 15 minutes to show up here, that's Home Assistant's own Supervisor polling
  interval, not something Update Manager controls.

## Troubleshooting

* **A pending update isn't showing as "ready" yet**: staging recomputes every 15 minutes, so it can lag
  the wait-days boundary by that much.
* **A History entry says "Install method: External"**: happened outside Home Assistant entirely (a
  device/app with its own auto-update, e.g. a UniFi switch), only noticed once it already had a newer
  version.
* **No vote controls show for an entity**: likely not identifiable for voting (see Known limitations).
* **An update still auto-installed despite a negative vote**: check the vote was on this exact jump, and
  that no trusted voter's "healthy" vote was in play (it always wins).
* **A repair notification says my GitHub link has expired**: only after two failed refreshes in a row.
  Re-link from the Settings tab, or wait: the next successful refresh clears it on its own too.
* **A repair issue says "An update seems stuck"**: it's running longer than usual without finishing. Only
  stops that one entity from holding up anything waiting behind it, doesn't cancel the install itself.
  The same "Stop waiting" action is also one click away from the entity's own detail dialog.
* Check **Settings > System > Logs** (filter on "update_manager") for anything at warning level or above.

## Removal

1. Go to **Settings > Devices & Services**, find **Update Manager**, and remove it (the three-dot menu
   on its card, or open the entry and use Delete).
2. If you added it as a Marketplace custom repository, remove it from the Marketplace too (Integrations tab, three-dot
   menu on Update Manager's own card).

Nothing outside Home Assistant's own storage is touched by this integration (no separate service,
container, or external account changes), so there's nothing else to clean up.
