import QtQuick
import qs.Common
import qs.Widgets

// Renders the controls a driver describes (see helper/hp/drivers/base.py):
// "segmented" mode switches, labelled "choice" rows, toggles and "list" dropdowns.
Column {
    id: list

    property var controls: []
    readonly property var shown: controls.filter(c => c.visible !== false)

    signal changed(string id, var value)

    function tr(text) {
        return text ? I18n.trFor("headphones", text) : "";
    }

    spacing: Theme.spacingM

    // Counted rather than given the array, so a state update refreshes the
    // controls in place instead of rebuilding them mid-interaction.
    Repeater {
        model: list.shown.length

        Column {
            id: entry

            required property int index
            readonly property var modelData: list.shown[index] ?? ({})
            readonly property var options: modelData.options ?? []
            readonly property int selectedIndex: options.findIndex(o => o.value === modelData.value)

            width: list.width
            spacing: Theme.spacingS

            StyledText {
                width: parent.width
                visible: (entry.modelData.section ?? "") !== ""
                topPadding: Theme.spacingS
                text: list.tr(entry.modelData.section)
                font.pixelSize: Theme.fontSizeMedium
                font.weight: Font.Medium
                color: Theme.surfaceText
            }

            StyledText {
                width: parent.width
                visible: (entry.modelData.sectionDescription ?? "") !== ""
                text: list.tr(entry.modelData.sectionDescription)
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.surfaceVariantText
                wrapMode: Text.WordWrap
            }

            Loader {
                width: parent.width
                sourceComponent: ({
                        "segmented": segmented,
                        "choice": choice,
                        "toggle": toggle,
                        "list": dropdown
                    })[entry.modelData.kind] ?? null

                Component {
                    id: segmented

                    Item {
                        implicitHeight: segmentedGroup.height

                        DankButtonGroup {
                            id: segmentedGroup
                            anchors.horizontalCenter: parent.horizontalCenter
                            maximumWidth: parent.width
                            enabled: entry.modelData.enabled !== false
                            model: entry.options.map(o => list.tr(o.label))
                            currentIndex: entry.selectedIndex
                            onSelectionChanged: (index, selected) => {
                                if (selected && index !== entry.selectedIndex)
                                    list.changed(entry.modelData.id, entry.options[index].value);
                            }
                        }
                    }
                }

                Component {
                    id: choice

                    Item {
                        implicitHeight: Math.max(choiceLabel.implicitHeight, choiceGroup.height)
                        opacity: entry.modelData.enabled !== false ? 1 : 0.5

                        StyledText {
                            id: choiceLabel
                            anchors.left: parent.left
                            anchors.right: choiceGroup.left
                            anchors.rightMargin: Theme.spacingM
                            anchors.verticalCenter: parent.verticalCenter
                            text: list.tr(entry.modelData.label)
                            font.pixelSize: Theme.fontSizeMedium
                            color: Theme.surfaceText
                            elide: Text.ElideRight
                        }

                        DankButtonGroup {
                            id: choiceGroup
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            size: "small"
                            maximumWidth: parent.width * 0.7
                            enabled: entry.modelData.enabled !== false
                            model: entry.options.map(o => list.tr(o.label))
                            currentIndex: entry.selectedIndex
                            onSelectionChanged: (index, selected) => {
                                if (selected && index !== entry.selectedIndex)
                                    list.changed(entry.modelData.id, entry.options[index].value);
                            }
                        }
                    }
                }

                Component {
                    id: toggle

                    DankToggle {
                        text: list.tr(entry.modelData.label)
                        description: list.tr(entry.modelData.description)
                        enabled: entry.modelData.enabled !== false
                        checked: entry.modelData.value === true
                        onToggled: checked => list.changed(entry.modelData.id, checked)
                    }
                }

                Component {
                    id: dropdown

                    DankDropdown {
                        text: list.tr(entry.modelData.label)
                        description: list.tr(entry.modelData.description)
                        enabled: entry.modelData.enabled !== false
                        options: entry.options.map(o => list.tr(o.label))
                        currentValue: entry.selectedIndex >= 0 ? list.tr(entry.options[entry.selectedIndex].label) : ""
                        onValueChanged: value => {
                            const picked = entry.options.find(o => list.tr(o.label) === value);
                            if (picked && picked.value !== entry.modelData.value)
                                list.changed(entry.modelData.id, picked.value);
                        }
                    }
                }
            }
        }
    }
}
