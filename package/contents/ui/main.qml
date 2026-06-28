import QtQuick
import QtQuick.Layouts
import QtCore
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasma5support as Plasma5Support
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: root

    // Allocate horizontal space proportional to the number of pills shown:
    // total width = count * per-pill width + gaps. The per-pill width is the
    // single knob controlling how big each provider is.
    readonly property int _compactCount: {
        var n = _enabledProviderIds.length
        var max = Math.max(1, Plasmoid.configuration.compactMaxProviders || 4)
        return Math.max(1, Math.min(n, max))
    }
    readonly property int _pillUnits: Math.max(2, Plasmoid.configuration.compactPillWidth || 4)
    Layout.minimumWidth: _compactCount * Kirigami.Units.gridUnit * (_pillUnits - 1) + (_compactCount - 1) * Kirigami.Units.smallSpacing
    Layout.preferredWidth: _compactCount * Kirigami.Units.gridUnit * _pillUnits + (_compactCount - 1) * Kirigami.Units.smallSpacing

    property var usageData: ({ "providers": [] })
    property string errorMessage: ""

    // Parse enabled providers from config (comma-separated string)
    property var _enabledProviderIds: {
        var raw = Plasmoid.configuration.enabledProviders || ""
        return raw.split(",").map(function(s) { return s.trim() }).filter(function(s) { return s.length > 0 })
    }

    // Filter providers to only show enabled ones
    property var providers: {
        var all = usageData && usageData.providers ? usageData.providers : []
        var enabled = _enabledProviderIds
        if (enabled.length === 0) return []
        return all.filter(function(p) {
            return enabled.indexOf(p.provider) >= 0
        })
    }

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

        onNewData: function(sourceName, data) {
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
        onToggleExpanded: root.expanded = !root.expanded
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

    // Plasma 6: PlasmoidItem has no configurationChanged signal.
    // Re-load data when the resolved file path changes.
    onResolvedDataFilePathChanged: root.loadUsageData()

    // ── Polling config sync ───────────────────────────────────────

    property var _lastPollingConfig: ({ enabled: null, interval: null, providers: null,
                                        claude: null, kimi: null, minimax: null })

    function _syncPollingConfig() {
        var enabled = Plasmoid.configuration.pollingEnabled || false
        var interval = Plasmoid.configuration.pollingInterval || 300
        var providers = Plasmoid.configuration.enabledProviders || "codex,claude,kimi,minimax"
        var claude = Plasmoid.configuration.claudeFetchMethod || "browser"
        var kimi = Plasmoid.configuration.kimiFetchMethod || "direct"
        var minimax = Plasmoid.configuration.minimaxFetchMethod || "direct"

        // Debounce: only sync if something actually changed
        if (_lastPollingConfig.enabled === enabled &&
            _lastPollingConfig.interval === interval &&
            _lastPollingConfig.providers === providers &&
            _lastPollingConfig.claude === claude &&
            _lastPollingConfig.kimi === kimi &&
            _lastPollingConfig.minimax === minimax) {
            return
        }

        _lastPollingConfig = { enabled: enabled, interval: interval, providers: providers,
                               claude: claude, kimi: kimi, minimax: minimax }

        var scriptUrl = Qt.resolvedUrl("../scripts/sync_config.py").toString()
        var scriptPath = scriptUrl.substring(0, 7) === "file://" ? scriptUrl.substring(7) : scriptUrl
        var methodArgs = " --claude-method " + claude + " --kimi-method " + kimi + " --minimax-method " + minimax
        var cmd
        if (enabled) {
            cmd = "python3 " + scriptPath + " --enable --interval " + interval + " --providers " + providers + methodArgs
        } else {
            cmd = "python3 " + scriptPath + " --disable"
        }
        configSyncExecutor.connectSource(cmd)
    }

    Plasma5Support.DataSource {
        id: configSyncExecutor
        engine: "executable"
        connectedSources: []

        onNewData: function(sourceName, data) {
            var stdout = data["stdout"] || ""
            var stderr = data["stderr"] || ""
            if (stderr.length > 0) {
                console.log("[ShowAIUsage] Config sync stderr:", stderr)
            }
            if (stdout.length > 0) {
                console.log("[ShowAIUsage] Config sync:", stdout)
            }
            disconnectSource(sourceName)
        }
    }

    // Watch polling-related config entries for changes
    property bool _pollingEnabled: Plasmoid.configuration.pollingEnabled || false
    property int _pollingInterval: Plasmoid.configuration.pollingInterval || 300
    property string _enabledProviders: Plasmoid.configuration.enabledProviders || "codex,claude,kimi,minimax"
    property string _claudeFetchMethod: Plasmoid.configuration.claudeFetchMethod || "browser"
    property string _kimiFetchMethod: Plasmoid.configuration.kimiFetchMethod || "direct"
    property string _minimaxFetchMethod: Plasmoid.configuration.minimaxFetchMethod || "direct"

    on_PollingEnabledChanged: _syncPollingConfig()
    on_PollingIntervalChanged: _syncPollingConfig()
    on_EnabledProvidersChanged: _syncPollingConfig()
    on_ClaudeFetchMethodChanged: _syncPollingConfig()
    on_KimiFetchMethodChanged: _syncPollingConfig()
    on_MinimaxFetchMethodChanged: _syncPollingConfig()

    Component.onCompleted: {
        root.loadUsageData()
        _syncPollingConfig()
    }
}
