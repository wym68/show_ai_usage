import QtQuick
import QtQuick.Layouts
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami as Kirigami

Item {
    id: root

    property var providers: []
    property string errorMessage: ""

    readonly property real _pillH: Kirigami.Units.gridUnit * 1.4
    readonly property real _gap: Kirigami.Units.smallSpacing

    implicitWidth:  4 * Kirigami.Units.gridUnit * 4 + 3 * _gap
    implicitHeight: _pillH
    clip: true

    // ── Helpers ───────────────────────────────────────────────
    function _val(p, key) {
        var v = Number(p && p[key])
        return isNaN(v) ? 0 : Math.max(0, Math.min(100, v))
    }
    function _dispVal(p) {
        return _val(p, "window_7d_percent") > 85
            ? _val(p, "window_7d_percent") : _val(p, "window_5h_percent")
    }
    function _is7d(p) { return _val(p, "window_7d_percent") > 85 }
    function _color(v) {
        return v >= 95 ? "#F44336" : v >= 80 ? "#FF9800" : v >= 50 ? "#FFC107" : "#4CAF50"
    }
    function _label(p) {
        var m = {"codex":"C", "claude":"D", "kimi":"K", "minimax":"M"}
        return p && p.provider ? (m[p.provider] || "?") : "?"
    }

    // ── Pills ─────────────────────────────────────────────────
    RowLayout {
        anchors.centerIn: parent
        width: root.width > 0 ? root.width : root.implicitWidth
        height: root._pillH
        spacing: root._gap
        visible: root.providers && root.providers.length > 0

        Repeater {
            model: root.providers || []

            Rectangle {
                readonly property var _prov: modelData
                readonly property real _val: root._dispVal(_prov)
                readonly property bool _is7d: root._is7d(_prov)

                Layout.fillWidth: true
                Layout.preferredHeight: root._pillH
                radius: height / 2
                color: root._color(_val)
                opacity: 0.9

                Rectangle {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: parent.width * (100 - parent._val) / 100
                    radius: parent.radius
                    color: Kirigami.Theme.backgroundColor
                    opacity: 0.4
                }

                Text {
                    anchors.centerIn: parent
                    text: root._label(parent._prov) + "  " + Math.round(parent._val) + "%"
                    color: "white"
                    font.pixelSize: Math.max(10, Math.round(parent.height * 0.56))
                    font.bold: true
                    style: Text.Outline
                    styleColor: "black"
                }

                Rectangle {
                    anchors.right: parent.right; anchors.top: parent.top
                    anchors.margins: 1
                    width: 4; height: 4; radius: 2
                    visible: parent._is7d
                    color: "#FFFFFF"
                    border.color: "black"
                    border.width: 1
                }
            }
        }
    }

    // ── Empty state ───────────────────────────────────────────
    Text {
        anchors.centerIn: parent
        visible: !root.providers || root.providers.length === 0
        text: root.errorMessage ? "N/A" : "⋯"
        color: Kirigami.Theme.textColor
        font.pixelSize: Kirigami.Theme.defaultFont.pixelSize
    }
}
