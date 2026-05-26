import AppKit
import Foundation

// MARK: - Font helper

func fitFontSize(text: String, maxWidth: CGFloat, start: CGFloat = 62, min: CGFloat = 11) -> CGFloat {
    var size = start
    while size > min {
        let w = (text as NSString).size(withAttributes: [.font: NSFont.boldSystemFont(ofSize: size)]).width
        if w <= maxWidth { break }
        size -= 1
    }
    return size
}

// MARK: - Persistent prefs per widget family

enum Prefs {
    static func color(for f: String) -> NSColor {
        guard let d = UserDefaults.standard.data(forKey: "color.\(f)"),
              let c = try? NSKeyedUnarchiver.unarchivedObject(ofClass: NSColor.self, from: d)
        else { return NSColor(calibratedRed: 0.565, green: 0.753, blue: 0.376, alpha: 1) }
        return c
    }
    static func opacity(for f: String) -> Double {
        let v = UserDefaults.standard.double(forKey: "opacity.\(f)")
        return v == 0 ? 0.72 : v
    }
    static func ontop(for f: String) -> Bool {
        guard UserDefaults.standard.object(forKey: "ontop.\(f)") != nil else { return true }
        return UserDefaults.standard.bool(forKey: "ontop.\(f)")
    }
    static func save(color c: NSColor, for f: String) {
        let d = try? NSKeyedArchiver.archivedData(withRootObject: c, requiringSecureCoding: true)
        UserDefaults.standard.set(d, forKey: "color.\(f)")
    }
    static func save(opacity v: Double, for f: String) {
        UserDefaults.standard.set(v, forKey: "opacity.\(f)")
    }
    static func save(ontop v: Bool, for f: String) {
        UserDefaults.standard.set(v, forKey: "ontop.\(f)")
    }
}

// MARK: - Config popover

class ConfigVC: NSViewController {
    let family: String
    weak var widget: WidgetWindow?
    var colorWell: NSColorWell!
    var opacitySlider: NSSlider!
    var ontopCheck: NSButton!

    init(family: String, widget: WidgetWindow) {
        self.family = family
        self.widget = widget
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError() }

    override func loadView() {
        let W: CGFloat = 208, pad: CGFloat = 14

        let colorLbl = rowLabel("Color")
        colorLbl.frame = NSRect(x: pad, y: 108, width: 60, height: 15)

        colorWell = NSColorWell(frame: NSRect(x: W - pad - 36, y: 104, width: 36, height: 24))
        colorWell.color = Prefs.color(for: family)
        colorWell.target = self
        colorWell.action = #selector(colorChanged(_:))

        let opacLbl = rowLabel("Opacity")
        opacLbl.frame = NSRect(x: pad, y: 74, width: 60, height: 15)

        opacitySlider = NSSlider(value: Prefs.opacity(for: family),
                                  minValue: 0.1, maxValue: 1.0,
                                  target: self, action: #selector(opacityChanged(_:)))
        opacitySlider.frame = NSRect(x: pad, y: 52, width: W - pad * 2, height: 18)

        ontopCheck = NSButton(checkboxWithTitle: "Always on top",
                               target: self, action: #selector(ontopChanged(_:)))
        ontopCheck.state = Prefs.ontop(for: family) ? .on : .off
        ontopCheck.frame = NSRect(x: pad, y: 16, width: W - pad * 2, height: 20)
        ontopCheck.font = NSFont.systemFont(ofSize: 11)

        let v = NSView(frame: NSRect(x: 0, y: 0, width: W, height: 144))
        [colorLbl, colorWell, opacLbl, opacitySlider, ontopCheck].forEach { v.addSubview($0) }
        self.view = v
    }

    private func rowLabel(_ s: String) -> NSTextField {
        let f = NSTextField(labelWithString: s)
        f.font = NSFont.systemFont(ofSize: 11, weight: .medium)
        f.textColor = .secondaryLabelColor
        return f
    }

    @objc func colorChanged(_ sender: NSColorWell) {
        Prefs.save(color: sender.color, for: family)
        widget?.applyPrefs()
    }
    @objc func opacityChanged(_ sender: NSSlider) {
        Prefs.save(opacity: sender.doubleValue, for: family)
        widget?.applyPrefs()
    }
    @objc func ontopChanged(_ sender: NSButton) {
        Prefs.save(ontop: sender.state == .on, for: family)
        widget?.applyPrefs()
    }
}

// MARK: - Widget window

class WidgetWindow: NSObject, NSWindowDelegate {
    let family: String
    let window: NSWindow
    var onClose: (() -> Void)?
    var popover: NSPopover?

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
        window.collectionBehavior = [.managed, .participatesInCycle]
        window.isOpaque = false
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
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
            sub.frame = NSRect(x: 20, y: 10, width: W - 56, height: 20)
            sub.font = NSFont.systemFont(ofSize: 10, weight: .medium)
            sub.textColor = NSColor(calibratedRed: 0.22, green: 0.40, blue: 0.08, alpha: 1.0)
            sub.backgroundColor = .clear
            sub.drawsBackground = false
            content.addSubview(sub)
        }

        let dotsBtn = NSButton(frame: NSRect(x: W - 30, y: 8, width: 20, height: 20))
        if let img = NSImage(systemSymbolName: "ellipsis", accessibilityDescription: "Settings") {
            dotsBtn.image = img
            dotsBtn.imageScaling = .scaleProportionallyDown
            dotsBtn.contentTintColor = NSColor(calibratedWhite: 0.15, alpha: 0.55)
        } else {
            dotsBtn.title = "•••"
            dotsBtn.font = NSFont.systemFont(ofSize: 8)
        }
        dotsBtn.bezelStyle = .inline
        dotsBtn.isBordered = false
        dotsBtn.target = self
        dotsBtn.action = #selector(showConfig(_:))
        content.addSubview(dotsBtn)

        applyPrefs()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        DistributedNotificationCenter.default().addObserver(
            forName: Notification.Name("com.localagentsociety.focus.\(family)"),
            object: nil, queue: .main
        ) { [weak self] _ in
            self?.window.orderFrontRegardless()
        }
    }

    func applyPrefs() {
        window.backgroundColor = Prefs.color(for: family).withAlphaComponent(Prefs.opacity(for: family))
        window.level = Prefs.ontop(for: family) ? .floating : .normal
    }

    @objc func showConfig(_ sender: NSButton) {
        if let p = popover, p.isShown { p.close(); return }
        let p = NSPopover()
        p.contentViewController = ConfigVC(family: family, widget: self)
        p.behavior = .transient
        p.show(relativeTo: sender.bounds, of: sender, preferredEdge: .maxY)
        popover = p
    }

    func windowWillClose(_: Notification) { onClose?() }
}

// MARK: - App icon

func makeAppIcon() -> NSImage {
    let size: CGFloat = 512
    let img = NSImage(size: NSSize(width: size, height: size))
    img.lockFocus()

    let ctx = NSGraphicsContext.current!.cgContext

    // Background: deep navy rounded square
    let bg = NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: size, height: size), xRadius: 110, yRadius: 110)
    NSColor(calibratedRed: 0.07, green: 0.07, blue: 0.16, alpha: 1).setFill()
    bg.fill()

    // Subtle radial gradient overlay
    let center = CGPoint(x: size / 2, y: size / 2)
    let colors = [
        CGColor(red: 0.18, green: 0.18, blue: 0.36, alpha: 0.8),
        CGColor(red: 0.07, green: 0.07, blue: 0.16, alpha: 0)
    ]
    if let grad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
                              colors: colors as CFArray,
                              locations: [0, 1]) {
        ctx.drawRadialGradient(grad,
                               startCenter: center, startRadius: 0,
                               endCenter: center, endRadius: size * 0.62,
                               options: [])
    }

    // Node positions: 1 center + 6 around a ring
    let cx = size / 2, cy = size / 2
    let ring: CGFloat = 148
    var nodes: [CGPoint] = [CGPoint(x: cx, y: cy)]
    for i in 0..<6 {
        let angle = CGFloat(i) * .pi / 3 - .pi / 6
        nodes.append(CGPoint(x: cx + ring * cos(angle), y: cy + ring * sin(angle)))
    }

    // Extra outer nodes (alternate ring positions)
    let outerRing: CGFloat = 215
    var outerNodes: [CGPoint] = []
    for i in 0..<6 {
        let angle = CGFloat(i) * .pi / 3
        outerNodes.append(CGPoint(x: cx + outerRing * cos(angle), y: cy + outerRing * sin(angle)))
    }

    // Draw edges: center → inner ring
    let edgeColor = NSColor(calibratedRed: 0.44, green: 0.82, blue: 0.72, alpha: 0.30)
    edgeColor.setStroke()
    for n in nodes.dropFirst() {
        let path = NSBezierPath()
        path.lineWidth = 1.8
        path.move(to: nodes[0])
        path.line(to: n)
        path.stroke()
    }

    // Edges: inner ring neighbors
    for i in 1...6 {
        let next = i == 6 ? 1 : i + 1
        let path = NSBezierPath()
        path.lineWidth = 1.5
        edgeColor.setStroke()
        path.move(to: nodes[i])
        path.line(to: nodes[next])
        path.stroke()
    }

    // Edges: inner ring → outer (alternating)
    let outerEdgeColor = NSColor(calibratedRed: 0.44, green: 0.82, blue: 0.72, alpha: 0.15)
    outerEdgeColor.setStroke()
    for i in 0..<6 {
        let path = NSBezierPath()
        path.lineWidth = 1.2
        path.move(to: nodes[i + 1])
        path.line(to: outerNodes[i])
        path.stroke()
    }

    // Draw outer nodes (small)
    for pt in outerNodes {
        let r: CGFloat = 6
        let dot = NSBezierPath(ovalIn: NSRect(x: pt.x - r, y: pt.y - r, width: r * 2, height: r * 2))
        NSColor(calibratedRed: 0.44, green: 0.82, blue: 0.72, alpha: 0.45).setFill()
        dot.fill()
    }

    // Draw inner ring nodes (medium)
    for pt in nodes.dropFirst() {
        let r: CGFloat = 11
        let dot = NSBezierPath(ovalIn: NSRect(x: pt.x - r, y: pt.y - r, width: r * 2, height: r * 2))
        NSColor(calibratedRed: 0.44, green: 0.82, blue: 0.72, alpha: 0.85).setFill()
        dot.fill()
        // Glow ring
        let glow = NSBezierPath(ovalIn: NSRect(x: pt.x - r - 3, y: pt.y - r - 3, width: (r + 3) * 2, height: (r + 3) * 2))
        NSColor(calibratedRed: 0.44, green: 0.82, blue: 0.72, alpha: 0.12).setFill()
        glow.fill()
    }

    // Center node (large, brighter)
    let cr: CGFloat = 22
    let glow2 = NSBezierPath(ovalIn: NSRect(x: cx - cr - 8, y: cy - cr - 8, width: (cr + 8) * 2, height: (cr + 8) * 2))
    NSColor(calibratedRed: 0.44, green: 0.82, blue: 0.72, alpha: 0.15).setFill()
    glow2.fill()
    let centerDot = NSBezierPath(ovalIn: NSRect(x: cx - cr, y: cy - cr, width: cr * 2, height: cr * 2))
    NSColor(calibratedRed: 0.56, green: 0.90, blue: 0.80, alpha: 1).setFill()
    centerDot.fill()

    img.unlockFocus()
    return img
}

// MARK: - App delegate

class AppDelegate: NSObject, NSApplicationDelegate {
    var widgets: [String: WidgetWindow] = [:]
    // Families the user has manually closed this session — don't auto-reopen them
    var closedByUser: Set<String> = []

    func applicationDidFinishLaunching(_: Notification) {
        NSApp.applicationIconImage = makeAppIcon()

        // Open widgets for all registered agents on first launch
        guard let agents = fetchAgents() else { return }
        for (idx, family) in agents.keys.sorted().enumerated() {
            guard let info = agents[family] else { continue }
            let members = info["members"] as? [String] ?? []
            spawnWidget(family: family, members: members, index: idx)
        }
    }

    // URL scheme: localagentsociety://FamilyName  →  open or focus that widget
    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls {
            guard url.scheme == "localagentsociety",
                  let family = url.host, !family.isEmpty else { continue }
            openWidget(for: family)
        }
    }

    // Dock icon click when all windows hidden → reopen everything
    func applicationShouldHandleReopen(_ app: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows {
            closedByUser.removeAll()
            guard let agents = fetchAgents() else { return true }
            for (idx, family) in agents.keys.sorted().enumerated() {
                guard let info = agents[family] else { continue }
                let members = info["members"] as? [String] ?? []
                spawnWidget(family: family, members: members, index: idx)
            }
        }
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
        openWidget(for: family)
    }

    // Open or focus a widget. Removes family from closedByUser so it can be re-shown.
    func openWidget(for family: String) {
        closedByUser.remove(family)
        if let w = widgets[family] {
            w.window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        guard let agents = fetchAgents(), let info = agents[family] else { return }
        let idx = agents.keys.sorted().firstIndex(of: family) ?? 0
        let members = info["members"] as? [String] ?? []
        spawnWidget(family: family, members: members, index: idx)
    }

    private func spawnWidget(family: String, members: [String], index: Int) {
        guard widgets[family] == nil else { return }
        let widget = WidgetWindow(family: family, members: members, index: index)
        widget.onClose = { [weak self] in
            self?.closedByUser.insert(family)
            self?.widgets.removeValue(forKey: family)
        }
        widgets[family] = widget
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
