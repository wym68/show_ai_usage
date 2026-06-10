import QtQuick
import QtQuick.Layouts
import QtCore
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: root

    // Force the panel to allocate enough horizontal space for 4 pills.
    Layout.minimumWidth: 4 * Kirigami.Units.gridUnit * 3 + 3 * Kirigami.Units.smallSpacing
    Layout.preferredWidth: 4 * Kirigami.Units.gridUnit * 4 + 3 * Kirigami.Units.smallSpacing

    property var usageData: ({ "providers": [] })
    property var providers: usageData && usageData.providers ? usageData.providers : []
    property string errorMessage: ""

    // Resolve data file path: custom or default
    readonly property string defaultDataFileUrl: StandardPaths.writableLocation(StandardPaths.GenericDataLocation) + "/show-ai-usage/data.json"
    property string resolvedDataFilePath: {
        var custom = Plasmoid.configuration.dataFilePath || "auto"
        if (custom === "" || custom === "auto") {
            var url = defaultDataFileUrl.toString()
            return url.substring(0, 7) === "file://" ? url.substring(7) : url
        }
        return custom
    }

    // Override the default metadata tooltip with live usage data.
    toolTipMainText: "AI 用量"
    toolTipTextFormat: Text.RichText
    toolTipSubText: {
        var header = ""
        if (usageData && usageData.fetched_at) {
            header = "<i>更新于 " + relativeTime(usageData.fetched_at) + "</i><br/><br/>"
        }
        if (!providers || providers.length === 0)
            return header + (errorMessage || "等待数据…")
        return header + providers.map(function(p) {
            var name = _tipName(p)
            if (p.error) return "<b>" + name + "</b>: " + p.error
            var v5h = Math.round(Number(p.window_5h_percent) || 0)
            var v7d = Math.round(Number(p.window_7d_percent) || 0)
            var r5h = p.reset_5h || "–"
            var r7d = p.reset_7d || "–"
            return "<b>" + name + "</b><br/>"
                 + "5小时: " + v5h + "%&nbsp;&nbsp;" + r5h + "<br/>"
                 + "7天:&nbsp;&nbsp;&nbsp;&nbsp;" + v7d + "%&nbsp;&nbsp;" + r7d
        }).join("<br/>")
    }

    function _tipName(p) {
        var m = {"codex":"OpenAI Codex", "claude":"Claude Code", "kimi":"Kimi", "minimax":"MiniMax"}
        return p && p.provider ? (m[p.provider] || p.provider) : "未知服务"
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

    // Read data file via the executable dataengine
    Plasma5Support.DataSource {
        id: fileReader
        engine: "executable"
        connectedSources: []

        onNewData: {
            var stdout = data["stdout"] || ""
            if (stdout.length > 0) {
                try {
                    var parsed = JSON.parse(stdout)
                    root.usageData = parsed
                    root.errorMessage = ""
                } catch (e) {
                    root.errorMessage = "数据格式错误: " + e
                    root.usageData = { "providers": [] }
                }
            } else {
                var stderr = data["stderr"] || ""
                root.errorMessage = stderr.length > 0 ? "读取失败: " + stderr : "数据文件为空"
                root.usageData = { "providers": [] }
            }
            disconnectSource(sourceName)
        }
    }

    function loadUsageData() {
        fileReader.connectSource("cat " + root.resolvedDataFilePath)
    }

    compactRepresentation: CompactRepresentation {
        providers: root.providers
        errorMessage: root.errorMessage
    }

    fullRepresentation: FullRepresentation {
        usageData: root.usageData
        providers: root.providers
        errorMessage: root.errorMessage
        dataFileUrl: root.defaultDataFileUrl
    }

    Timer {
        id: refreshTimer
        interval: (Plasmoid.configuration.refreshInterval || 60) * 1000
        running: true
        repeat: true
        onTriggered: root.loadUsageData()
    }

    // ── Configuration change handler ──────────────────────────
    // Re-load data and refresh timer whenever config changes
    onConfigurationChanged: {
        // Recalculate resolved data path (in case dataFilePath changed)
        root.resolvedDataFilePathChanged()

        // Restart the timer immediately with the new interval
        refreshTimer.restart()

        // Force providers list refresh
        root.loadUsageData()
    }

    Component.onCompleted: root.loadUsageData()
}
