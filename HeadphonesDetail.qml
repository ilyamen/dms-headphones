import QtQuick
import qs.Common
import qs.Services
import qs.Widgets

Rectangle {
    id: detail

    required property var widget
    readonly property var headset: widget.headset
    readonly property var battery: headset?.battery ?? []
    readonly property var btDevice: (BluetoothService.devices?.values ?? []).find(d => (d.address || "").toUpperCase() === (widget.device?.address ?? "")) ?? null

    implicitHeight: header.height + (controls.visible ? controls.height + Theme.spacingL : 0) + Theme.spacingM * 2
    onImplicitHeightChanged: widget.detailHeight = implicitHeight
    Component.onCompleted: widget.detailHeight = implicitHeight

    radius: Theme.cornerRadius
    color: Theme.nestedSurface
    border.color: Theme.outlineMedium
    border.width: Theme.layerOutlineWidth

    Column {
        id: header
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: Theme.spacingM
        spacing: Theme.spacingS

        // Several headsets connected: pick which one the panel and tile show
        DankButtonGroup {
            visible: detail.widget.devices.length > 1
            anchors.horizontalCenter: parent.horizontalCenter
            size: "small"
            maximumWidth: parent.width
            model: detail.widget.devices.map(d => detail.widget.modelName(d.device))
            currentIndex: detail.widget.devices.indexOf(detail.headset)
            onSelectionChanged: (index, selected) => {
                if (selected)
                    detail.widget.choose(detail.widget.devices[index].device.address);
            }
        }

        Item {
            width: parent.width
            height: Math.max(titleColumn.implicitHeight, 32)

            Column {
                id: titleColumn
                anchors.left: parent.left
                anchors.right: headerRight.left
                anchors.rightMargin: Theme.spacingS
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2

                StyledText {
                    width: parent.width
                    text: detail.widget.device?.name || detail.widget.tr("Headphones")
                    font.pixelSize: Theme.fontSizeLarge
                    font.weight: Font.Medium
                    color: Theme.surfaceText
                    elide: Text.ElideRight
                }

                StyledText {
                    width: parent.width
                    visible: text !== ""
                    text: codecInfo.text
                    font.pixelSize: Theme.fontSizeSmall
                    color: Theme.surfaceVariantText
                    elide: Text.ElideRight
                }
            }

            Row {
                id: headerRight
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: Theme.spacingM

                DankSpinner {
                    size: 16
                    visible: detail.headset?.busy === true || (detail.widget.connected && !detail.widget.ready && !detail.headset?.error)
                    anchors.verticalCenter: parent.verticalCenter
                }

                Repeater {
                    model: detail.battery

                    Row {
                        required property var modelData
                        spacing: 2
                        anchors.verticalCenter: parent.verticalCenter

                        StyledText {
                            visible: text !== ""
                            text: detail.widget.tr(modelData.label)
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.surfaceVariantText
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        DankIcon {
                            readonly property int level: modelData.level
                            name: modelData.charging ? "battery_charging_full" : level > 80 ? "battery_full" : level > 50 ? "battery_5_bar" : level > 20 ? "battery_3_bar" : "battery_1_bar"
                            size: Theme.iconSizeSmall
                            color: level > 20 || modelData.charging ? Theme.surfaceVariantText : Theme.warning
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        StyledText {
                            text: modelData.level + "%"
                            font.pixelSize: Theme.fontSizeSmall
                            color: Theme.surfaceVariantText
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }
            }
        }

        StyledText {
            width: parent.width
            visible: text !== ""
            text: !detail.widget.connected ? detail.widget.tr("Connect supported headphones over Bluetooth to control them.") : detail.widget.tr(detail.headset?.error ?? "")
            font.pixelSize: Theme.fontSizeSmall
            color: detail.widget.connected ? Theme.error : Theme.surfaceVariantText
            wrapMode: Text.WordWrap
        }
    }

    ControlList {
        id: controls
        anchors.top: header.bottom
        anchors.topMargin: Theme.spacingL
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: Theme.spacingM
        anchors.rightMargin: Theme.spacingM
        visible: detail.widget.ready
        controls: detail.headset?.controls ?? []
        opacity: detail.headset?.busy ? 0.75 : 1
        onChanged: (id, value) => detail.widget.set(id, value)

        Behavior on opacity {
            NumberAnimation {
                duration: Theme.shortDuration
            }
        }
    }

    // Live codec line, refreshed only while this panel is shown: codec and sample
    // rate from the BlueZ media transport, bitrate from the adapter's TX counter.
    QtObject {
        id: codecInfo

        property string text: ""
        // AAC states its bitrate ceiling in the codec configuration
        property int maxKbps: 0
        property var lastTx: null
        readonly property string procId: "headphones.tx." + Math.floor(Math.random() * 1e9)

        function codecLabel(props) {
            const codec = Number(props.Codec);
            const bytes = BluetoothService.bytesFromDbusValue(props.Configuration);
            const name = BluetoothService.codecNameFromBluez(codec, props.Configuration);
            maxKbps = name === "AAC" && bytes.length >= 6 ? Math.round((((bytes[3] & 0x7F) << 16) | (bytes[4] << 8) | bytes[5]) / 1000) : 0;
            if (name === "LDAC" && bytes.length > 6) {
                const rate = ({
                        "32": "44.1",
                        "16": "48",
                        "8": "88.2",
                        "4": "96"
                    })[bytes[6] & 0x3C];
                return rate ? "LDAC · " + rate + " " + detail.widget.tr("kHz") : "LDAC";
            }
            return name ? BluetoothService.getCodecInfo(name).name : "";
        }

        // Read the transport the way DMS's own Bluetooth panel does: the object
        // list carries the codec configuration bytes that tell LDAC from other
        // vendor codecs (a plain property read does not deliver them).
        function update() {
            const devicePath = detail.btDevice?.dbusPath ?? "";
            if (!devicePath || !BluetoothService.dbusBridgeAvailable) {
                text = "";
                return;
            }
            DMSService.dbusCall("system", "org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects", [], response => {
                const objects = response.result?.values?.[0] ?? {};
                const path = Object.keys(objects).find(p => p.startsWith(devicePath + "/") && objects[p]["org.bluez.MediaTransport1"]);
                const props = path ? objects[path]["org.bluez.MediaTransport1"] : null;
                if (!props || props.Codec === undefined) {
                    text = "";
                    return;
                }
                const label = codecLabel(props);
                if (props.State !== "active") {
                    text = label ? label + " · " + detail.widget.tr("idle") : "";
                    return;
                }
                updateBitrate(label);
            });
        }

        // The counter covers the whole adapter, so other streaming devices add to it.
        function updateBitrate(label) {
            const adapter = (BluetoothService.adapter?.dbusPath ?? "/org/bluez/hci0").split("/").pop();
            Proc.runCommand(procId, ["hciconfig", adapter], (output, exitCode) => {
                const bytes = Number((/TX bytes:(\d+)/.exec(output) ?? [])[1]);
                const now = Date.now();
                let suffix = "";
                if (exitCode === 0 && lastTx && bytes >= lastTx.bytes && now > lastTx.time) {
                    const kbps = Math.round((bytes - lastTx.bytes) * 8 / (now - lastTx.time) / 10) * 10;
                    suffix = " · " + (maxKbps > 0 ? detail.widget.tr("≈%1 of %2 kbps").arg(kbps).arg(maxKbps) : detail.widget.tr("≈%1 kbps").arg(kbps));
                }
                if (exitCode === 0)
                    lastTx = {
                        "bytes": bytes,
                        "time": now
                    };
                text = label + suffix;
            }, 0, 3000, detail);
        }
    }

    Timer {
        interval: 1000
        repeat: true
        triggeredOnStart: true
        running: detail.visible && detail.btDevice !== null
        onRunningChanged: {
            if (!running) {
                codecInfo.lastTx = null;
            }
        }
        onTriggered: codecInfo.update()
    }
}
