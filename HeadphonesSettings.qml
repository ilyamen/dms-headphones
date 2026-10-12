import QtQuick
import qs.Common
import qs.Services
import qs.Widgets
import qs.Modules.Plugins

// Set-once options that live on the headset itself (voice prompts, button and
// gesture actions). Nothing here is stored by DMS: the controls read the
// headset's state and write straight back to it.
PluginSettings {
    id: root

    pluginId: "headphones"

    readonly property var devices: PluginService.globalVars["headphones"]?.state?.devices ?? []
    readonly property string selected: PluginService.globalVars["headphones"]?.selected ?? ""
    readonly property var headset: devices.find(d => d.device.address === selected) ?? devices[0] ?? null
    readonly property bool ready: headset?.status === "ready"
    readonly property var settings: headset?.settings ?? []

    function tr(text) {
        return text ? I18n.trFor("headphones", text) : "";
    }

    DankButtonGroup {
        visible: root.devices.length > 1
        size: "small"
        maximumWidth: parent.width
        model: root.devices.map(d => (d.device.model ?? "").replace(/^(UGREEN\s+HiTune|Samsung\s+Galaxy|Galaxy)\s+/, ""))
        currentIndex: root.devices.indexOf(root.headset)
        onSelectionChanged: (index, selected) => {
            if (selected)
                PluginService.setGlobalVar("headphones", "selected", root.devices[index].device.address);
        }
    }

    StyledText {
        width: parent.width
        text: root.headset?.device ? root.headset.device.name : root.tr("No supported headphones connected")
        font.pixelSize: Theme.fontSizeLarge
        font.weight: Font.Medium
        color: Theme.surfaceText
        elide: Text.ElideRight
    }

    StyledText {
        width: parent.width
        visible: text !== ""
        text: {
            if (!root.headset?.device)
                return root.tr("Supported: UGREEN HiTune Max5, Max5c; Samsung Galaxy Buds3. Connect one over Bluetooth to change its settings.");
            if (!root.ready)
                return root.headset.error ? root.tr(root.headset.error) : root.tr("Connecting…");
            return root.settings.length === 0 ? root.tr("This headset has no further settings.") : "";
        }
        font.pixelSize: Theme.fontSizeSmall
        color: Theme.surfaceVariantText
        wrapMode: Text.WordWrap
    }

    ControlList {
        width: parent.width
        visible: root.ready
        controls: root.settings
        onChanged: (id, value) => PluginService.pluginDaemonInstances["headphones"]?.send({
                "cmd": "set",
                "address": root.headset?.device?.address ?? "",
                "id": id,
                "value": value
            })
    }
}
