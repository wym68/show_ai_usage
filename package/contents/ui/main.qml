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
    // These Layout properties live on the PlasmoidItem itself, which IS the direct
    // child of the panel's RowLayout — this is the correct place, not CompactRepresentation.
    Layout.minimumWidth: 4 * Kirigami.Units.gridUnit * 3 + 3 * Kirigami.Units.smallSpacing
    Layout.preferredWidth: 4 * Kirigami.Units.gridUnit * 4 + 3 * Kirigami.Units.smallSpacing

    property var usageData: ({ "providers": [] })
    property var providers: usageData && usageData.providers ? usageData.providers : []
    property string errorMessage: ""
    // StandardPaths.writableLocation returns a file:// URL like "file:///home/user/.local/share"
    readonly property string dataFileUrl: StandardPaths.writableLocation(StandardPaths.GenericDataLocation) + "/show-ai-usage/data.json"
    // Bare filesystem path for shell commands (strip file:// prefix)
    readonly property string dataFilePath: {
        var url = dataFileUrl.toString()
        return url.substring(0, 7) === "file://" ? url.substring(7) : url
    }

    // Read data file via the executable dataengine (works in both plasmawindowed and panel)
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
        fileReader.connectSource("cat " + root.dataFilePath)
    }

    compactRepresentation: CompactRepresentation {
        providers: root.providers
        errorMessage: root.errorMessage
    }

    fullRepresentation: FullRepresentation {
        usageData: root.usageData
        providers: root.providers
        errorMessage: root.errorMessage
        dataFileUrl: root.dataFileUrl
    }

    Timer {
        id: refreshTimer
        interval: (Plasmoid.configuration.refreshInterval || 60) * 1000
        running: true
        repeat: true
        onTriggered: root.loadUsageData()
    }

    Component.onCompleted: root.loadUsageData()
}
