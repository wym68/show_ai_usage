import QtQuick
import QtQuick.Layouts
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid
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

    // ── Config-driven properties ──────────────────────────────
    readonly property int _displayMode: Plasmoid.configuration.displayMode || 0
    readonly property bool _showLabels: Plasmoid.configuration.showProviderLabels !== false
    readonly property int _maxProviders: Math.max(1, Plasmoid.configuration.compactMaxProviders || 4)

    // Filtered and truncated provider list
    readonly property var _displayProviders: {
        var list = root.providers || []
        // Apply display mode filter
        var filtered = list.filter(function(p) {
            if (p.error) return true
            var v5h = Number(p.window_5h_percent) || 0
            var v7d = Number(p.window_7d_percent) || 0
            switch (root._displayMode) {
                case 1: return !isNaN(v5h)  // 5h only
                case 2: return !isNaN(v7d)  // 7d only
                default: return true        // both
            }
        })
        // Truncate to max providers
        return filtered.slice(0, root._maxProviders)
    }

    // ── Helpers ───────────────────────────────────────────────
    function _val(p, key) {
        var v = Number(p && p[key])
        return isNaN(v) ? 0 : Math.max(0, Math.min(100, v))
    }
    function _dispVal(p) {
        if (root._displayMode === 1) return _val(p, "window_5h_percent")
        if (root._displayMode === 2) return _val(p, "window_7d_percent")
        // Auto: show 7d if > 85, else 5h (existing behaviour)
        return _val(p, "window_7d_percent") > 85
            ? _val(p, "window_7d_percent") : _val(p, "window_5h_percent")
    }
    function _is7d(p) { return _val(p, "window_7d_percent") > 85 }
    function _color(v) {
        // Use color theme from config
        var theme = Plasmoid.configuration.colorTheme || 0
        if (theme === 1) { // Colorblind-friendly palette
            return v >= 95 ? "#9C27B0" : v >= 80 ? "#F44336" : v >= 50 ? "#FF9800" : "#2196F3"
        }
        // Custom colors
        if (theme === 2) {
            var cLow = Plasmoid.configuration.customColorLow || "#4CAF50"
            var cMid = Plasmoid.configuration.customColorMid || "#FFC107"
            var cHigh = Plasmoid.configuration.customColorHigh || "#FF9800"
            var cCrit = Plasmoid.configuration.customColorCritical || "#F44336"
            return v >= 95 ? cCrit : v >= 80 ? cHigh : v >= 50 ? cMid : cLow
        }
        // Default palette
        return v >= 95 ? "#F44336" : v >= 80 ? "#FF9800" : v >= 50 ? "#FFC107" : "#4CAF50"
    }
    function _label(p) {
        var m = {"codex":"O", "claude":"C", "kimi":"K", "minimax":"M"}
        return p && p.provider ? (m[p.provider] || "?") : "?"
    }

    // ── Pills ─────────────────────────────────────────────────
    RowLayout {
        anchors.centerIn: parent
        width: root.width > 0 ? root.width : root.implicitWidth
        height: root._pillH
        spacing: root._gap
        visible: root._displayProviders.length > 0

        Repeater {
            model: root._displayProviders

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
                    text: {
                        var label = root._showLabels ? (root._label(parent._prov) + "  ") : ""
                        return label + Math.round(parent._val) + "%"
                    }
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
        visible: root._displayProviders.length === 0
        text: root.errorMessage ? "N/A" : "⋯"
        color: Kirigami.Theme.textColor
        font.pixelSize: Kirigami.Theme.defaultFont.pixelSize
    }
}
