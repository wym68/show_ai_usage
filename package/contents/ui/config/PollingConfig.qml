import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kde.plasma.plasmoid

KCM.AbstractKCM {
    id: pollingConfigRoot

    property alias cfg_pollingEnabled: enablePollingCheck.checked
    property alias cfg_pollingInterval: intervalSpin.value
    property alias cfg_enabledProviders: providersField.text

    property var providerList: [
        { id: "codex", name: "OpenAI Codex" },
        { id: "claude", name: "Claude Code" },
        { id: "kimi", name: "Kimi" },
        { id: "minimax", name: "MiniMax" }
    ]

    function updateProvidersString() {
        var checked = []
        for (var i = 0; i < providerRepeater.count; i++) {
            var checkbox = providerRepeater.itemAt(i)
            if (checkbox && checkbox.checked) {
                checked.push(providerList[i].id)
            }
        }
        providersField.text = checked.join(",")
    }

    function applyProvidersString(str) {
        var ids = str.split(",").map(function(s) { return s.trim() })
        for (var i = 0; i < providerRepeater.count; i++) {
            var checkbox = providerRepeater.itemAt(i)
            if (checkbox) {
                checkbox.checked = ids.indexOf(providerList[i].id) >= 0
            }
        }
    }

    function copyCommand(text) {
        clipboardInput.text = text
        clipboardInput.selectAll()
        clipboardInput.copy()
    }

    Kirigami.FormLayout {
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

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
        }

        QQC2.SpinBox {
            id: intervalSpin
            Kirigami.FormData.label: "抓取间隔:"
            from: 60
            to: 3600
            stepSize: 60
            textFromValue: function(value, locale) {
                return value + " 秒"
            }
            valueFromText: function(text, locale) {
                return parseInt(text)
            }
            enabled: enablePollingCheck.checked
        }

        QQC2.Label {
            Kirigami.FormData.label: ""
            text: "建议 300 秒（5 分钟）或更长，避免过于频繁的请求"
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.WordWrap
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
        }

        QQC2.Label {
            Kirigami.FormData.label: "数据提供商:"
            text: "选择要监控的服务"
            color: Kirigami.Theme.textColor
        }

        ColumnLayout {
            Kirigami.FormData.label: ""
            spacing: Kirigami.Units.smallSpacing

            Repeater {
                id: providerRepeater
                model: providerList

                RowLayout {
                    spacing: Kirigami.Units.smallSpacing

                    QQC2.CheckBox {
                        text: modelData.name
                        checked: true
                        onCheckedChanged: pollingConfigRoot.updateProvidersString()
                    }

                    Item { Layout.fillWidth: true }

                    QQC2.TextField {
                        id: cmdField
                        text: "uv run python -m poller.main --login " + modelData.id
                        readOnly: true
                        selectByMouse: true
                        Layout.preferredWidth: implicitWidth
                        background: Rectangle {
                            color: Kirigami.Theme.alternateBackgroundColor
                            radius: Kirigami.Units.smallSpacing
                        }
                    }

                    QQC2.Button {
                        text: "复制"
                        icon.name: "edit-copy"
                        flat: true
                        onClicked: {
                            pollingConfigRoot.copyCommand(cmdField.text)
                        }
                    }
                }
            }
        }

        QQC2.TextField {
            id: providersField
            visible: false
            onTextChanged: pollingConfigRoot.applyProvidersString(text)
        }

        QQC2.Label {
            Kirigami.FormData.label: ""
            text: "首次使用需要在终端中运行登录命令（点击右侧「复制」按钮，然后粘贴到终端执行）<br><b>注意:请在项目路径下运行命令。</b>"
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.WordWrap
            textFormat: Text.RichText
        }
    }

    // Hidden TextInput for clipboard operations
    TextInput {
        id: clipboardInput
        visible: false
    }

    Component.onCompleted: {
        applyProvidersString(providersField.text)
    }
}
