"""Detects whether an update entity's underlying device is a Zigbee device
(ZHA or Zigbee2MQTT), and if so, which Zigbee network it belongs to, the
grouping key rollout_manager.py uses to pace firmware installs one device at
a time instead of flashing several at once (real radio traffic that can
destabilize the mesh).

Verified against real, current sources, not guessed: Zigbee2MQTT 2.12.1's own
`lib/extension/homeassistant.ts` (the bridge device it publishes always gets
manufacturer="Zigbee2MQTT"/model="Bridge", literal strings; every other
device's own discovery payload points its `via_device` at that bridge) and
Home Assistant core 2026.7.3's `device_registry.py`/`components/mqtt/entity.py`
(how that `via_device` becomes a real `via_device_id` on the resolved
DeviceEntry). The bridge's *name* is user-configurable (HA's own
`homeassistant.name` MQTT option), so deliberately not matched on, only the
two literal, non-configurable fields are.
"""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr


def is_zha_device(hass: HomeAssistant, device: dr.DeviceEntry) -> bool:
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == "zha":
            return True
    return False


def is_zigbee2mqtt_device(hass: HomeAssistant, device: dr.DeviceEntry) -> bool:
    if not device.via_device_id:
        return False
    bridge = dr.async_get(hass).async_get(device.via_device_id)
    return bool(bridge and bridge.manufacturer == "Zigbee2MQTT" and bridge.model == "Bridge")


def zigbee_network_id(hass: HomeAssistant, device: dr.DeviceEntry) -> str | None:
    """A stable identifier for *which* Zigbee network this device belongs to,
    not just "is this Zigbee at all", there can be more than one
    Zigbee2MQTT bridge on the same HA instance (each its own separate mesh),
    though in practice only ever one ZHA config entry (a single radio).
    Returns None for anything that isn't Zigbee at all."""
    if is_zigbee2mqtt_device(hass, device):
        return f"z2m:{device.via_device_id}"
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == "zha":
            return f"zha:{entry_id}"
    return None
