import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kde.plasma.plasmoid

KCM.AbstractKCM {
    property alias cfg_dataFilePath: dataFilePathField.text
    property alias cfg_colorTheme: colorThemeCombo.currentIndex
    property alias cfg_customColorLow: colorLowField.text
    property alias cfg_customColorMid: colorMidField.text
    property alias cfg_customColorHigh: colorHighField.text
    property alias cfg_customColorCritical: colorCriticalField.text

    Kirigami.FormLayout {
        // ── Data path ─────────────────────────────────────────
        QQC2.TextField {
            id: dataFilePathField
            Kirigami.FormData.label: "自定义数据路径:"
            placeholderText: "auto"
        }

        QQC2.Label {
            Kirigami.FormData.label: ""
            text: "留空或填 auto 使用默认路径 (~/.local/share/show-ai-usage/data.json)"
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.WordWrap
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "颜色自定义"
        }

        // ── Color theme selector ──────────────────────────────
        QQC2.ComboBox {
            id: colorThemeCombo
            Kirigami.FormData.label: "配色方案:"
            model: ["默认（绿/黄/橙/红）", "色盲友好（蓝/橙/红/紫）"]
        }

        // ── Custom color fields ───────────────────────────────
        Item {
            Kirigami.FormData.label: "0–50%:"
            Layout.fillWidth: true
            implicitHeight: colorLowField.implicitHeight

            RowLayout {
                anchors.fill: parent
                spacing: Kirigami.Units.smallSpacing

                Rectangle {
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                    radius: 2
                    color: colorLowField.text
                    border.width: 1
                    border.color: Kirigami.Theme.disabledTextColor
                }

                QQC2.TextField {
                    id: colorLowField
                    Layout.fillWidth: true
                    placeholderText: "#4CAF50"
                }
            }
        }

        Item {
            Kirigami.FormData.label: "50–80%:"
            Layout.fillWidth: true
            implicitHeight: colorMidField.implicitHeight

            RowLayout {
                anchors.fill: parent
                spacing: Kirigami.Units.smallSpacing

                Rectangle {
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                    radius: 2
                    color: colorMidField.text
                    border.width: 1
                    border.color: Kirigami.Theme.disabledTextColor
                }

                QQC2.TextField {
                    id: colorMidField
                    Layout.fillWidth: true
                    placeholderText: "#FFC107"
                }
            }
        }

        Item {
            Kirigami.FormData.label: "80–95%:"
            Layout.fillWidth: true
            implicitHeight: colorHighField.implicitHeight

            RowLayout {
                anchors.fill: parent
                spacing: Kirigami.Units.smallSpacing

                Rectangle {
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                    radius: 2
                    color: colorHighField.text
                    border.width: 1
                    border.color: Kirigami.Theme.disabledTextColor
                }

                QQC2.TextField {
                    id: colorHighField
                    Layout.fillWidth: true
                    placeholderText: "#FF9800"
                }
            }
        }

        Item {
            Kirigami.FormData.label: "95–100%:"
            Layout.fillWidth: true
            implicitHeight: colorCriticalField.implicitHeight

            RowLayout {
                anchors.fill: parent
                spacing: Kirigami.Units.smallSpacing

                Rectangle {
                    Layout.preferredWidth: Kirigami.Units.iconSizes.small
                    Layout.preferredHeight: Kirigami.Units.iconSizes.small
                    radius: 2
                    color: colorCriticalField.text
                    border.width: 1
                    border.color: Kirigami.Theme.disabledTextColor
                }

                QQC2.TextField {
                    id: colorCriticalField
                    Layout.fillWidth: true
                    placeholderText: "#F44336"
                }
            }
        }

        QQC2.Label {
            Kirigami.FormData.label: ""
            text: "颜色仅在选择「色盲友好」或自定义时生效，格式为 #RRGGBB"
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.WordWrap
        }
    }
}
