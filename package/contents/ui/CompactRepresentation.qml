import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami as Kirigami

Item {
    id: root

    property var providers: []
    property string errorMessage: ""

    implicitWidth: providers && providers.length > 0
        ? Math.max(Kirigami.Units.gridUnit * 3, compactRow.implicitWidth)
        : Kirigami.Units.gridUnit * 2
    implicitHeight: Kirigami.Units.gridUnit

    function percent(provider) {
        var value = Number(provider && provider.window_5h_percent)
        if (isNaN(value)) {
            return 0
        }
        return Math.max(0, Math.min(100, value))
    }

    function usageColor(value) {
        if (value >= 95) {
            return "#F44336"
        }
        if (value >= 80) {
            return "#FF9800"
        }
        if (value >= 50) {
            return "#FFC107"
        }
        return "#4CAF50"
    }

    function providerName(provider) {
        return provider && provider.provider ? provider.provider : "未知服务"
    }

    RowLayout {
        id: compactRow
        anchors.centerIn: parent
        spacing: Kirigami.Units.smallSpacing
        visible: root.providers && root.providers.length > 0

        Repeater {
            model: root.providers || []

            Rectangle {
                id: meter

                readonly property var provider: modelData
                readonly property real usagePercent: root.percent(provider)

                Layout.preferredWidth: Kirigami.Units.gridUnit
                Layout.preferredHeight: Math.max(Kirigami.Units.smallSpacing, Kirigami.Units.gridUnit * 0.35)
                radius: height / 2
                color: Kirigami.Theme.disabledTextColor
                opacity: provider && provider.error ? 0.65 : 1

                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: Math.max(parent.height, parent.width * meter.usagePercent / 100)
                    radius: parent.radius
                    color: provider && provider.error ? "#F44336" : root.usageColor(meter.usagePercent)
                }

                MouseArea {
                    id: hoverArea
                    anchors.fill: parent
                    hoverEnabled: true
                }

                Controls.ToolTip.visible: hoverArea.containsMouse
                Controls.ToolTip.text: provider && provider.error
                    ? root.providerName(provider) + ": " + provider.error
                    : root.providerName(provider) + " 5h: " + Math.round(meter.usagePercent) + "%"
            }
        }
    }

    Text {
        anchors.centerIn: parent
        visible: !root.providers || root.providers.length === 0
        text: root.errorMessage ? "N/A" : "⋯"
        color: Kirigami.Theme.textColor
        font.pixelSize: Kirigami.Theme.defaultFont.pixelSize

        MouseArea {
            id: emptyHover
            anchors.fill: parent
            hoverEnabled: true
        }

        Controls.ToolTip.visible: emptyHover.containsMouse
        Controls.ToolTip.text: root.errorMessage || "等待数据…"
    }
}
