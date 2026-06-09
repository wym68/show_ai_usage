import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami

Item {
    id: root

    property var usageData: ({ "providers": [] })
    property var providers: []
    property string errorMessage: ""
    property string dataFileUrl: ""

    readonly property int staleThreshold: (Plasmoid.configuration.staleThreshold || 600) * 1000  // ms

    implicitWidth: Kirigami.Units.gridUnit * 20
    implicitHeight: Kirigami.Units.gridUnit * 24

    /* ── Helper functions ─────────────────────────────────── */

    function percent(provider, key) {
        var value = Number(provider && provider[key])
        if (isNaN(value)) {
            return 0
        }
        return Math.max(0, Math.min(100, value))
    }

    function usageColor(value) {
        if (value >= 95) return "#F44336"
        if (value >= 80) return "#FF9800"
        if (value >= 50) return "#FFC107"
        return "#4CAF50"
    }

    function displayName(raw) {
        var map = {
            "codex":      "OpenAI Codex",
            "claude":     "Claude Code",
            "kimi":       "Kimi",
            "minimax":    "MiniMax"
        }
        return map[raw] || raw
    }

    function formatPercent(value) {
        return Math.round(value) + "%"
    }

    function relativeTime(isoString) {
        if (!isoString) return "未知"
        var now = new Date()
        var then = new Date(isoString)
        var diffMs = now.getTime() - then.getTime()
        if (isNaN(diffMs)) return isoString

        if (diffMs < 0) return "刚刚"
        var diffSec = Math.floor(diffMs / 1000)
        if (diffSec < 60)   return diffSec + " 秒前"
        var diffMin = Math.floor(diffSec / 60)
        if (diffMin < 60)   return diffMin + " 分钟前"
        var diffHour = Math.floor(diffMin / 60)
        if (diffHour < 24)  return diffHour + " 小时前"
        var diffDay = Math.floor(diffHour / 24)
        return diffDay + " 天前"
    }

    function isStale() {
        if (!usageData || !usageData.fetched_at) return false
        var now = new Date().getTime()
        var fetched = new Date(usageData.fetched_at).getTime()
        if (isNaN(fetched)) return false
        return (now - fetched) > root.staleThreshold
    }

    /* ── UI ───────────────────────────────────────────────── */

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.largeSpacing
        spacing: Kirigami.Units.smallSpacing

        /* Header */
        PlasmaExtras.Heading {
            Layout.fillWidth: true
            text: "🤖 AI 订阅用量追踪"
            level: 2
            wrapMode: Text.WordWrap
        }

        /* Update time + stale warning */
        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            Controls.Label {
                text: "更新时间:"
                color: Kirigami.Theme.disabledTextColor
            }
            Controls.Label {
                Layout.fillWidth: true
                text: relativeTime(usageData && usageData.fetched_at)
                color: Kirigami.Theme.textColor
            }
            Controls.Label {
                visible: root.isStale()
                text: "⚠ 数据已过期"
                color: "#FF9800"
                font.bold: true
            }
        }

        /* Scrollable provider list */
        Controls.ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            ColumnLayout {
                width: parent.width
                spacing: Kirigami.Units.largeSpacing

                /* Empty / error state */
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: emptyColumn.implicitHeight
                    visible: !root.providers || root.providers.length === 0

                    ColumnLayout {
                        id: emptyColumn
                        anchors.centerIn: parent
                        width: parent.width
                        spacing: Kirigami.Units.smallSpacing

                        PlasmaExtras.PlaceholderMessage {
                            Layout.fillWidth: true
                            text: root.errorMessage ? root.errorMessage : "等待数据… 请先运行 poller"
                        }
                        Controls.Label {
                            Layout.fillWidth: true
                            visible: root.dataFileUrl.length > 0
                            text: root.dataFileUrl
                            color: Kirigami.Theme.disabledTextColor
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }

                /* Provider cards */
                Repeater {
                    model: root.providers || []

                    Rectangle {
                        id: providerCard

                        readonly property var provider: modelData
                        readonly property real fiveHourPercent: root.percent(provider, "window_5h_percent")
                        readonly property real sevenDayPercent: root.percent(provider, "window_7d_percent")

                        Layout.fillWidth: true
                        Layout.preferredHeight: cardContent.implicitHeight + Kirigami.Units.largeSpacing * 2
                        radius: Kirigami.Units.cornerRadius
                        color: Kirigami.Theme.backgroundColor
                        border.color: provider && provider.error ? "#F44336" : Kirigami.Theme.highlightColor
                        border.width: provider && provider.error ? 2 : 1

                        ColumnLayout {
                            id: cardContent
                            anchors.fill: parent
                            anchors.margins: Kirigami.Units.largeSpacing
                            spacing: Kirigami.Units.smallSpacing

                            Controls.Label {
                                Layout.fillWidth: true
                                text: root.displayName(provider && provider.provider)
                                color: Kirigami.Theme.textColor
                                font.bold: true
                                font.pixelSize: Kirigami.Theme.defaultFont.pixelSize * 1.15
                            }

                            UsageRow {
                                Layout.fillWidth: true
                                label: "5h:"
                                value: providerCard.fiveHourPercent
                                barColor: root.usageColor(providerCard.fiveHourPercent)
                                percentText: root.formatPercent(providerCard.fiveHourPercent)
                            }

                            UsageRow {
                                Layout.fillWidth: true
                                label: "7d:"
                                value: providerCard.sevenDayPercent
                                barColor: root.usageColor(providerCard.sevenDayPercent)
                                percentText: root.formatPercent(providerCard.sevenDayPercent)
                            }

                            LabelLine {
                                Layout.fillWidth: true
                                visible: provider && provider.remaining_credit !== null && provider.remaining_credit !== undefined && String(provider.remaining_credit).length > 0
                                label: "剩余额度:"
                                value: provider && provider.remaining_credit !== null && provider.remaining_credit !== undefined ? String(provider.remaining_credit) : ""
                            }

                            LabelLine {
                                Layout.fillWidth: true
                                visible: provider && provider.reset_in !== null && provider.reset_in !== undefined && String(provider.reset_in).length > 0
                                label: "重置:"
                                value: provider && provider.reset_in !== null && provider.reset_in !== undefined ? String(provider.reset_in) : ""
                            }

                            Controls.Label {
                                Layout.fillWidth: true
                                visible: provider && provider.error
                                text: provider && provider.error ? provider.error : ""
                                color: "#F44336"
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }
            }
        }

        /* Bottom action bar */
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing

            Item { Layout.fillWidth: true }  // spacer

            Controls.Button {
                icon.name: "view-refresh"
                text: "刷新"
                onClicked: {
                    // Plasmoid.rootItem is the PlasmoidItem from main.qml
                    if (Plasmoid.rootItem && typeof Plasmoid.rootItem.loadUsageData === "function") {
                        Plasmoid.rootItem.loadUsageData()
                    }
                }
            }
        }
    }

    /* ── Inline components ─────────────────────────────────── */

    component UsageRow: RowLayout {
        property string label: ""
        property real value: 0
        property color barColor: "#4CAF50"
        property string percentText: "0%"

        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            Layout.preferredWidth: Kirigami.Units.gridUnit * 2
            text: parent.label
            color: Kirigami.Theme.textColor
            font.bold: true
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Kirigami.Units.smallSpacing * 1.5
            radius: height / 2
            color: Kirigami.Theme.disabledTextColor
            opacity: 0.9

            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: parent.width * Math.max(0, Math.min(100, value)) / 100
                radius: parent.radius
                color: barColor
            }
        }

        Controls.Label {
            Layout.preferredWidth: Kirigami.Units.gridUnit * 3
            text: parent.percentText
            color: Kirigami.Theme.textColor
            horizontalAlignment: Text.AlignRight
        }
    }

    component LabelLine: RowLayout {
        property string label: ""
        property string value: ""

        spacing: Kirigami.Units.smallSpacing

        Controls.Label {
            text: parent.label
            color: Kirigami.Theme.disabledTextColor
            font.bold: true
        }
        Controls.Label {
            Layout.fillWidth: true
            text: parent.value
            color: Kirigami.Theme.textColor
            wrapMode: Text.WordWrap
        }
    }
}
