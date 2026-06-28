import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kde.plasma.plasmoid

KCM.AbstractKCM {
    property alias cfg_displayMode: displayModeCombo.currentIndex
    property alias cfg_showProviderLabels: showLabelsCheck.checked
    property alias cfg_compactMaxProviders: maxProvidersSpin.value
    property alias cfg_compactPillWidth: pillWidthSpin.value

    QQC2.ScrollView {
        id: displayScroll
        anchors.fill: parent
        clip: true
        QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AsNeeded
        QQC2.ScrollBar.vertical.policy: QQC2.ScrollBar.AsNeeded

    Kirigami.FormLayout {
        width: Math.max(implicitWidth, displayScroll.availableWidth)

        QQC2.ComboBox {
            id: displayModeCombo
            Kirigami.FormData.label: "显示模式:"
            model: ["5h + 7d 都显示", "仅 5h", "仅 7d"]
        }

        QQC2.CheckBox {
            id: showLabelsCheck
            Kirigami.FormData.label: "紧凑标签:"
            text: "显示 provider 字母标签"
        }

        QQC2.SpinBox {
            id: maxProvidersSpin
            Kirigami.FormData.label: "最大显示数:"
            from: 1
            to: 8
        }

        QQC2.Label {
            Kirigami.FormData.label: ""
            text: "超出最大显示数的 provider 将被折叠"
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.WordWrap
        }

        QQC2.SpinBox {
            id: pillWidthSpin
            Kirigami.FormData.label: "每项宽度:"
            from: 2
            to: 12
        }

        QQC2.Label {
            Kirigami.FormData.label: ""
            text: "紧凑模式中单个 provider 的宽度（gridUnit 倍数），总宽 = 个数 × 此值"
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.WordWrap
        }
    }
    }
}
