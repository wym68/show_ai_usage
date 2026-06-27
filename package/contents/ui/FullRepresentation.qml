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

    // Display mode from config
    readonly property int _displayMode: Plasmoid.configuration.displayMode || 0

    implicitWidth: Kirigami.Units.gridUnit * 20
    implicitHeight: Kirigami.Units.gridUnit * 24

    /* ── Helper functions ─────────────────────────────────── */

    function percent(provider, key) {
        var value = Number(provider && provider[key])
        if (isNaN(value)) return 0
        return Math.max(0, Math.min(100, value))
    }

    function usageColor(value) {
        var theme = Plasmoid.configuration.colorTheme || 0
        if (theme === 1) { // colorblind-friendly
            return value >= 95 ? "#9C27B0" : value >= 80 ? "#F44336" : value >= 50 ? "#FF9800" : "#2196F3"
        }
        if (theme === 2) { // custom
            var cLow = Plasmoid.configuration.customColorLow || "#4CAF50"
            var cMid = Plasmoid.configuration.customColorMid || "#FFC107"
            var cHigh = Plasmoid.configuration.customColorHigh || "#FF9800"
            var cCrit = Plasmoid.configuration.customColorCritical || "#F44336"
            return value >= 95 ? cCrit : value >= 80 ? cHigh : value >= 50 ? cMid : cLow
        }
        // default
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

    // Usage/console page each provider links to (opened in the default browser).
    function providerUrl(raw) {
        var map = {
            "codex":      "https://chatgpt.com/codex/cloud/settings/analytics",
            "claude":     "https://claude.ai/new#settings/usage",
            "kimi":       "https://www.kimi.com/code/console",
            "minimax":    "https://platform.minimaxi.com/console/usage"
        }
        return map[raw] || ""
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

    // Filter providers based on display mode
    readonly property var _filteredProviders: {
        var list = root.providers || []
        if (root._displayMode === 0) return list // show all
        return list.filter(function(p) {
            if (p.error) return true
            if (root._displayMode === 1) return !isNaN(Number(p.window_5h_percent))
            if (root._displayMode === 2) return !isNaN(Number(p.window_7d_percent))
            return true
        })
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
                    visible: !root._filteredProviders || root._filteredProviders.length === 0

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
                    model: root._filteredProviders

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
                                readonly property string _url: root.providerUrl(provider && provider.provider)

                                Layout.fillWidth: true
                                text: _url.length > 0
                                    ? "<a href=\"" + _url + "\" style=\"text-decoration:none; color:"
                                        + Kirigami.Theme.textColor + ";\">"
                                        + root.displayName(provider && provider.provider) + "</a>"
                                    : root.displayName(provider && provider.provider)
                                textFormat: Text.RichText
                                color: Kirigami.Theme.textColor
                                font.bold: true
                                font.pixelSize: Kirigami.Theme.defaultFont.pixelSize * 1.15
                                onLinkActivated: function(link) { Qt.openUrlExternally(link) }

                                HoverHandler {
                                    enabled: parent._url.length > 0
                                    cursorShape: Qt.PointingHandCursor
                                }
                            }

                            UsageRow {
                                visible: root._displayMode !== 2
                                Layout.fillWidth: true
                                label: "5h:"
                                value: providerCard.fiveHourPercent
                                barColor: root.usageColor(providerCard.fiveHourPercent)
                                percentText: root.formatPercent(providerCard.fiveHourPercent)
                            }

                            UsageRow {
                                visible: root._displayMode !== 1
                                Layout.fillWidth: true
                                label: "7d:"
                                value: providerCard.sevenDayPercent
                                barColor: root.usageColor(providerCard.sevenDayPercent)
                                percentText: root.formatPercent(providerCard.sevenDayPercent)
                            }

                            LabelLine {
                                Layout.fillWidth: true
                                visible: root._displayMode !== 2
                                    && provider && provider.reset_5h !== null
                                    && provider.reset_5h !== undefined
                                    && String(provider.reset_5h).length > 0
                                label: "重置(5h):"
                                value: provider && provider.reset_5h ? String(provider.reset_5h) : ""
                            }

                            LabelLine {
                                Layout.fillWidth: true
                                visible: root._displayMode !== 1
                                    && provider && provider.reset_7d !== null
                                    && provider.reset_7d !== undefined
                                    && String(provider.reset_7d).length > 0
                                label: "重置(7d):"
                                value: provider && provider.reset_7d ? String(provider.reset_7d) : ""
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
