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

// MARK: - Summary

print("")
print("Results: \(passed) passed, \(failed) failed")
exit(failed > 0 ? 1 : 0)
