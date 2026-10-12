# Headphones for DankMaterialShell

A [DankMaterialShell](https://github.com/AvengeMedia/DankMaterialShell) plugin that controls Bluetooth headphones from the Control Center, the way their phone apps do: noise cancelling, equalizer presets, game mode, LDAC, multipoint, voice prompts and button or gesture actions. The tile shows the active headset and its noise mode, the panel adds the battery levels and the live Bluetooth codec with its bitrate.

## Supported headphones

| Headset | Panel | Settings page |
| --- | --- | --- |
| UGREEN HiTune Max5 | Noise cancelling (three strengths), transparency, LDAC, game mode, multipoint, 9 EQ presets | Voice prompt language, ANC button actions |
| UGREEN HiTune Max5c | Noise cancelling, transparency, LDAC, game mode, multipoint, spatial audio, EQ presets | Voice prompt language |
| Samsung Galaxy Buds3 | Noise cancelling, game mode, EQ presets | Touch gestures one by one, pinch-and-hold action per bud, noise cancelling with one earbud, seamless connection |

Tested on a HiTune Max5 and Galaxy Buds3. The Max5c values come from [ugreen_core](https://github.com/dustincorder/ugreenapp), where it was the reference device.

Several headsets can be connected at once; the plugin keeps all of them linked. The tile shows the one the computer plays to, and a switch at the top of the panel picks another. Without one playing, it shows the one connected last. The tile and the bar pill appear only while a supported headset is connected.

## How it works

A small Python helper keeps each headset's control port (an RFCOMM channel it finds over SDP) open while the headset is connected. Changes made on the headset itself, such as switching noise cancelling with its button, show up in DMS right away. The helper needs only the Python standard library and `busctl` from systemd.

Each headset family has a driver in `helper/hp/drivers/`. A driver translates the vendor protocol into a list of controls (mode switches, toggles, dropdowns) and battery levels, and the plugin renders whatever it describes. Supporting another headset means adding a driver; the QML side stays the same. `tests/test_drivers.py` shows how a driver is exercised without hardware.

The protocols come from these projects, which worked them out from the official apps:

- UGREEN: [ugreen_core](https://github.com/dustincorder/ugreenapp)
- Samsung: [GalaxyBudsClient](https://github.com/timschneeb/GalaxyBudsClient) and [BudsLink](https://github.com/maniacx/BudsLink)

## Requirements

- DMS 1.6.3 or newer
- `python3` and `busctl` (systemd)
- BlueZ, with the headphones paired
- Optional: `hciconfig` (bluez-deprecated tools) for the bitrate in the codec line

## Installation

### From a registry

In DMS Settings → Plugins, add the registry `https://github.com/ilyamen/dms-plugin-registry.git`. Then install **Headphones** from Browse, or run:

```sh
dms plugins install headphones
```

### Manually

```sh
git clone https://github.com/ilyamen/dms-headphones ~/.config/DankMaterialShell/plugins/headphones
```

Enable the plugin in Settings → Plugins, then add the **Headphones** tile to the Control Center (or the pill to the bar). Voice prompts, button and gesture actions are in Settings → Plugins → Headphones.

## Notes

- Headsets accept one control client at a time. Close other tools that talk to the headset (the GalaxyBudsClient desktop app, ugreen_core) while the plugin is enabled.
- Switching LDAC on the Max5 re-establishes the audio link, so audio stops for a few seconds; the plugin reconnects by itself.
- To see the raw traffic: `python3 helper/headphonesd.py --debug`, then type `{"cmd": "devices", "addresses": ["AA:BB:CC:DD:EE:FF"]}` (disable the plugin first, see the previous note).

## License

GPL-3.0
