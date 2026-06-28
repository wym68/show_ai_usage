import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami

// One provider's row: enable checkbox + fetch-method selector, with a
// reactive command preview, optional token input, and a one-click login
// button. Emits signals; the parent owns persistence and command execution.
ColumnLayout {
    id: row

    // ── Inputs (set by parent) ────────────────────────────────────
    property string providerId
    property string providerName
    property bool browserOnly: false        // codex: no direct path
    property bool canToken: false            // direct path accepts a token
    property bool tokenOptional: false       // token can be auto-detected
    property string noteBrowser: ""
    property string noteDirect: ""

    // ── State ─────────────────────────────────────────────────────
    property bool enabledState: true
    property string method: browserOnly ? "browser" : "direct"

    // ── Derived (reactive) ───────────────────────────────────────
    readonly property string effectiveMethod: browserOnly ? "browser" : method
    readonly property string command: effectiveMethod === "direct"
        ? "uv run python -m poller.main --set-token " + providerId
        : "uv run python -m poller.main --login " + providerId
    readonly property string note: effectiveMethod === "direct" ? noteDirect : noteBrowser

    // ── Signals ───────────────────────────────────────────────────
    signal toggledEnabled(bool checked)
    signal pickedMethod(string value)
    signal requestLogin()
    signal requestSaveToken(string token)
    signal requestCopy(string text)

    Layout.fillWidth: true
    spacing: Kirigami.Units.smallSpacing

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing

        QQC2.CheckBox {
            text: row.providerName
            checked: row.enabledState
            onToggled: {
                row.enabledState = checked
                row.toggledEnabled(checked)
            }
            Layout.minimumWidth: Kirigami.Units.gridUnit * 8
        }

        QQC2.ComboBox {
            visible: !row.browserOnly
            enabled: row.enabledState
            textRole: "label"
            valueRole: "value"
            model: [
                { label: "浏览器登录", value: "browser" },
                { label: "直连 API",  value: "direct" }
            ]
            currentIndex: row.method === "direct" ? 1 : 0
            onActivated: {
                row.method = currentValue
                row.pickedMethod(currentValue)
            }
            Layout.preferredWidth: Kirigami.Units.gridUnit * 8
        }

        QQC2.Label {
            visible: row.browserOnly
            text: "浏览器登录"
            color: Kirigami.Theme.disabledTextColor
            Layout.preferredWidth: Kirigami.Units.gridUnit * 8
        }

        Item { Layout.fillWidth: true }
    }

    // Command preview + copy
    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.gridUnit
        spacing: Kirigami.Units.smallSpacing

        QQC2.TextField {
            id: cmdField
            text: row.command
            readOnly: true
            selectByMouse: true
            Layout.fillWidth: true
            background: Rectangle {
                color: Kirigami.Theme.alternateBackgroundColor
                radius: Kirigami.Units.smallSpacing
            }
        }

        QQC2.Button {
            text: "复制"
            icon.name: "edit-copy"
            flat: true
            onClicked: row.requestCopy(cmdField.text)
        }
    }

    // Action area: one-click login (browser) or token input (direct)
    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.gridUnit
        spacing: Kirigami.Units.smallSpacing
        visible: row.enabledState

        // Browser method → one-click login button.
        QQC2.Button {
            visible: row.effectiveMethod === "browser"
            text: "一键登录"
            icon.name: "user-identity"
            onClicked: row.requestLogin()
        }

        // Direct method with a token → password field + save.
        QQC2.TextField {
            id: tokenField
            visible: row.effectiveMethod === "direct" && row.canToken
            echoMode: TextInput.Password
            placeholderText: row.tokenOptional ? "Token（可留空，自动检测）" : "粘贴 Token"
            Layout.fillWidth: true
        }

        QQC2.Button {
            visible: row.effectiveMethod === "direct" && row.canToken
            text: "保存 Token"
            icon.name: "document-save"
            enabled: tokenField.text.length > 0
            onClicked: {
                row.requestSaveToken(tokenField.text)
                tokenField.text = ""
            }
        }
    }

    QQC2.Label {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.gridUnit
        text: row.note
        color: Kirigami.Theme.disabledTextColor
        font: Kirigami.Theme.smallFont
        wrapMode: Text.WordWrap
        visible: text.length > 0
    }
}
