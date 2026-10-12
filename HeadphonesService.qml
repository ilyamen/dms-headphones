import QtQuick
import Quickshell.Io
import qs.Common
import qs.Services
import qs.Modules.Plugins

// Runs the helper that talks to the headset. There is one instance of this
// component, so the Control Center tile, the bar pill and the settings page all
// share one connection: headsets accept a single control client at a time.
// The helper's state lands in PluginService.globalVars.headphones.state (all
// connected headsets) and .selected (the one shown); the other components send
// commands through send().
PluginComponent {
    id: root

    readonly property string directory: PluginService.availablePlugins["headphones"]?.pluginDirectory ?? ""

    // The headset the computer plays to becomes the one the tile shows; picking
    // another one in the panel overrides that until the output changes again.
    readonly property string sinkAddress: {
        const node = AudioService.sink;
        const address = node?.properties?.["api.bluez5.address"] ?? "";
        if (address)
            return address.toUpperCase();
        const match = /bluez_output\.([0-9A-Fa-f_]{17})/.exec(node?.name ?? "");
        return match ? match[1].replace(/_/g, ":").toUpperCase() : "";
    }
    onSinkAddressChanged: {
        if (sinkAddress)
            PluginService.setGlobalVar("headphones", "selected", sinkAddress);
    }

    // Connected devices, most recently connected first; the helper links every
    // one a driver supports. BlueZ signals keep this live, no polling.
    readonly property var connectedAddresses: (BluetoothService.devices?.values ?? []).filter(d => d.connected && d.address).map(d => d.address.toUpperCase())
    property var recency: []

    function send(message) {
        if (helper.running)
            helper.write(JSON.stringify(message) + "\n");
    }

    function syncDevices() {
        const connected = connectedAddresses;
        const kept = recency.filter(a => connected.includes(a));
        const added = connected.filter(a => !kept.includes(a));
        recency = added.concat(kept);
        send({
            "cmd": "devices",
            "addresses": recency
        });
    }

    onConnectedAddressesChanged: syncDevices()
    Component.onCompleted: {
        if (sinkAddress)
            PluginService.setGlobalVar("headphones", "selected", sinkAddress);
    }

    Component.onDestruction: PluginService.setGlobalVar("headphones", "state", null)

    Process {
        id: helper

        command: ["python3", "-I", "-B", root.directory + "/helper/headphonesd.py"]
        running: root.directory !== ""
        stdinEnabled: true

        onStarted: root.syncDevices()
        onExited: (exitCode, exitStatus) => {
            PluginService.setGlobalVar("headphones", "state", null);
            console.warn("headphones: helper exited with code", exitCode);
            restart.start();
        }

        stdout: SplitParser {
            onRead: line => {
                try {
                    PluginService.setGlobalVar("headphones", "state", JSON.parse(line));
                } catch (e) {
                    console.warn("headphones: unexpected helper output:", line);
                }
            }
        }
    }

    // A crashed helper comes back after a pause instead of spinning
    Timer {
        id: restart
        interval: 5000
        onTriggered: helper.running = root.directory !== ""
    }
}
