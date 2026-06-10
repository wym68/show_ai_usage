import QtQuick
import org.kde.plasma.configuration

ConfigModel {
    ConfigCategory {
        name: "General"
        icon: "preferences-system"
        source: "config/GeneralConfig.qml"
    }
    ConfigCategory {
        name: "Display"
        icon: "preferences-desktop-display"
        source: "config/DisplayConfig.qml"
    }
    ConfigCategory {
        name: "Advanced"
        icon: "preferences-other"
        source: "config/AdvancedConfig.qml"
    }
}
