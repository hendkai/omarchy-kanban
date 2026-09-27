import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

// Detail popup for kanban-progress, modeled on the installed working
// dizziee.system-updates popup: the visible window is a KeyboardPanel
// (real layer-shell PanelWindow from qs.Ui) — qs.Ui.Panel itself is only
// an Item owning the open/close controller. One section per machine with
// state, heartbeat age, board task counts (board completion, explicitly
// NOT task percent), and running/review/blocked/ready titles. Content is
// capped to the screen and scrolls when a host has many boards.
Panel {
  id: root
  moduleName: "hendkai.kanban-progress"
  ipcTarget: "hendkai.kanban-progress"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null

  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(fg, 1.5)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // Palette matches the chips regardless of theme.
  readonly property color pcColor: hostWidget ? hostWidget.pcColor : "#45d6c5"
  readonly property color macColor: hostWidget ? hostWidget.macColor : "#bd93f9"

  function openAndRefresh() {
    open()
    if (hostWidget && hostWidget.refresh) hostWidget.refresh()
  }

  readonly property real wantedHeight: contentColumn.implicitHeight + 24

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: 560
    contentHeight: panel.fittedContentHeight(root.wantedHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTextKey: function(t) {
        if (t === "r" || t === "R") root.openAndRefresh()
      }

      ColumnLayout {
        id: outerColumn
        anchors.fill: parent
        spacing: 10

        // ---- header (fixed; always visible) ---------------------------
        RowLayout {
          Layout.fillWidth: true
          Layout.leftMargin: 12
          Layout.rightMargin: 12
          Layout.topMargin: 10
          Text {
            text: qsTr("Kanban status")
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
            Layout.fillWidth: true
          }
          Text {
            visible: hostWidget && (hostWidget.loadingPc || hostWidget.loadingMac)
            text: qsTr("refreshing…")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }

        PanelSeparator {
          Layout.fillWidth: true
          Layout.leftMargin: 12
          Layout.rightMargin: 12
          foreground: root.fg
        }

        // ---- scrollable body -------------------------------------------
        Flickable {
          id: scroll
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.leftMargin: 12
          Layout.rightMargin: 12
          Layout.bottomMargin: 10
          contentWidth: width
          contentHeight: contentColumn.implicitHeight
          clip: true
          boundsBehavior: Flickable.StopAtBounds

          ColumnLayout {
            id: contentColumn
            width: scroll.width
            spacing: 10

            HostSection {
              Layout.fillWidth: true
              title: hostWidget && hostWidget.strSetting
                ? hostWidget.strSetting("labelPc", "Local") : "Local"
              machineColor: root.pcColor
              hostWidget: root.hostWidget
              hostKey: "pc"
              fontFamily: root.fontFamily
              fg: root.fg
              dim: root.dim
            }

            HostSection {
              Layout.fillWidth: true
              visible: hostWidget === null
                || hostWidget.setting("showMac", true) === true
              title: hostWidget && hostWidget.strSetting
                ? hostWidget.strSetting("labelMac", "Remote") : "Remote"
              machineColor: root.macColor
              hostWidget: root.hostWidget
              hostKey: "mac"
              fontFamily: root.fontFamily
              fg: root.fg
              dim: root.dim
            }

            Text {
              Layout.fillWidth: true
              Layout.topMargin: 2
              text: qsTr("r refreshes · Esc closes · counts are board progress, not task percentages")
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }
          }
        }
      }
    }
  }

  // IPC: exactly one IpcHandler owns the "hendkai.kanban-progress" target —
  // the BarWidget (manageIpc: false here). It exposes open/close/toggle/
  // refresh plus `status`, a live JSON readback of both hosts:
  //   quickshell ipc -p /usr/share/omarchy/shell call hendkai.kanban-progress status

  component HostSection: BorderSurface {
    id: section
    property string title: "Local"
    property color machineColor: "#45d6c5"
    property var hostWidget: null
    property string hostKey: "pc"
    property string fontFamily: ""
    property color fg: "white"
    property color dim: "gray"

    // Named hostState (not "state"): "state" collides with Item.state.
    readonly property var boards: hostWidget ? hostWidget.boardsOf(hostKey) : []
    readonly property string hostState: hostWidget ? hostWidget.hostState(hostKey) : "loading"
    readonly property int running: hostWidget ? hostWidget.runningCount(hostKey) : 0
    readonly property var totals: hostWidget ? hostWidget.boardTotals(hostKey) : { done: 0, total: 0 }
    readonly property int hbAge: hostWidget ? hostWidget.heartbeatAgeSec(hostKey) : -1
    readonly property string fresh: hostWidget ? hostWidget.hostFresh(hostKey) : "none"

    Layout.fillWidth: true
    color: Qt.rgba(machineColor.r, machineColor.g, machineColor.b, 0.06)
    borderSpec: Border.flat(Qt.alpha(machineColor, 0.35), 1)
    radius: Style.cornerRadius
    padding: 10

    implicitHeight: sectionBody.implicitHeight + contentTopInset + contentBottomInset

    function stateLabel(st) {
      if (st === "loading") return qsTr("loading…")
      if (st === "disabled") return qsTr("not configured")
      if (st === "offline") return qsTr("offline")
      if (st === "error") return qsTr("error")
      if (st === "schema") return qsTr("schema mismatch")
      if (st === "empty") return qsTr("no boards / tasks")
      return qsTr("connected")
    }

    ColumnLayout {
      id: sectionBody
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.leftMargin: section.contentLeftInset
      anchors.rightMargin: section.contentRightInset
      anchors.topMargin: section.contentTopInset
      spacing: 6

      RowLayout {
        Layout.fillWidth: true
        spacing: 8

        Rectangle {
          width: 10; height: 10; radius: 5
          color: section.machineColor
          opacity: section.hostState === "ok" ? 1 : 0.4
        }
        Text {
          text: section.title
          color: section.machineColor
          font.family: section.fontFamily
          font.pixelSize: Style.font.subtitle
          font.bold: true
        }
        Text {
          Layout.fillWidth: true
          text: section.stateLabel(section.hostState)
          color: section.hostState === "ok" ? section.dim : section.fg
          font.family: section.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
        Text {
          visible: section.hostState === "ok" && section.hbAge >= 0
          text: (section.fresh === "stale" ? qsTr("Stale") + " · " : "♥ ")
            + (section.hostWidget ? section.hostWidget.fmtAge(section.hbAge) : "–")
            + (section.fresh === "stale" ? " · " + qsTr("unknown heartbeat") : "")
          color: section.fresh === "stale" ? section.fg : section.dim
          font.family: section.fontFamily
          font.pixelSize: Style.font.caption
        }
        Text {
          visible: section.hostState === "ok"
          text: section.running > 0 ? section.running + qsTr(" running") : qsTr("nothing running")
          color: section.running > 0 ? section.fg : section.dim
          font.family: section.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: section.running > 0
        }
      }

      // Board counts row: chips per board with counts (board completion).
      // modelData.total comes from the collector and excludes cancelled/
      // archived — the same denominator boardTotals() uses in QML.
      Flow {
        visible: section.hostState === "ok"
        Layout.fillWidth: true
        spacing: 6

        Repeater {
          model: section.boards

          delegate: Rectangle {
            id: boardChip
            required property var modelData
            readonly property bool okBoard: modelData && modelData.ok === true
            readonly property var counts: okBoard && modelData.status_counts ? modelData.status_counts : null
            width: boardRow.implicitWidth + 16
            height: 24
            radius: 6
            color: okBoard
              ? Qt.rgba(section.machineColor.r, section.machineColor.g, section.machineColor.b, 0.08)
              : Qt.rgba(1, 0, 0, 0.06)
            border.color: okBoard
              ? Qt.alpha(section.machineColor, 0.3)
              : Qt.alpha("#a55555", 0.6)
            border.width: 1

            Row {
              id: boardRow
              anchors.centerIn: parent
              spacing: 5
              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: boardChip.modelData ? String(boardChip.modelData.name) : ""
                textFormat: Text.PlainText
                color: section.fg
                font.family: section.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }
              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: {
                  if (!counts) return boardChip.modelData && boardChip.modelData.error === "schema" ? qsTr("schema?") : qsTr("IO")
                  var parts = []
                  if (counts.running) parts.push("▶" + counts.running)
                  if (counts.review) parts.push("▶" + counts.review)
                  if (counts.blocked) parts.push("⛔" + counts.blocked)
                  if (counts.ready) parts.push("◇" + counts.ready)
                  var done = (counts.done || 0) + (counts.completed || 0)
                  var tracked = boardChip.modelData && typeof boardChip.modelData.total === "number"
                    ? boardChip.modelData.total : 0
                  parts.push(done + "/" + tracked)
                  return parts.join(" ")
                }
                color: section.dim
                font.family: section.fontFamily
                font.pixelSize: Style.font.caption
              }
            }
          }
        }
      }

      // Active titles grouped by status (running first, ready included)
      ColumnLayout {
        visible: section.hostState === "ok"
        spacing: 2
        Layout.fillWidth: true

        Repeater {
          model: {
            var out = []
            var boards = section.boards
            var order = ["running", "review", "blocked", "ready"]
            for (var o = 0; o < order.length; o++) {
              for (var i = 0; i < boards.length; i++) {
                var b = boards[i]
                if (!b.ok || !b.active) continue
                for (var j = 0; j < b.active.length; j++) {
                  var t = b.active[j]
                  if (t.status === order[o])
                    out.push({ title: t.title, status: t.status, board: b.name })
                }
              }
            }
            return out.slice(0, 20)
          }

          delegate: RowLayout {
            id: titleRow
            required property var modelData
            Layout.fillWidth: true
            spacing: 6
            Text {
              text: titleRow.modelData.status === "running" ? "▶"
                : titleRow.modelData.status === "review" ? "👁"
                : titleRow.modelData.status === "blocked" ? "⛔" : "◇"
              color: section.machineColor
              font.family: section.fontFamily
              font.pixelSize: Style.font.caption
            }
            Text {
              Layout.fillWidth: true
              text: titleRow.modelData.title
              color: section.fg
              font.family: section.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
              textFormat: Text.PlainText
            }
            Text {
              text: titleRow.modelData.board
              textFormat: Text.PlainText
              color: section.dim
              font.family: section.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }
      }

      // Board progress line (explicit: NOT task percent)
      Text {
        visible: section.hostState === "ok" && totals.total > 0
        Layout.fillWidth: true
        text: qsTr("Board progress: ") + totals.done + "/" + totals.total
          + qsTr(" done (board counts, cancelled excluded — not task percentages)")
        color: section.dim
        font.family: section.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
  }
}
