import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM
import org.kde.plasma.plasmoid

KCM.AbstractKCM {
    property alias cfg_refreshInterval: refreshIntervalSpin.value
    property alias cfg_staleThreshold: staleThresholdSpin.value

    Kirigami.FormLayout {
        QQC2.SpinBox {
            id: refreshIntervalSpin
            Kirigami.FormData.label: "界面刷新间隔（秒）:"
            from: 10
            to: 3600
            stepSize: 10
        }

        QQC2.SpinBox {
            id: staleThresholdSpin
            Kirigami.FormData.label: "数据过期阈值（秒）:"
            from: 60
            to: 86400
            stepSize: 60
        }

        QQC2.Label {
            Kirigami.FormData.label: ""
            text: "超过过期阈值后 Plasmoid 会显示「⚠ 数据已过期」警告"
            color: Kirigami.Theme.disabledTextColor
            wrapMode: Text.WordWrap
        }
    }
}
