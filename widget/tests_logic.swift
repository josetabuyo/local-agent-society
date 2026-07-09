#!/usr/bin/env swift
// Logic unit tests — runs with: swift widget/tests_logic.swift
import Foundation

var passed = 0, failed = 0

func test(_ name: String, _ value: @autoclosure () -> Bool) {
    if value() { print("  PASS \(name)"); passed += 1 }
    else        { print("  FAIL \(name)"); failed += 1 }
}

// MARK: - Prefs key naming

test("color key",   "color.Forti"      == "color.\("Forti")")
test("opacity key", "opacity.System"   == "opacity.\("System")")
test("ontop key",   "ontop.Vacaciones" == "ontop.\("Vacaciones")")
test("color key with space", "color.Local Agent" == "color.\("Local Agent")")

// MARK: - Prefs defaults (no stored value → default)

let ud = UserDefaults.standard
let testFamily = "__tray_test_\(UUID().uuidString)"

// Opacity default: 0.72 when key absent
ud.removeObject(forKey: "opacity.\(testFamily)")
let opacityDefault: Double = {
    let v = ud.double(forKey: "opacity.\(testFamily)")
    return v == 0 ? 0.72 : v
}()
test("opacity default is 0.72", opacityDefault == 0.72)

// Opacity persists round-trip
ud.set(0.5, forKey: "opacity.\(testFamily)")
let opacityLoaded = ud.double(forKey: "opacity.\(testFamily)")
test("opacity round-trip", opacityLoaded == 0.5)

// Ontop default: true when key absent
ud.removeObject(forKey: "ontop.\(testFamily)")
let ontopDefault: Bool = {
    guard ud.object(forKey: "ontop.\(testFamily)") != nil else { return true }
    return ud.bool(forKey: "ontop.\(testFamily)")
}()
test("ontop default is true", ontopDefault == true)

// Ontop persists round-trip
ud.set(false, forKey: "ontop.\(testFamily)")
let ontopLoaded: Bool = {
    guard ud.object(forKey: "ontop.\(testFamily)") != nil else { return true }
    return ud.bool(forKey: "ontop.\(testFamily)")
}()
test("ontop round-trip false", ontopLoaded == false)

// Cleanup test keys
["color", "opacity", "ontop"].forEach { ud.removeObject(forKey: "\($0).\(testFamily)") }

// MARK: - URL scheme parsing (localagentsociety://FamilyName)

let simpleURL = URL(string: "localagentsociety://Forti")!
test("url scheme",        simpleURL.scheme == "localagentsociety")
test("url host = family", simpleURL.host == "Forti")
test("url path empty",    simpleURL.path == "" || simpleURL.path == "/")

let systemURL = URL(string: "localagentsociety://System")!
test("url System family", systemURL.host == "System")

// Percent-encoded family names
let encodedURL = URL(string: "localagentsociety://Local%20Agent")!
test("url percent-decoded family", encodedURL.host == "Local Agent")

// Empty host → must be rejected by handler (host is nil or empty)
let emptyHostURL = URL(string: "localagentsociety://")
let emptyHost = emptyHostURL?.host ?? ""
test("empty host is empty or nil", emptyHost.isEmpty)

// MARK: - closedByUser set semantics

var closedByUser: Set<String> = []

closedByUser.insert("Forti")
test("insert into closed set", closedByUser.contains("Forti"))

closedByUser.remove("Forti")
test("remove from closed set", !closedByUser.contains("Forti"))

// Removing non-existent key is safe
closedByUser.remove("NonExistent")
test("remove non-existent is safe", closedByUser.isEmpty)

// Re-inserting after remove works
closedByUser.insert("System")
closedByUser.remove("System")
test("insert-remove-check cycle", !closedByUser.contains("System"))

// MARK: - Gear panel TTY set diffing (WidgetWindow.ttySetChanged)
// Mirrored here as a pure function since tests_logic.swift runs standalone
// (not linked against tray.swift's AppKit-dependent types).

func ttySetChanged(old: [String], new: [String]) -> Bool {
    Set(old) != Set(new)
}

test("tty diff: no change (same order)",       !ttySetChanged(old: ["/dev/ttys001", "/dev/ttys002"], new: ["/dev/ttys001", "/dev/ttys002"]))
test("tty diff: no change (different order)",  !ttySetChanged(old: ["/dev/ttys001", "/dev/ttys002"], new: ["/dev/ttys002", "/dev/ttys001"]))
test("tty diff: addition detected",             ttySetChanged(old: ["/dev/ttys001"], new: ["/dev/ttys001", "/dev/ttys002"]))
test("tty diff: removal detected",              ttySetChanged(old: ["/dev/ttys001", "/dev/ttys002"], new: ["/dev/ttys001"]))
test("tty diff: empty to empty is no change",  !ttySetChanged(old: [], new: []))
test("tty diff: empty to non-empty",            ttySetChanged(old: [], new: ["/dev/ttys001"]))
test("tty diff: non-empty to empty",            ttySetChanged(old: ["/dev/ttys001"], new: []))

// MARK: - Route popup selection preservation

func resolveRouteSelection(ttys: [String], previousSelection: String?, fallbackSelection: String?) -> String? {
    guard let candidate = previousSelection ?? fallbackSelection, ttys.contains(candidate) else { return nil }
    return candidate
}

test("selection preserved when tty still present",
     resolveRouteSelection(ttys: ["/dev/ttys001", "/dev/ttys002"], previousSelection: "/dev/ttys002", fallbackSelection: nil) == "/dev/ttys002")

test("selection falls back to Auto when tty removed",
     resolveRouteSelection(ttys: ["/dev/ttys001"], previousSelection: "/dev/ttys002", fallbackSelection: nil) == nil)

test("selection uses fallback (selectedTTY) when no previous popup selection",
     resolveRouteSelection(ttys: ["/dev/ttys003"], previousSelection: nil, fallbackSelection: "/dev/ttys003") == "/dev/ttys003")

test("selection nil when neither previous nor fallback present",
     resolveRouteSelection(ttys: ["/dev/ttys001"], previousSelection: nil, fallbackSelection: nil) == nil)

test("selection nil when new tty appears but none selected before",
     resolveRouteSelection(ttys: ["/dev/ttys001", "/dev/ttys002"], previousSelection: nil, fallbackSelection: nil) == nil)

// MARK: - expandWindow frame-delta math (WidgetWindow.expandWindow)
// Mirrored here as pure geometry math since tests_logic.swift runs standalone
// (not linked against tray.swift's AppKit-dependent NSWindow/NSView code).
// Real signature: expandWindow(by:excluding:display:) grows/shrinks the
// window by `delta`, keeping the top edge fixed (moves origin.y by -delta,
// grows height by +delta), and shifts every content subview's origin.y by
// +delta except the one passed as `excluding`.

struct PlainRect: Equatable {
    var x: Double, y: Double, w: Double, h: Double
}

func expandedWindowFrame(current: PlainRect, delta: Double) -> PlainRect {
    PlainRect(x: current.x, y: current.y - delta, w: current.w, h: current.h + delta)
}

func offsetSubviewFrames(_ frames: [(id: String, frame: PlainRect)], delta: Double, excluding excludedID: String?) -> [(id: String, frame: PlainRect)] {
    frames.map { entry in
        guard entry.id != excludedID else { return entry }
        var f = entry.frame
        f.y += delta
        return (entry.id, f)
    }
}

test("expandWindow: grow keeps top edge fixed (origin.y decreases by delta)",
     expandedWindowFrame(current: PlainRect(x: 10, y: 100, w: 300, h: 200), delta: 50)
        == PlainRect(x: 10, y: 50, w: 300, h: 250))

test("expandWindow: shrink keeps top edge fixed (origin.y increases as delta is negative)",
     expandedWindowFrame(current: PlainRect(x: 10, y: 100, w: 300, h: 200), delta: -50)
        == PlainRect(x: 10, y: 150, w: 300, h: 150))

test("expandWindow: zero delta is a no-op on the frame",
     expandedWindowFrame(current: PlainRect(x: 0, y: 0, w: 300, h: 200), delta: 0)
        == PlainRect(x: 0, y: 0, w: 300, h: 200))

test("expandWindow: width is never touched",
     expandedWindowFrame(current: PlainRect(x: 0, y: 0, w: 300, h: 200), delta: 30).w == 300)

let subviewsBeforeGrow: [(id: String, frame: PlainRect)] = [
    ("gearPanel",    PlainRect(x: 0, y: 0, w: 300, h: 300)),
    ("commandPanel", PlainRect(x: 0, y: 300, w: 300, h: 40)),
]

let subviewsAfterGrow = offsetSubviewFrames(subviewsBeforeGrow, delta: 20, excluding: nil)
test("expandWindow: no exclusion shifts every subview by delta",
     subviewsAfterGrow.map { $0.frame.y } == [20, 320])

let subviewsAfterGrowExcluding = offsetSubviewFrames(subviewsBeforeGrow, delta: 20, excluding: "commandPanel")
test("expandWindow: excluded view keeps its own (already-final) y",
     subviewsAfterGrowExcluding.first(where: { $0.id == "commandPanel" })!.frame.y == 300)
test("expandWindow: non-excluded views still shift when another view is excluded",
     subviewsAfterGrowExcluding.first(where: { $0.id == "gearPanel" })!.frame.y == 20)

let subviewsAfterShrink = offsetSubviewFrames(subviewsBeforeGrow, delta: -15, excluding: nil)
test("expandWindow: negative delta shifts subviews up",
     subviewsAfterShrink.map { $0.frame.y } == [-15, 285])

// MARK: - GearPanelModel row/label shaping
// Mirrors the pure string-shaping logic GearPanelBuilder.build performs
// before laying out NSTextFields — folderName, portsLabel, agentVoiceLabel,
// and the fixed info-row ordering/count.

func gearFolderName(agentPath: String) -> String {
    agentPath.isEmpty ? "—" : (agentPath as NSString).lastPathComponent
}

func gearPortsLabel(ports: [Int]?) -> String {
    guard let ports = ports else { return "…" }
    return ports.isEmpty ? "None" : ports.map { String($0) }.joined(separator: " · ")
}

struct MiniVoice { let name: String; let lang: String; let flag: String }
let miniVoiceCatalogue: [MiniVoice] = [
    MiniVoice(name: "Samantha", lang: "en-US", flag: "🇺🇸"),
    MiniVoice(name: "Paulina",  lang: "es-MX", flag: "🇲🇽"),
]

func gearAgentVoiceLabel(agentVoice: String, catalogue: [MiniVoice]) -> String {
    guard !agentVoice.isEmpty else { return "—" }
    if let v = catalogue.first(where: { $0.name == agentVoice }) {
        return "\(agentVoice)  \(v.flag) \(v.lang)"
    }
    return agentVoice
}

func gearInfoRows(branch: String, folderName: String, portsLabel: String, humanVoiceLabel: String, agentVoiceLabel: String) -> [(String, String)] {
    [
        ("Branch",      branch),
        ("Folder",      folderName),
        ("Ports",       portsLabel),
        ("Human Voice", humanVoiceLabel),
        ("Agent Voice", agentVoiceLabel),
    ]
}

test("gear folderName: empty path renders em-dash",  gearFolderName(agentPath: "") == "—")
test("gear folderName: uses last path component",    gearFolderName(agentPath: "/Users/x/Development/Forti") == "Forti")

test("gear portsLabel: nil ports render loading ellipsis", gearPortsLabel(ports: nil) == "…")
test("gear portsLabel: empty ports render None",           gearPortsLabel(ports: []) == "None")
test("gear portsLabel: joins multiple ports",              gearPortsLabel(ports: [8700, 5173]) == "8700 · 5173")
test("gear portsLabel: single port has no separator",      gearPortsLabel(ports: [8700]) == "8700")

test("gear agentVoiceLabel: empty voice renders em-dash",        gearAgentVoiceLabel(agentVoice: "", catalogue: miniVoiceCatalogue) == "—")
test("gear agentVoiceLabel: known voice includes flag+lang",     gearAgentVoiceLabel(agentVoice: "Samantha", catalogue: miniVoiceCatalogue) == "Samantha  🇺🇸 en-US")
test("gear agentVoiceLabel: unknown voice falls back to raw",    gearAgentVoiceLabel(agentVoice: "Ghostwriter", catalogue: miniVoiceCatalogue) == "Ghostwriter")

let emptyGearRows = gearInfoRows(branch: "", folderName: "—", portsLabel: "…", humanVoiceLabel: "—", agentVoiceLabel: "—")
test("gear info rows: always exactly 5 rows regardless of emptiness", emptyGearRows.count == 5)
test("gear info rows: fixed key ordering starts with Branch",         emptyGearRows.map { $0.0 } == ["Branch", "Folder", "Ports", "Human Voice", "Agent Voice"])

let populatedGearRows = gearInfoRows(branch: "main", folderName: "Forti", portsLabel: "8700", humanVoiceLabel: "en-US", agentVoiceLabel: "Samantha  🇺🇸 en-US")
test("gear info rows: populated inputs preserve row count", populatedGearRows.count == 5)
test("gear info rows: populated values land in the right slots", populatedGearRows[0].1 == "main" && populatedGearRows[2].1 == "8700")

// MARK: - CommandListPanelModel row-count / height shaping
// Mirrors CommandPanelBuilder.buildList's pure layout math: row height,
// separator insertion (only when both groups are non-empty), and total
// panel height — without building any NSView.

enum MiniCmdKind { case openTerminal, openBareTerminal, injectCommand }
struct MiniCmd { let kind: MiniCmdKind }

func commandListLayout(commands: [MiniCmd]) -> (rowCount: Int, hasSeparator: Bool, totalHeight: Double) {
    let rH = 32.0
    // Mirrors tray.swift exactly: only openTerminal/injectCommand define the
    // separator groups — openBareTerminal counts toward totalHeight (it's
    // still a row in `cmds`) but does not participate in `hasSep`.
    let opens = commands.filter { $0.kind == .openTerminal }
    let injects = commands.filter { $0.kind == .injectCommand }
    let hasSep = !opens.isEmpty && !injects.isEmpty
    let totalH = Double(commands.count) * rH + (hasSep ? 10.0 : 0.0) + 34.0 + 8.0
    return (commands.count, hasSep, totalH)
}

let emptyCmdLayout = commandListLayout(commands: [])
test("command list: empty commands has zero rows",       emptyCmdLayout.rowCount == 0)
test("command list: empty commands has no separator",     !emptyCmdLayout.hasSeparator)
test("command list: empty commands height is base chrome only", emptyCmdLayout.totalHeight == 42)

let opensOnlyLayout = commandListLayout(commands: [MiniCmd(kind: .openTerminal), MiniCmd(kind: .openBareTerminal)])
test("command list: opens-only has no separator",  !opensOnlyLayout.hasSeparator)
test("command list: opens-only height excludes separator gap", opensOnlyLayout.totalHeight == 2 * 32 + 42)

let injectsOnlyLayout = commandListLayout(commands: [MiniCmd(kind: .injectCommand)])
test("command list: injects-only has no separator", !injectsOnlyLayout.hasSeparator)

let mixedLayout = commandListLayout(commands: [MiniCmd(kind: .openTerminal), MiniCmd(kind: .injectCommand), MiniCmd(kind: .injectCommand)])
test("command list: mixed opens+injects adds separator",       mixedLayout.hasSeparator)
test("command list: mixed opens+injects height includes separator gap", mixedLayout.totalHeight == 3 * 32 + 10 + 42)
test("command list: row count matches total command count",    mixedLayout.rowCount == 3)

let bareAndInjectLayout = commandListLayout(commands: [MiniCmd(kind: .openBareTerminal), MiniCmd(kind: .injectCommand)])
test("command list: bareTerminal+inject has no separator (bareTerminal isn't in either group)", !bareAndInjectLayout.hasSeparator)
test("command list: bareTerminal+inject still counts both rows in height", bareAndInjectLayout.totalHeight == 2 * 32 + 42)

// MARK: - CommandEditPanelModel field defaults (new vs existing command)
// Mirrors CommandPanelBuilder.buildEdit's pure derivation of initial field
// values/segment selection/button title from an optional WidgetCommand.

struct MiniEditCommand { let label: String; let kind: MiniCmdKind; let payload: String }

func commandEditSegment(kind: MiniCmdKind?) -> Int {
    switch kind {
    case .none:                    return 0
    case .some(.openTerminal):     return 0
    case .some(.openBareTerminal): return 1
    case .some(.injectCommand):    return 2
    }
}

func commandEditFields(command: MiniEditCommand?, index: Int?) -> (label: String, payload: String, segment: Int, saveTitle: String, hasDelete: Bool) {
    (
        label: command?.label ?? "",
        payload: command?.payload ?? "",
        segment: commandEditSegment(kind: command?.kind),
        saveTitle: index == nil ? "Add" : "Save",
        hasDelete: index != nil
    )
}

let newCmdFields = commandEditFields(command: nil, index: nil)
test("command edit: new command has empty label",       newCmdFields.label.isEmpty)
test("command edit: new command has empty payload",      newCmdFields.payload.isEmpty)
test("command edit: new command defaults to segment 0 (claude)", newCmdFields.segment == 0)
test("command edit: new command save button reads Add",  newCmdFields.saveTitle == "Add")
test("command edit: new command has no delete button",    !newCmdFields.hasDelete)

let existingInjectFields = commandEditFields(command: MiniEditCommand(label: "clear", kind: .injectCommand, payload: "/clear"), index: 2)
test("command edit: existing command preserves label",    existingInjectFields.label == "clear")
test("command edit: existing command preserves payload",  existingInjectFields.payload == "/clear")
test("command edit: inject kind maps to segment 2",        existingInjectFields.segment == 2)
test("command edit: existing command save button reads Save", existingInjectFields.saveTitle == "Save")
test("command edit: existing command has delete button",   existingInjectFields.hasDelete)

let existingBareTerminalFields = commandEditFields(command: MiniEditCommand(label: "", kind: .openBareTerminal, payload: ""), index: 0)
test("command edit: bare terminal kind maps to segment 1", existingBareTerminalFields.segment == 1)

// MARK: - Summary

print("")
print("Results: \(passed) passed, \(failed) failed")
exit(failed > 0 ? 1 : 0)
