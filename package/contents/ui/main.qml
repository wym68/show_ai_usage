import QtQuick
import QtQuick.Layouts
import QtCore
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: root

    property var usageData: ({ "providers": [] })
    property var providers: usageData && usageData.providers ? usageData.providers : []
    property string errorMessage: ""
    readonly property string dataFileUrl: "file://" + StandardPaths.writableLocation(StandardPaths.GenericDataLocation) + "/show-ai-usage/data.json"

    function loadUsageData() {
        var request = new XMLHttpRequest()
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) {
                return
            }

            if (request.status !== 0 && request.status !== 200) {
                root.errorMessage = "无法读取数据文件: " + request.status
                root.usageData = { "providers": [] }
                return
            }

            if (!request.responseText || request.responseText.trim().length === 0) {
                root.errorMessage = "数据文件为空"
                root.usageData = { "providers": [] }
                return
            }

            try {
                var parsed = JSON.parse(request.responseText)
                root.usageData = parsed || { "providers": [] }
                root.errorMessage = ""
            } catch (error) {
                root.errorMessage = "数据格式错误: " + error
                root.usageData = { "providers": [] }
            }
        }

        request.open("GET", root.dataFileUrl, true)
        request.send()
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
        interval: 60000
        running: true
        repeat: true
        onTriggered: root.loadUsageData()
    }

    Component.onCompleted: root.loadUsageData()
}
