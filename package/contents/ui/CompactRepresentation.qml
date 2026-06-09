import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami as Kirigami

Item {
    id: root

    property var providers: []
    property string errorMessage: ""

    // ── Sizing ────────────────────────────────────────────────
    readonly property real _pillW: Kirigami.Units.gridUnit * 3.5
    readonly property real _pillH: Kirigami.Units.gridUnit * 1.0
    readonly property real _gap: Kirigami.Units.smallSpacing
    // Fixed width based on max 4 providers — Plasma panel locks widget size at startup,
    // so dynamic recalculation when data loads causes truncation.
    readonly property real _totalW: 4 * _pillW + 3 * _gap

    implicitWidth: _totalW
    implicitHeight: _pillH
    Layout.minimumWidth: _totalW
    Layout.preferredWidth: _totalW
    Layout.maximumWidth: _totalW
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
    function _is7d(p) {
        return _val(p, "window_7d_percent") > 85
    }
    function _color(v) {
        return v >= 95 ? "#F44336" : v >= 80 ? "#FF9800" : v >= 50 ? "#FFC107" : "#4CAF50"
    }
    function _label(p) {
        var m = {"codex":"C", "claude":"D", "kimi":"K", "minimax":"M"}
        return p && p.provider ? (m[p.provider] || "?") : "?"
    }
    function _fullName(p) {
        var m = {"codex":"OpenAI Codex", "claude":"Claude Code", "kimi":"Kimi", "minimax":"MiniMax"}
        return p && p.provider ? (m[p.provider] || p.provider) : "未知服务"
    }

    // ── Content ───────────────────────────────────────────────
    RowLayout {
        id: pillRow
        anchors.centerIn: parent
        width: root.width
        height: root._pillH
        spacing: root._gap
        visible: root.providers && root.providers.length > 0

        Repeater {
            model: root.providers || []

            Rectangle {
                id: pill

                readonly property var _prov: modelData
                readonly property real _val: root._dispVal(_prov)
                readonly property bool _is7d: root._is7d(_prov)

                Layout.fillWidth: true
                Layout.preferredHeight: root._pillH
                radius: height / 2

                // Base: usage color
                color: root._color(_val)
                opacity: 0.9

                // Unused overlay
                Rectangle {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: parent.width * (100 - parent._val) / 100
                    radius: parent.radius
                    color: Kirigami.Theme.backgroundColor
                    opacity: 0.4
                }

                // Provider + Percentage label
                Text {
                    anchors.centerIn: parent
                    text: root._label(parent._prov) + " " + Math.round(parent._val) + "%"
                    color: "white"
                    font.pixelSize: Math.max(7, Math.round(parent.height * 0.42))
                    font.bold: true
                    style: Text.Outline
                    styleColor: "black"
                }

                // 7d dot (top-right corner)
                Rectangle {
                    anchors.right: parent.right; anchors.top: parent.top
                    anchors.margins: 1
                    width: 4; height: 4; radius: 2
                    visible: parent._is7d
                    color: "#FFFFFF"
                    border.color: "black"
                    border.width: 1
                }

                // Tooltip
                MouseArea {
                    id: _mouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onPressed: mouse.accepted = false
                    onReleased: mouse.accepted = false
                }
                Controls.ToolTip {
                    parent: pill
                    visible: _mouse.containsMouse
                    delay: 500
                    timeout: 5000
                    text: _prov && _prov.error
                        ? root._fullName(_prov) + ": " + _prov.error
                        : root._fullName(_prov) + " "
                          + (root._is7d(_prov) ? "7d" : "5h") + ": "
                          + Math.round(root._dispVal(_prov)) + "%"
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

        MouseArea {
            id: _emptyMouse
            anchors.fill: parent
            hoverEnabled: true
            onPressed: mouse.accepted = false
            onReleased: mouse.accepted = false
        }
        Controls.ToolTip {
            parent: parent
            visible: _emptyMouse.containsMouse
            delay: 500
            timeout: 5000
            text: root.errorMessage || "等待数据…"
        }
    }
}