import AppKit
import Foundation

func fitFontSize(text: String, maxWidth: CGFloat, start: CGFloat = 62, min: CGFloat = 11) -> CGFloat {
    var size = start
    while size > min {
        let w = (text as NSString).size(withAttributes: [.font: NSFont.boldSystemFont(ofSize: size)]).width
        if w <= maxWidth { break }
        size -= 1
    }
    return size
}

class WidgetWindow: NSObject, NSWindowDelegate {
    let family: String
    let window: NSWindow
    var onClose: (() -> Void)?

    init(family: String, members: [String], index: Int) {
        let W: CGFloat = 300, H: CGFloat = 160
        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let x = screen.minX + 60 + CGFloat(index) * 30
        let y = screen.maxY - H - 60 - CGFloat(index) * 30

        window = NSWindow(
            contentRect: NSRect(x: x, y: y, width: W, height: H),
            styleMask: [.titled, .closable, .miniaturizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        self.family = family
        super.init()

        window.title = family
        window.level = .floating
        window.collectionBehavior = [.managed, .participatesInCycle]
        window.isOpaque = false
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.backgroundColor = NSColor(calibratedRed: 0.565, green: 0.753, blue: 0.376, alpha: 0.72)
        window.isReleasedWhenClosed = false
        window.delegate = self

        let content = window.contentView!
        let labelWidth = W - 28

        let nameLbl = NSTextField(wrappingLabelWithString: family)
        nameLbl.frame = NSRect(x: 18, y: H * 0.28, width: labelWidth, height: H * 0.60)
        nameLbl.font = NSFont.boldSystemFont(ofSize: fitFontSize(text: family, maxWidth: labelWidth))
        nameLbl.textColor = NSColor(calibratedRed: 0.08, green: 0.08, blue: 0.08, alpha: 1.0)
        nameLbl.backgroundColor = .clear
        nameLbl.drawsBackground = false
        nameLbl.lineBreakMode = .byClipping
        content.addSubview(nameLbl)

        if !members.isEmpty {
            let sub = NSTextField(labelWithString: members.map { $0.uppercased() }.joined(separator: " · "))
            sub.frame = NSRect(x: 20, y: 10, width: W - 28, height: 20)
            sub.font = NSFont.systemFont(ofSize: 10, weight: .medium)
            sub.textColor = NSColor(calibratedRed: 0.22, green: 0.40, blue: 0.08, alpha: 1.0)
            sub.backgroundColor = .clear
            sub.drawsBackground = false
            content.addSubview(sub)
        }

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_: Notification) { onClose?() }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var widgets: [String: WidgetWindow] = [:]
    var timer: Timer?

    func applicationDidFinishLaunching(_: Notification) {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refresh() }
    }

    // Click on Dock icon when no windows are visible → reopen everything
    func applicationShouldHandleReopen(_ app: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows { refresh(showClosed: true) }
        return true
    }

    func applicationDockMenu(_: NSApplication) -> NSMenu? {
        guard let agents = fetchAgents(), !agents.isEmpty else { return nil }
        let menu = NSMenu()
        for family in agents.keys.sorted() {
            let item = NSMenuItem(title: family,
                                  action: #selector(focusAgent(_:)),
                                  keyEquivalent: "")
            item.image = NSImage(systemSymbolName: "macwindow", accessibilityDescription: nil)
            item.target = self
            item.representedObject = family
            menu.addItem(item)
        }
        return menu
    }

    @objc func focusAgent(_ sender: NSMenuItem) {
        guard let family = sender.representedObject as? String else { return }
        if let widget = widgets[family] {
            widget.window.makeKeyAndOrderFront(nil)
        } else {
            refresh(showClosed: false, only: family)
        }
    }

    func refresh(showClosed: Bool = false, only: String? = nil) {
        guard let agents = fetchAgents() else { return }
        let sorted = agents.keys.sorted()

        for (idx, family) in sorted.enumerated() {
            guard only == nil || only == family else { continue }
            guard let info = agents[family] else { continue }

            if let w = widgets[family] {
                if showClosed { w.window.makeKeyAndOrderFront(nil) }
            } else {
                let members = info["members"] as? [String] ?? []
                let widget = WidgetWindow(family: family, members: members, index: idx)
                widget.onClose = { [weak self] in self?.widgets.removeValue(forKey: family) }
                widgets[family] = widget
            }
        }

        for family in Set(widgets.keys).subtracting(agents.keys) {
            widgets[family]?.window.close()
            widgets.removeValue(forKey: family)
        }
    }

    func fetchAgents() -> [String: [String: Any]]? {
        guard let url = URL(string: "http://localhost:8700/agents"),
              let data = try? Data(contentsOf: url),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: [String: Any]]
        else { return nil }
        return json
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
