import QtQuick
import Quickshell.Io
import qs.Ui
import qs.Commons

// Kanban Progress — two compact chips (Local turquoise, Remote violet).
// Data comes from poll.py: ONE bounded subprocess PER HOST, so an offline
// remote never delays or wipes the local result. Chips show the current running
// task title (rotating ~8s when multiple) and the running count; when
// nothing runs but work waits, they show "N blocked"/"N ready".
// No percentages are ever shown: status/heartbeat cannot express progress,
// so a slim indeterminate activity bar marks real running work only.
// Board-count completion ("X/Y erledigt") appears in the popup as explicit
// "Board progress" — a count, never task percent.
BarWidget {
  id: root
  moduleName: "hendkai.kanban-progress"

  // Machine accent colors: settings pcColor/macColor accept #rrggbb; the
  // fallbacks are the fixed defaults. Independent of theme (theme colors text).
  function colorSetting(name, fallback) {
    var v = String(setting(name) || "")
    return /^#[0-9a-fA-F]{6}$/.test(v) ? v : fallback
  }
  readonly property color pcColor: colorSetting("pcColor", "#45d6c5")
  readonly property color macColor: colorSetting("macColor", "#bd93f9")
  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property color dimText: Qt.alpha(fg, 0.62)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // ---- settings ----------------------------------------------------------
  function intSetting(name, fallback, min, max) {
    var v = Number(setting(name))
    if (!isFinite(v)) v = Number(fallback)
    if (!isFinite(v)) v = min
    return Math.max(min, Math.min(max, Math.round(v)))
  }
  function strSetting(name, fallback) {
    var v = setting(name)
    v = (v === undefined || v === null || String(v) === "") ? fallback : String(v)
    return v.replace(/[<>]/g, "").substring(0, 12)
  }
  function strSettingRaw(name, fallback) {
    var v = setting(name)
    return (v === undefined || v === null || String(v).trim() === "") ? fallback : String(v).trim()
  }
  readonly property int pollMs: intSetting("pollIntervalSec", 15, 10, 300) * 1000
  readonly property int chipW: intSetting("chipWidth", 200, 90, 400)
  readonly property string labelPc: strSetting("labelPc", "Local")
  readonly property string labelMac: strSetting("labelMac", "Remote")
  readonly property bool showMac: setting("showMac", true) === true
  readonly property bool reduceMotion: setting("reduceMotion", false) === true
  // Optional non-default config path; forwarded to poll.py by both processes.
  readonly property string configPath: strSettingRaw("configPath", "")

  // ---- state -------------------------------------------------------------
  // One entry per completed host poll; each updates independently. A host
  // keeps its last data while a refresh is in flight; a failed refresh
  // marks only that host — never wipes the other.
  property var hostPc: null
  property var hostMac: null
  property bool loadingPc: false
  property bool loadingMac: false
  property real nowMs: Date.now()
  property int rotateIndex: 0

  function hostDoc(key) { return key === "pc" ? hostPc : hostMac }

  function boardsOf(key) {
    var doc = hostDoc(key)
    if (!doc || !doc.ok) return []
    return Array.isArray(doc.boards) ? doc.boards : []
  }
  function meta(key) {
    var doc = hostDoc(key)
    return doc && doc._meta ? doc._meta : { state: doc ? "ok" : "unknown" }
  }

  // running tasks across boards of one host (bounded: collector caps detail
  // lists per board, we cap the total defensively at 30)
  function runningTitles(key) {
    var out = []
    var boards = boardsOf(key)
    for (var i = 0; i < boards.length && out.length < 30; i++) {
      var b = boards[i]
      if (!b.ok || !b.active) continue
      for (var j = 0; j < b.active.length && out.length < 30; j++) {
        var t = b.active[j]
        if (t.status === "running") out.push(t.title || "")
      }
    }
    return out
  }
  function countOf(key, status) {
    var boards = boardsOf(key)
    var n = 0
    for (var i = 0; i < boards.length; i++) {
      var b = boards[i]
      if (b.ok && b.status_counts && b.status_counts[status])
        n += Math.max(0, Math.floor(b.status_counts[status]))
    }
    return n
  }
  function runningCount(key) { return countOf(key, "running") }
  function blockedCount(key) { return countOf(key, "blocked") }
  function readyCount(key) { return countOf(key, "ready") }

  // newest running heartbeat (epoch seconds), or -1
  function lastHeartbeat(key) {
    var boards = boardsOf(key)
    var best = -1
    for (var i = 0; i < boards.length; i++) {
      var b = boards[i]
      if (!b.ok) continue
      var hb = b.last_heartbeat_at
      if (typeof hb === "number" && hb > best) best = hb
    }
    return best
  }

  // Per-host display state: "loading"|"ok"|"empty"|"schema"|"offline"|"error"|"disabled"
  function hostState(key) {
    var doc = hostDoc(key)
    if (!doc) return "loading"
    var m = meta(key)
    if (m.state === "disabled") return "disabled"
    if (m.state === "offline") return "offline"
    if (m.state === "error") return "error"
    if (!doc.ok) return "error"
    var boards = boardsOf(key)
    var anyOk = false
    for (var i = 0; i < boards.length; i++) if (boards[i].ok) { anyOk = true; break }
    if (!anyOk) return boards.length === 0 ? "empty" : "schema"
    return "ok"
  }

  // Board-completion numbers (explicitly NOT task progress). Denominator
  // excludes cancelled/archived, matching collector.py exactly.
  function boardTotals(key) {
    var boards = boardsOf(key)
    var done = 0
    var total = 0
    for (var i = 0; i < boards.length; i++) {
      var b = boards[i]
      if (!b.ok || !b.status_counts) continue
      var c = b.status_counts
      done += (c.done || 0) + (c.completed || 0)
      for (var s in c) {
        if (s === "cancelled" || s === "archived") continue
        total += c[s]
      }
    }
    return { done: done, total: total }
  }

  // Rotating title per host; exactly ONE handler per property change
  // (duplicate onXChanged handlers are a QML compile error).
  property var titlesPc: []
  property var titlesMac: []
  // No index reset on new data: modulo in rotatedTitle() keeps the position
  // stable across polls instead of jumping back to the first title.
  onHostPcChanged: { titlesPc = runningTitles("pc") }
  onHostMacChanged: { titlesMac = runningTitles("mac") }
  Timer {
    interval: 8000
    running: true
    repeat: true
    onTriggered: root.rotateIndex++
  }
  function rotatedTitle(list) {
    if (!list || list.length === 0) return ""
    return list[Math.abs(rotateIndex) % list.length]
  }

  // Heartbeat freshness: stale when newest running heartbeat older than 10 min
  readonly property int staleAfterSec: 600
  Timer {
    interval: 10000
    running: true
    repeat: true
    onTriggered: root.nowMs = Date.now()
  }
  function heartbeatAgeSec(key) {
    var hb = lastHeartbeat(key)
    if (hb < 0) return -1
    return Math.max(0, Math.floor((nowMs - hb * 1000) / 1000))
  }
  function hostFresh(key) {
    // "fresh" | "stale" | "none"
    if (runningCount(key) === 0) return "none"
    var age = heartbeatAgeSec(key)
    if (age < 0) return "none"
    return age > staleAfterSec ? "stale" : "fresh"
  }

  function fmtAge(sec) {
    if (sec < 0) return "–"
    if (sec < 60) return sec + "s"
    if (sec < 3600) return Math.floor(sec / 60) + "m"
    if (sec < 86400) return Math.floor(sec / 3600) + "h"
    return Math.floor(sec / 86400) + "d"
  }

  // ---- polling: one bounded process per host, no overlap per host --------
  function refreshHost(key) {
    // Hidden remote chip: no polls are started, last data (if any) is kept.
    if (key === "mac" && !showMac) return
    if (key === "pc") {
      if (loadingPc) return
      loadingPc = true
      pcProc.running = true
    } else {
      if (loadingMac) return
      loadingMac = true
      macProc.running = true
    }
  }
  function refresh() {
    refreshHost("pc")
    refreshHost("mac")
  }
  function applyHost(key, text) {
    var doc = null
    try {
      var parsed = JSON.parse(text)
      doc = parsed.hosts && parsed.hosts[key] ? parsed.hosts[key] : null
    } catch (e) {
      doc = null
    }
    if (!doc) {
      // Parse/process failure must surface as a visible error state,
      // never perpetual loading.
      doc = { ok: false, _meta: { state: "error", detail: "no data" }, boards: [] }
    }
    if (key === "pc") { hostPc = doc; loadingPc = false }
    else { hostMac = doc; loadingMac = false }
  }
  Component.onCompleted: refresh()

  Process {
    id: pcProc
    command: root.pollCommand("pc")
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyHost("pc", text)
    }
  }
  Process {
    id: macProc
    command: root.pollCommand("mac")
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyHost("mac", text)
    }
  }
  function pathFromUrl(url) {
    var v = String(url || "")
    if (v.indexOf("file://") === 0) return decodeURIComponent(v.substring(7))
    return v
  }
  function pollCommand(host) {
    var cmd = ["python3", pathFromUrl(Qt.resolvedUrl("poll.py")), "--host", host]
    if (configPath !== "") cmd.push("--config", configPath)
    return cmd
  }
  Timer {
    interval: root.pollMs
    running: true
    repeat: true
    onTriggered: root.refresh()
  }

  // IPC readback for independent verification (see netspeed pattern):
  //   quickshell ipc -p /usr/share/omarchy/shell call hendkai.kanban-progress status
  IpcHandler {
    target: "hendkai.kanban-progress"

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.togglePanel() }
    function refresh(): void { root.refresh() }

    function status(): string {
      var out = {}
      var keys = ["pc", "mac"]
      for (var i = 0; i < keys.length; i++) {
        var k = keys[i]
        var tot = root.boardTotals(k)
        out[k] = {
          state: root.hostState(k),
          running: root.runningCount(k),
          blocked: root.blockedCount(k),
          ready: root.readyCount(k),
          boards: root.boardsOf(k).length,
          done: tot.done,
          total: tot.total
        }
      }
      return JSON.stringify(out)
    }
  }

  // ---- popup -------------------------------------------------------------
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function togglePanel() { if (panelLoader.item) panelLoader.item.toggle() }
  function injectPanel() {
    var t = panelLoader.item
    if (!t) return
    if ("bar" in t) t.bar = root.bar
    if ("settings" in t) t.settings = root.settings
    if ("anchorItem" in t) t.anchorItem = button
    if ("hostWidget" in t) t.hostWidget = root
  }
  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    visible: false
    source: Qt.resolvedUrl("Panel.qml")
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  // ---- layout ------------------------------------------------------------
  // total ~440px default: 2 chips (chipW=200) + spacing 8 + margins
  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    labelVisible: false
    hasVisualContent: true
    horizontalMargin: 4
    fixedWidth: root.vertical
      ? -1
      : (root.showMac ? 2 : 1) * root.chipW + 8 + scaledHorizontalMargin * 2
    fixedHeight: root.vertical ? -1 : root.barSize

    tooltipText: root.tooltipText()
    onPressed: function(b) {
      if (b === Qt.LeftButton) root.togglePanel()
      else if (b === Qt.MiddleButton) root.refresh()
    }

    // Explicit height: chips size from this Row, never from their children.
    Row {
      anchors.centerIn: parent
      spacing: 8
      height: root.vertical ? 0 : root.barSize - 6

      KanbanChip {
        height: parent.height
        width: root.chipW
        machineColor: root.pcColor
        label: root.labelPc
        hostStatus: root.hostState("pc")
        title: root.rotatedTitle(root.titlesPc)
        running: root.runningCount("pc")
        blocked: root.blockedCount("pc")
        ready: root.readyCount("pc")
        fresh: root.hostFresh("pc")
        fontFamily: root.fontFamily
      }
      KanbanChip {
        visible: root.showMac
        height: parent.height
        width: root.chipW
        machineColor: root.macColor
        label: root.labelMac
        hostStatus: root.hostState("mac")
        title: root.rotatedTitle(root.titlesMac)
        running: root.runningCount("mac")
        blocked: root.blockedCount("mac")
        ready: root.readyCount("mac")
        fresh: root.hostFresh("mac")
        fontFamily: root.fontFamily
      }
    }
  }

  function tooltipText() {
    var lines = []
    var pairs = [[labelPc, "pc"], [labelMac, "mac"]]
    for (var i = 0; i < pairs.length; i++) {
      var name = pairs[i][0]
      var key = pairs[i][1]
      if (key === "mac" && !showMac) continue
      var st = hostState(key)
      if (st === "loading") { lines.push(name + ": …"); continue }
      if (st === "disabled") { lines.push(name + ": " + qsTr("not configured")); continue }
      if (st === "offline") { lines.push(name + ": offline"); continue }
      if (st === "error") { lines.push(name + ": " + qsTr("error")); continue }
      if (st === "schema") { lines.push(name + ": " + qsTr("schema mismatch")); continue }
      if (st === "empty") { lines.push(name + ": " + qsTr("no boards")); continue }
      var r = runningCount(key)
      var bl = blockedCount(key)
      var tot = boardTotals(key)
      var line = name + ": " + r + " " + qsTr("running")
      if (bl > 0) line += " · " + bl + " " + qsTr("blocked")
      line += " · " + qsTr("boards") + " " + tot.done + "/" + tot.total
      if (hostFresh(key) === "stale") line += " · " + qsTr("Stale")
      lines.push(line)
    }
    lines.push(qsTr("Click: details"))
    return lines.join("\n")
  }

  component KanbanChip: Rectangle {
    id: chip
    property color machineColor: "#45d6c5"
    property string label: "PC"
    // Named hostStatus, not "state": "state" collides with Item.state.
    property string hostStatus: "loading"  // loading|ok|empty|schema|offline|error|disabled
    property string title: ""
    property int running: 0
    property int blocked: 0
    property int ready: 0
    property string fresh: "none"          // fresh|stale|none
    property string fontFamily: ""

    readonly property bool busy: hostStatus === "ok" && running > 0
    readonly property real barH: 2

    radius: height / 4
    color: Qt.alpha(machineColor, 0.10)
    border.color: Qt.alpha(machineColor, 0.55)
    border.width: 1
    clip: true

    Row {
      id: chipRow
      anchors.fill: parent
      anchors.leftMargin: 7
      anchors.rightMargin: 7
      spacing: 6

      Rectangle {
        id: dot
        width: 8
        height: 8
        radius: 4
        anchors.verticalCenter: parent.verticalCenter
        color: chip.machineColor
        opacity: chip.hostStatus === "offline" || chip.hostStatus === "error"
          || chip.hostStatus === "disabled" ? 0.35 : 1
      }
      Text {
        id: labelItem
        anchors.verticalCenter: parent.verticalCenter
        text: chip.label
        color: chip.machineColor
        font.family: chip.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }
      Text {
        id: titleText
        anchors.verticalCenter: parent.verticalCenter
        // fixed margins + dot + label + count + 3 gaps; lower-bounded so a
        // long label/count can never drive the elided title width negative
        width: Math.max(24, chip.width - 14 - dot.width - labelItem.width - countText.width - 18)
        text: {
          if (chip.hostStatus === "loading") return qsTr("loading…")
          if (chip.hostStatus === "disabled") return qsTr("not configured")
          if (chip.hostStatus === "offline") return qsTr("offline")
          if (chip.hostStatus === "error") return qsTr("error")
          if (chip.hostStatus === "schema") return qsTr("schema?")
          if (chip.hostStatus === "empty") return qsTr("no tasks")
          if (chip.running > 0 && chip.fresh === "stale")
            return qsTr("Stale") + " · " + chip.title
          if (chip.running > 0) return chip.title
          if (chip.blocked > 0) return chip.blocked + qsTr(" blocked")
          if (chip.ready > 0) return chip.ready + qsTr(" ready")
          return qsTr("nothing open")
        }
        color: chip.hostStatus === "ok" ? root.fg : root.dimText
        font.family: chip.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
        textFormat: Text.PlainText
      }
      Text {
        id: countText
        anchors.verticalCenter: parent.verticalCenter
        text: chip.running > 0 ? "×" + chip.running : ""
        color: chip.machineColor
        font.family: chip.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }
    }

    // Slim indeterminate activity bar: only when tasks are really running.
    // No percentages — ever.
    Rectangle {
      visible: chip.busy
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      anchors.leftMargin: 3
      anchors.rightMargin: 3
      height: chip.barH
      radius: chip.barH / 2
      color: Qt.alpha(chip.machineColor, 0.18)
      clip: true

      Rectangle {
        id: runner
        readonly property real travel: parent.width - width
        // Reduce-motion: centered static runner; the sweep stays off.
        x: root.reduceMotion ? (parent.width - width) / 2 : 0
        width: Math.max(14, parent.width * 0.3)
        height: parent.height
        radius: parent.radius
        color: chip.machineColor
        XAnimator on x {
          running: chip.busy && !root.reduceMotion
          from: -20
          to: runner.travel + 20
          duration: 1600
          loops: Animation.Infinite
          easing.type: Easing.InOutQuad
        }
      }
    }
  }
}
