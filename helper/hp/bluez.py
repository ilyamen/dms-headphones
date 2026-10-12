"""What BlueZ knows about a device: name, advertised service UUIDs and modalias.

Read through `busctl` (systemd), since the standard library has no D-Bus client.
"""

import json
import subprocess


def _value(prop):
    return prop.get("data") if isinstance(prop, dict) else None


def device_info(address):
    """Device1 properties of `address`, or None when BlueZ does not know it."""
    output = subprocess.run(
        ["busctl", "--system", "--json=short", "call", "org.bluez", "/",
         "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"],
        capture_output=True, text=True, timeout=10, check=True).stdout
    objects = json.loads(output)["data"][0]
    address = address.upper()
    for path, interfaces in objects.items():
        device = interfaces.get("org.bluez.Device1")
        if not device or (_value(device.get("Address")) or "").upper() != address:
            continue
        return {
            "path": path,
            "address": address,
            "name": _value(device.get("Name")) or _value(device.get("Alias")) or "",
            "alias": _value(device.get("Alias")) or "",
            "uuids": [u.lower() for u in _value(device.get("UUIDs")) or []],
            "modalias": _value(device.get("Modalias")) or "",
            "connected": bool(_value(device.get("Connected"))),
        }
    return None
