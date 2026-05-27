import AppKit
import Foundation
import Speech
import AVFoundation
import ApplicationServices

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

// MARK: - Track last non-widget focused app (for injection target)

var lastNonWidgetApp: NSRunningApplication?

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
    static func voiceLocale(for f: String) -> String {
        return UserDefaults.standard.string(forKey: "voiceLocale.\(f)") ?? "es-MX"
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
    static func save(voiceLocale locale: String, for f: String) {
        UserDefaults.standard.set(locale, forKey: "voiceLocale.\(f)")
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

// MARK: - Language picker popover

let supportedLocales: [(name: String, flag: String, id: String)] = [
    ("Español",    "🇲🇽", "es-MX"),
    ("English",    "🇺🇸", "en-US"),
    ("Português",  "🇧🇷", "pt-BR"),
    ("Français",   "🇫🇷", "fr-FR"),
    ("Deutsch",    "🇩🇪", "de-DE"),
]

class LangPickerVC: NSViewController {
    let family: String
    weak var widget: WidgetWindow?
    weak var popover: NSPopover?

    init(family: String, widget: WidgetWindow, popover: NSPopover) {
        self.family  = family
        self.widget  = widget
        self.popover = popover
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError() }

    override func loadView() {
        let W: CGFloat = 160, rowH: CGFloat = 30, pad: CGFloat = 8
        let H = CGFloat(supportedLocales.count) * rowH + pad * 2
        let v = NSView(frame: NSRect(x: 0, y: 0, width: W, height: H))

        let current = Prefs.voiceLocale(for: family)
        for (i, lang) in supportedLocales.enumerated() {
            let y = H - pad - CGFloat(i + 1) * rowH
            let btn = NSButton(frame: NSRect(x: pad, y: y, width: W - pad * 2, height: rowH - 2))
            btn.title = "\(lang.flag)  \(lang.name)"
            btn.tag   = i
            btn.alignment = .left
            btn.bezelStyle = .rounded
            btn.isBordered = lang.id == current
            btn.font = lang.id == current
                ? NSFont.boldSystemFont(ofSize: 12)
                : NSFont.systemFont(ofSize: 12)
            btn.target = self
            btn.action = #selector(selectLang(_:))
            v.addSubview(btn)
        }
        self.view = v
    }

    @objc func selectLang(_ sender: NSButton) {
        let lang = supportedLocales[sender.tag]
        Prefs.save(voiceLocale: lang.id, for: family)
        widget?.voice.setLocale(lang.id)
        popover?.close()
    }
}

// MARK: - Mic button (short press = toggle, long press = language picker)

class MicButton: NSButton {
    var onShortPress: (() -> Void)?
    var onLongPress:  (() -> Void)?
    private var pressTimer: Timer?
    private var isLongPress = false

    override func mouseDown(with event: NSEvent) {
        isLongPress = false
        pressTimer  = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: false) { [weak self] _ in
            self?.isLongPress = true
            self?.onLongPress?()
        }
    }

    override func mouseUp(with event: NSEvent) {
        pressTimer?.invalidate()
        pressTimer = nil
        if !isLongPress { onShortPress?() }
    }

    override func mouseExited(with event: NSEvent) {
        pressTimer?.invalidate()
        pressTimer = nil
    }
}

// MARK: - Voice input manager

class VoiceInputManager {
    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private let engine = AVAudioEngine()
    private var lastText: String = ""
    private(set) var isRecording = false

    var onResult: ((String) -> Void)?
    var onStateChange: ((Bool) -> Void)?

    init(locale: String = "es-MX") {
        recognizer = SFSpeechRecognizer(locale: Locale(identifier: locale))
    }

    func setLocale(_ identifier: String) {
        guard !isRecording else { return }
        recognizer = SFSpeechRecognizer(locale: Locale(identifier: identifier))
    }

    func toggle() {
        if isRecording { stopRecording() } else { requestPermissionsAndStart() }
    }

    private func requestPermissionsAndStart() {
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            guard let self = self, status == .authorized else { return }
            DispatchQueue.main.async { self.startRecording() }
        }
    }

    private func startRecording() {
        guard let recognizer = recognizer, recognizer.isAvailable else { return }

        lastText = ""
        request  = SFSpeechAudioBufferRecognitionRequest()
        guard let req = request else { return }
        req.shouldReportPartialResults = true

        let inputNode = engine.inputNode
        let format    = inputNode.outputFormat(forBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            self?.request?.append(buffer)
        }

        do {
            engine.prepare()
            try engine.start()
        } catch {
            engine.inputNode.removeTap(onBus: 0)
            return
        }

        isRecording = true
        onStateChange?(true)

        task = recognizer.recognitionTask(with: req) { [weak self] result, _ in
            if let result = result {
                self?.lastText = result.bestTranscription.formattedString
            }
        }
    }

    func stopRecording() {
        guard isRecording else { return }
        isRecording = false
        let text = lastText
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.cancel()
        onStateChange?(false)
        if !text.isEmpty {
            DispatchQueue.main.async { self.onResult?(text) }
        }
    }
}

// MARK: - CGEvent injection

func simulatePasteAndReturn() {
    let src = CGEventSource(stateID: .combinedSessionState)

    guard let vDown = CGEvent(keyboardEventSource: src, virtualKey: 9,  keyDown: true),
          let vUp   = CGEvent(keyboardEventSource: src, virtualKey: 9,  keyDown: false) else { return }
    vDown.flags = .maskCommand
    vUp.flags   = .maskCommand
    vDown.post(tap: .cgSessionEventTap)
    vUp.post(tap: .cgSessionEventTap)

    DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
        guard let rDown = CGEvent(keyboardEventSource: src, virtualKey: 36, keyDown: true),
              let rUp   = CGEvent(keyboardEventSource: src, virtualKey: 36, keyDown: false) else { return }
        rDown.flags = CGEventFlags(rawValue: 0)
        rUp.flags   = CGEventFlags(rawValue: 0)
        rDown.post(tap: .cgSessionEventTap)
        rUp.post(tap: .cgSessionEventTap)
    }
}

// MARK: - Widget window

let micIdleColor   = NSColor(calibratedWhite: 0.08, alpha: 0.82)

class WidgetWindow: NSObject, NSWindowDelegate {
    let family: String
    let agentPath: String
    let window: NSWindow
    var onClose: (() -> Void)?
    var configPopover: NSPopover?
    var langPopover:   NSPopover?
    var micBtn: MicButton!
    var voice: VoiceInputManager!

    init(family: String, members: [String], index: Int, path: String) {
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
        self.family    = family
        self.agentPath = path
        super.init()

        window.title = family
        window.collectionBehavior    = [.managed, .participatesInCycle]
        window.isOpaque              = false
        window.titlebarAppearsTransparent = true
        window.titleVisibility       = .hidden
        window.isReleasedWhenClosed  = false
        window.delegate              = self

        let content = window.contentView!

        // Family name label
        let labelWidth = W - 28
        let nameLbl = NSTextField(wrappingLabelWithString: family)
        nameLbl.frame         = NSRect(x: 18, y: H * 0.28, width: labelWidth, height: H * 0.60)
        nameLbl.font          = NSFont.boldSystemFont(ofSize: fitFontSize(text: family, maxWidth: labelWidth))
        nameLbl.textColor     = NSColor(calibratedRed: 0.08, green: 0.08, blue: 0.08, alpha: 1.0)
        nameLbl.backgroundColor = .clear
        nameLbl.drawsBackground = false
        nameLbl.lineBreakMode = .byClipping
        content.addSubview(nameLbl)

        // Members row
        if !members.isEmpty {
            let sub = NSTextField(labelWithString: members.map { $0.uppercased() }.joined(separator: " · "))
            sub.frame           = NSRect(x: 20, y: 10, width: W - 80, height: 20)
            sub.font            = NSFont.systemFont(ofSize: 10, weight: .medium)
            sub.textColor       = NSColor(calibratedRed: 0.22, green: 0.40, blue: 0.08, alpha: 1.0)
            sub.backgroundColor = .clear
            sub.drawsBackground = false
            content.addSubview(sub)
        }

        // Settings button (bottom-right, small)
        let dotsBtn = NSButton(frame: NSRect(x: W - 28, y: 10, width: 18, height: 18))
        if let img = NSImage(systemSymbolName: "ellipsis", accessibilityDescription: "Settings") {
            dotsBtn.image         = img
            dotsBtn.imageScaling  = .scaleProportionallyDown
            dotsBtn.contentTintColor = NSColor(calibratedWhite: 0.15, alpha: 0.45)
        } else {
            dotsBtn.title = "•••"
            dotsBtn.font  = NSFont.systemFont(ofSize: 8)
        }
        dotsBtn.bezelStyle = .inline
        dotsBtn.isBordered = false
        dotsBtn.target     = self
        dotsBtn.action     = #selector(showConfig(_:))
        content.addSubview(dotsBtn)

        // Mic button — larger, darker, prominent
        micBtn = MicButton(frame: NSRect(x: W - 64, y: 3, width: 32, height: 32))
        if let cfg = NSImage.SymbolConfiguration(pointSize: 18, weight: .semibold) as NSImage.SymbolConfiguration?,
           let img = NSImage(systemSymbolName: "mic.fill", accessibilityDescription: "Voice input")?
                        .withSymbolConfiguration(cfg) {
            micBtn.image        = img
            micBtn.imageScaling = .scaleProportionallyDown
        } else if let img = NSImage(systemSymbolName: "mic.fill", accessibilityDescription: "Voice input") {
            micBtn.image        = img
            micBtn.imageScaling = .scaleProportionallyDown
        } else {
            micBtn.title = "🎤"
            micBtn.font  = NSFont.systemFont(ofSize: 14)
        }
        micBtn.contentTintColor = micIdleColor
        micBtn.bezelStyle       = .inline
        micBtn.isBordered       = false

        micBtn.onShortPress = { [weak self] in self?.voice.toggle() }
        micBtn.onLongPress  = { [weak self] in self?.showLangPicker() }
        content.addSubview(micBtn)

        // Voice manager
        voice = VoiceInputManager(locale: Prefs.voiceLocale(for: family))
        voice.onStateChange = { [weak self] active in
            self?.micBtn.contentTintColor = active ? .systemRed : micIdleColor
        }
        voice.onResult = { [weak self] text in
            self?.injectToSession(text)
        }

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
        if let p = configPopover, p.isShown { p.close(); return }
        let p = NSPopover()
        p.contentViewController = ConfigVC(family: family, widget: self)
        p.behavior = .transient
        p.show(relativeTo: sender.bounds, of: sender, preferredEdge: .maxY)
        configPopover = p
    }

    func showLangPicker() {
        if let p = langPopover, p.isShown { p.close(); return }
        let p = NSPopover()
        p.contentViewController = LangPickerVC(family: family, widget: self, popover: p)
        p.behavior = .transient
        p.show(relativeTo: micBtn.bounds, of: micBtn, preferredEdge: .maxY)
        langPopover = p
        // Blue tint while picker is open
        micBtn.contentTintColor = .systemBlue
        p.contentViewController?.view.window?.windowController?.window?.makeKeyAndOrderFront(nil)
    }

    private func injectToSession(_ text: String) {
        guard AXIsProcessTrusted() else {
            let opts = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
            AXIsProcessTrustedWithOptions(opts)
            micBtn.contentTintColor = .systemOrange
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
                self?.micBtn.contentTintColor = micIdleColor
            }
            return
        }

        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)

        lastNonWidgetApp?.activate(options: .activateIgnoringOtherApps)

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            simulatePasteAndReturn()
        }

        micBtn.contentTintColor = .systemGreen
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak self] in
            self?.micBtn.contentTintColor = micIdleColor
        }
    }

    func windowWillClose(_: Notification) { onClose?() }
}

// MARK: - App icon

func makeAppIcon() -> NSImage {
    let size: CGFloat = 512
    let img = NSImage(size: NSSize(width: size, height: size))
    img.lockFocus()

    let ctx = NSGraphicsContext.current!.cgContext

    let bg = NSBezierPath(roundedRect: NSRect(x: 0, y: 0, width: size, height: size), xRadius: 110, yRadius: 110)
    NSColor(calibratedRed: 0.07, green: 0.07, blue: 0.16, alpha: 1).setFill()
    bg.fill()

    let center = CGPoint(x: size / 2, y: size / 2)
    let colors = [
        CGColor(red: 0.18, green: 0.18, blue: 0.36, alpha: 0.8),
        CGColor(red: 0.07, green: 0.07, blue: 0.16, alpha: 0)
    ]
    if let grad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(),
                              colors: colors as CFArray, locations: [0, 1]) {
        ctx.drawRadialGradient(grad,
                               startCenter: center, startRadius: 0,
                               endCenter: center, endRadius: size * 0.62,
                               options: [])
    }

    let cx = size / 2, cy = size / 2
    let ring: CGFloat = 148
    var nodes: [CGPoint] = [CGPoint(x: cx, y: cy)]
    for i in 0..<6 {
        let angle = CGFloat(i) * .pi / 3 - .pi / 6
        nodes.append(CGPoint(x: cx + ring * cos(angle), y: cy + ring * sin(angle)))
    }

    let outerRing: CGFloat = 215
    var outerNodes: [CGPoint] = []
    for i in 0..<6 {
        let angle = CGFloat(i) * .pi / 3
        outerNodes.append(CGPoint(x: cx + outerRing * cos(angle), y: cy + outerRing * sin(angle)))
    }

    let edgeColor = NSColor(calibratedRed: 0.44, green: 0.82, blue: 0.72, alpha: 0.30)
    edgeColor.setStroke()
    for n in nodes.dropFirst() {
        let path = NSBezierPath(); path.lineWidth = 1.8
        path.move(to: nodes[0]); path.line(to: n); path.stroke()
    }
    for i in 1...6 {
        let next = i == 6 ? 1 : i + 1
        let path = NSBezierPath(); path.lineWidth = 1.5
        edgeColor.setStroke()
        path.move(to: nodes[i]); path.line(to: nodes[next]); path.stroke()
    }

    let outerEdgeColor = NSColor(calibratedRed: 0.44, green: 0.82, blue: 0.72, alpha: 0.15)
    outerEdgeColor.setStroke()
    for i in 0..<6 {
        let path = NSBezierPath(); path.lineWidth = 1.2
        path.move(to: nodes[i + 1]); path.line(to: outerNodes[i]); path.stroke()
    }

    for pt in outerNodes {
        let r: CGFloat = 6
        let dot = NSBezierPath(ovalIn: NSRect(x: pt.x-r, y: pt.y-r, width: r*2, height: r*2))
        NSColor(calibratedRed: 0.44, green: 0.82, blue: 0.72, alpha: 0.45).setFill(); dot.fill()
    }
    for pt in nodes.dropFirst() {
        let r: CGFloat = 11
        let dot  = NSBezierPath(ovalIn: NSRect(x: pt.x-r, y: pt.y-r, width: r*2, height: r*2))
        NSColor(calibratedRed: 0.44, green: 0.82, blue: 0.72, alpha: 0.85).setFill(); dot.fill()
        let glow = NSBezierPath(ovalIn: NSRect(x: pt.x-r-3, y: pt.y-r-3, width: (r+3)*2, height: (r+3)*2))
        NSColor(calibratedRed: 0.44, green: 0.82, blue: 0.72, alpha: 0.12).setFill(); glow.fill()
    }

    let cr: CGFloat = 22
    let glow2 = NSBezierPath(ovalIn: NSRect(x: cx-cr-8, y: cy-cr-8, width: (cr+8)*2, height: (cr+8)*2))
    NSColor(calibratedRed: 0.44, green: 0.82, blue: 0.72, alpha: 0.15).setFill(); glow2.fill()
    let centerDot = NSBezierPath(ovalIn: NSRect(x: cx-cr, y: cy-cr, width: cr*2, height: cr*2))
    NSColor(calibratedRed: 0.56, green: 0.90, blue: 0.80, alpha: 1).setFill(); centerDot.fill()

    img.unlockFocus()
    return img
}

// MARK: - App delegate

class AppDelegate: NSObject, NSApplicationDelegate {
    var widgets: [String: WidgetWindow] = [:]
    var closedByUser: Set<String> = []

    func applicationDidFinishLaunching(_: Notification) {
        NSApp.applicationIconImage = makeAppIcon()

        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification,
            object: nil, queue: .main
        ) { n in
            let app = n.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication
            if app?.bundleIdentifier != Bundle.main.bundleIdentifier {
                lastNonWidgetApp = app
            }
        }

        guard let agents = fetchAgents() else { return }
        for (idx, family) in agents.keys.sorted().enumerated() {
            guard let info = agents[family] else { continue }
            let members = info["members"] as? [String] ?? []
            let path    = info["path"]    as? String  ?? ""
            spawnWidget(family: family, members: members, index: idx, path: path)
        }
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls {
            guard url.scheme == "localagentsociety",
                  let family = url.host, !family.isEmpty else { continue }
            openWidget(for: family)
        }
    }

    func applicationShouldHandleReopen(_ app: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows {
            closedByUser.removeAll()
            guard let agents = fetchAgents() else { return true }
            for (idx, family) in agents.keys.sorted().enumerated() {
                guard let info = agents[family] else { continue }
                let members = info["members"] as? [String] ?? []
                let path    = info["path"]    as? String  ?? ""
                spawnWidget(family: family, members: members, index: idx, path: path)
            }
        }
        return true
    }

    func applicationDockMenu(_: NSApplication) -> NSMenu? {
        guard let agents = fetchAgents(), !agents.isEmpty else { return nil }
        let menu = NSMenu()
        for family in agents.keys.sorted() {
            let item = NSMenuItem(title: family, action: #selector(focusAgent(_:)), keyEquivalent: "")
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

    func openWidget(for family: String) {
        closedByUser.remove(family)
        if let w = widgets[family] {
            w.window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        guard let agents = fetchAgents(), let info = agents[family] else { return }
        let idx     = agents.keys.sorted().firstIndex(of: family) ?? 0
        let members = info["members"] as? [String] ?? []
        let path    = info["path"]    as? String  ?? ""
        spawnWidget(family: family, members: members, index: idx, path: path)
    }

    private func spawnWidget(family: String, members: [String], index: Int, path: String) {
        guard widgets[family] == nil else { return }
        let widget = WidgetWindow(family: family, members: members, index: index, path: path)
        widget.onClose = { [weak self] in
            self?.closedByUser.insert(family)
            self?.widgets.removeValue(forKey: family)
        }
        widgets[family] = widget
    }

    func fetchAgents() -> [String: [String: Any]]? {
        guard let url  = URL(string: "http://localhost:8700/agents"),
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
