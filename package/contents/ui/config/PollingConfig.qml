import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kde.plasma.plasmoid
import org.kde.plasma.plasma5support as Plasma5Support

KCM.AbstractKCM {
    id: pollingConfigRoot

    property alias cfg_pollingEnabled: enablePollingCheck.checked
    property alias cfg_pollingInterval: intervalSpin.value
    property alias cfg_enabledProviders: providersField.text
    property alias cfg_claudeFetchMethod: claudeMethodField.text
    property alias cfg_kimiFetchMethod: kimiMethodField.text
    property alias cfg_minimaxFetchMethod: minimaxMethodField.text

    // Resolved at open from ~/.config/show-ai-usage/runtime.conf (written by
    // the installer). Needed to launch the poller for one-click login.
    property string projectDir: ""
    property string uvPath: "uv"

    readonly property string syncScriptPath: {
        var u = Qt.resolvedUrl("../scripts/sync_config.py").toString()
        return u.substring(0, 7) === "file://" ? u.substring(7) : u
    }

    // ── Shell helpers ─────────────────────────────────────────────
    function shQuote(s) {
        return "'" + String(s).replace(/'/g, "'\\''") + "'"
    }

    function rebuildProviders() {
        var ids = []
        if (rowCodex.enabledState)   ids.push("codex")
        if (rowClaude.enabledState)  ids.push("claude")
        if (rowKimi.enabledState)    ids.push("kimi")
        if (rowMinimax.enabledState) ids.push("minimax")
        providersField.text = ids.join(",")
    }

    function applyProvidersString(str) {
        var ids = str.split(",").map(function(s) { return s.trim() })
        rowCodex.enabledState   = ids.indexOf("codex") >= 0
        rowClaude.enabledState  = ids.indexOf("claude") >= 0
        rowKimi.enabledState    = ids.indexOf("kimi") >= 0
        rowMinimax.enabledState = ids.indexOf("minimax") >= 0
    }

    function copyCommand(text) {
        clipboardInput.text = text
        clipboardInput.selectAll()
        clipboardInput.copy()
    }

    function runLogin(providerId) {
        if (!projectDir) {
            statusLabel.text = "⚠ 未找到 runtime.conf，请在项目目录的终端运行：uv run python -m poller.main --login " + providerId
            return
        }
        statusLabel.text = "正在打开 " + providerId + " 登录窗口，登录后关闭浏览器即可保存…"
        var cmd = "cd " + shQuote(projectDir) + " && " + shQuote(uvPath)
                + " run python -m poller.main --login " + providerId
        actionExec.connectSource(cmd)
    }

    function saveToken(providerId, token) {
        statusLabel.text = "正在保存 " + providerId + " Token 到 secrets.env…"
        var cmd = "python3 " + shQuote(syncScriptPath) + " --save-secret " + providerId
                + " --token " + shQuote(token)
        actionExec.connectSource(cmd)
    }

    // Reads runtime.conf once at open.
    Plasma5Support.DataSource {
        id: runtimeReader
        engine: "executable"
        connectedSources: ["cat \"$HOME/.config/show-ai-usage/runtime.conf\" 2>/dev/null"]
        onNewData: function(source, data) {
            var text = data["stdout"] || ""
            var lines = text.split("\n")
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i].trim()
                if (line.indexOf("PROJECT_DIR=") === 0) {
                    pollingConfigRoot.projectDir = line.substring("PROJECT_DIR=".length).trim()
                } else if (line.indexOf("UV=") === 0) {
                    var v = line.substring("UV=".length).trim()
                    if (v.length > 0) pollingConfigRoot.uvPath = v
                }
            }
            disconnectSource(source)
        }
    }

    // Runs login / save-token actions.
    Plasma5Support.DataSource {
        id: actionExec
        engine: "executable"
        connectedSources: []
        onNewData: function(source, data) {
            var out = (data["stdout"] || "").trim()
            var err = (data["stderr"] || "").trim()
            if (err.length > 0 && out.length === 0) {
                statusLabel.text = "⚠ " + err
            } else if (out.length > 0) {
                statusLabel.text = out.split("\n").pop()
            } else {
                statusLabel.text = "完成"
            }
            disconnectSource(source)
        }
    }

    QQC2.ScrollView {
        id: pollingScroll
        anchors.fill: parent
        clip: true
        QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AsNeeded
        QQC2.ScrollBar.vertical.policy: QQC2.ScrollBar.AsNeeded

    Kirigami.FormLayout {
        id: pollingForm
        // Grow to the viewport when there is room, otherwise keep the natural
        // width so the horizontal scrollbar appears on small windows.
        width: Math.max(implicitWidth, pollingScroll.availableWidth)

        QQC2.CheckBox {
            id: enablePollingCheck
            Kirigami.FormData.label: "数据抓取:"
            text: "启用自动数据抓取"
        }

        QQC2.Label {
            Kirigami.FormData.label: ""
            text: "启用后，插件会按照设定间隔自动抓取各平台的用量数据"
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.WordWrap
        }

        Kirigami.Separator { Kirigami.FormData.isSection: true }

        QQC2.SpinBox {
            id: intervalSpin
            Kirigami.FormData.label: "抓取间隔:"
            from: 60
            to: 3600
            stepSize: 60
            textFromValue: function(value, locale) { return value + " 秒" }
            valueFromText: function(text, locale) { return parseInt(text) }
            enabled: enablePollingCheck.checked
        }

        QQC2.Label {
            Kirigami.FormData.label: ""
            text: "建议 300 秒（5 分钟）或更长，避免过于频繁的请求"
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.WordWrap
        }

        Kirigami.Separator { Kirigami.FormData.isSection: true }

        QQC2.Label {
            Kirigami.FormData.label: "数据提供商:"
            text: "勾选要监控的服务，选择抓取方式，并完成登录或录入 Token"
            color: Kirigami.Theme.textColor
        }

        ColumnLayout {
            Kirigami.FormData.label: ""
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing

            ProviderRow {
                id: rowCodex
                Layout.fillWidth: true
                providerId: "codex"
                providerName: "OpenAI Codex"
                browserOnly: true
                noteBrowser: "仅支持浏览器登录抓取"
                onToggledEnabled: pollingConfigRoot.rebuildProviders()
                onRequestLogin: pollingConfigRoot.runLogin(providerId)
                onRequestCopy: function(t) { pollingConfigRoot.copyCommand(t) }
            }

            ProviderRow {
                id: rowClaude
                Layout.fillWidth: true
                providerId: "claude"
                providerName: "Claude Code"
                canToken: true
                tokenOptional: true
                method: claudeMethodField.text || "browser"
                noteBrowser: "浏览器登录：打开 claude.ai 手动登录"
                noteDirect: "直连可自动读取 ~/.claude/.credentials.json，无需手动填 Token"
                onToggledEnabled: pollingConfigRoot.rebuildProviders()
                onPickedMethod: function(v) { claudeMethodField.text = v }
                onRequestLogin: pollingConfigRoot.runLogin(providerId)
                onRequestSaveToken: function(tok) { pollingConfigRoot.saveToken(providerId, tok) }
                onRequestCopy: function(t) { pollingConfigRoot.copyCommand(t) }
            }

            ProviderRow {
                id: rowKimi
                Layout.fillWidth: true
                providerId: "kimi"
                providerName: "Kimi"
                canToken: true
                method: kimiMethodField.text || "direct"
                noteBrowser: "浏览器登录：打开 kimi.com 手动登录"
                noteDirect: "直连需 Kimi Code Token，粘贴后点「保存 Token」（写入 secrets.env，0600）"
                onToggledEnabled: pollingConfigRoot.rebuildProviders()
                onPickedMethod: function(v) { kimiMethodField.text = v }
                onRequestLogin: pollingConfigRoot.runLogin(providerId)
                onRequestSaveToken: function(tok) { pollingConfigRoot.saveToken(providerId, tok) }
                onRequestCopy: function(t) { pollingConfigRoot.copyCommand(t) }
            }

            ProviderRow {
                id: rowMinimax
                Layout.fillWidth: true
                providerId: "minimax"
                providerName: "MiniMax"
                canToken: true
                tokenOptional: true
                method: minimaxMethodField.text || "direct"
                noteBrowser: "浏览器登录：打开 platform.minimaxi.com 手动登录"
                noteDirect: "直连可用 API Key（粘贴保存）或本机 mmx CLI（可留空）"
                onToggledEnabled: pollingConfigRoot.rebuildProviders()
                onPickedMethod: function(v) { minimaxMethodField.text = v }
                onRequestLogin: pollingConfigRoot.runLogin(providerId)
                onRequestSaveToken: function(tok) { pollingConfigRoot.saveToken(providerId, tok) }
                onRequestCopy: function(t) { pollingConfigRoot.copyCommand(t) }
            }
        }

        QQC2.Label {
            id: statusLabel
            Kirigami.FormData.label: "状态:"
            Layout.fillWidth: true
            text: "就绪"
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.WordWrap
            visible: text.length > 0
        }

        // Hidden persisted state (driven by the rows above).
        QQC2.TextField { id: providersField; visible: false }
        QQC2.TextField { id: claudeMethodField; visible: false; text: "browser" }
        QQC2.TextField { id: kimiMethodField; visible: false; text: "direct" }
        QQC2.TextField { id: minimaxMethodField; visible: false; text: "direct" }

        QQC2.Label {
            Kirigami.FormData.label: ""
            text: "密钥只写入 secrets.env（权限 0600），绝不写入插件配置。「一键登录」会打开隔离浏览器，登录后关闭窗口即保存。"
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
        }
    }
    }

    TextInput { id: clipboardInput; visible: false }

    Component.onCompleted: {
        applyProvidersString(providersField.text)
    }
}
