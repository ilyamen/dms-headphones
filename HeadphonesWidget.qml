import QtQuick
import qs.Common
import qs.Services
import qs.Widgets
import qs.Modules.Plugins

// Control Center tile and bar pill. Everything shown comes from the helper's
// state (HeadphonesService), so the same tile works for every supported headset.
PluginComponent {
    id: root

    property var popoutService: null

    // All connected supported headsets, and the one shown: the selected one
    // (normally the current audio output), else the one connected last.
    readonly property var devices: PluginService.globalVars["headphones"]?.state?.devices ?? []
    readonly property string selected: PluginService.globalVars["headphones"]?.selected ?? ""
    readonly property var headset: devices.find(d => d.device.address === selected) ?? devices[0] ?? null
    readonly property var device: headset?.device ?? null
    readonly property bool connected: device !== null
    readonly property bool ready: headset?.status === "ready"
    readonly property string shortName: modelName(device)

    // Set by the detail panel to its content height, so the Control Center
    // opens it exactly as tall as the controls of this headset need.
    property real detailHeight: 300

    readonly property string statusText: {
        if (!connected)
            return tr("Not connected");
        if (!ready)
            return headset.error ? tr(headset.error) : tr("Connecting…");
        return (headset.summary ?? []).map(tr).join(" · ");
    }

    function modelName(dev) {
        return (dev?.model ?? "").replace(/^(UGREEN\s+HiTune|Samsung\s+Galaxy|Galaxy)\s+/, "");
    }

    function choose(address) {
        PluginService.setGlobalVar("headphones", "selected", address);
    }

    function tr(text) {
        return text ? I18n.trFor("headphones", text) : "";
    }

    function send(message) {
        PluginService.pluginDaemonInstances["headphones"]?.send(message);
    }

    function set(id, value) {
        send({
            "cmd": "set",
            "address": device?.address ?? "",
            "id": id,
            "value": value
        });
    }

    // Tile click and right click on the pill: noise control on or off
    function toggleNoise() {
        const toggle = headset?.toggle;
        if (ready && toggle)
            set(toggle.id, toggle.value === toggle.off ? toggle.on : toggle.off);
    }

    onConnectedChanged: setVisibilityOverride(connected)
    Component.onCompleted: setVisibilityOverride(connected)

    ccWidgetIcon: connected ? (device.icon || "headphones") : "headset_off"
    ccWidgetPrimaryText: connected ? shortName : tr("Headphones")
    ccWidgetSecondaryText: statusText
    ccWidgetIsActive: ready && headset.active === true

    onCcWidgetToggled: toggleNoise()
    onCcWidgetExpanded: send({
        "cmd": "refresh"
    })

    ccDetailHeight: detailHeight
    ccDetailContent: Component {
        HeadphonesDetail {
            widget: root
        }
    }

    pillClickAction: (x, y, width, section, screen) => {
        root.popoutService?.toggleControlCenter(x, y, width, section, screen);
    }
    pillRightClickAction: () => root.toggleNoise()

    horizontalBarPill: Component {
        DankIcon {
            name: root.ccWidgetIcon
            size: root.iconSize
            color: root.ccWidgetIsActive ? Theme.primary : Theme.surfaceText
        }
    }

    verticalBarPill: Component {
        DankIcon {
            name: root.ccWidgetIcon
            size: root.iconSize
            color: root.ccWidgetIsActive ? Theme.primary : Theme.surfaceText
        }
    }
}
