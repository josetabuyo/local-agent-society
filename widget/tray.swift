import AppKit
import Foundation
import Speech
import AVFoundation


// MARK: - Font helper

func smartSplit(_ text: String) -> String {
    let chars = Array(text)
    let mid = chars.count / 2

    // Priority 1: split at space or hyphen closest to middle
    var bestSpaceIdx: Int? = nil
    var bestSpaceDist = Int.max
    for i in 0..<chars.count {
        if chars[i] == " " || chars[i] == "-" {
            let dist = abs(i - mid)
            if dist < bestSpaceDist { bestSpaceDist = dist; bestSpaceIdx = i }
        }
    }
    if let idx = bestSpaceIdx {
        let before = String(chars[0..<idx]).trimmingCharacters(in: .whitespaces)
        let after  = String(chars[min(idx + 1, chars.count)...]).trimmingCharacters(in: .whitespaces)
        if !before.isEmpty && !after.isEmpty { return before + "\n" + after }
    }

    // Priority 2: CamelCase boundary closest to middle
    var bestCamelIdx: Int? = nil
    var bestCamelDist = Int.max
    for i in 1..<chars.count {
        if chars[i].isUppercase && chars[i-1].isLowercase {
            let dist = abs(i - mid)
            if dist < bestCamelDist { bestCamelDist = dist; bestCamelIdx = i }
        }
    }
    if let idx = bestCamelIdx {
        return String(chars[0..<idx]) + "\n" + String(chars[idx...])
    }

    return text
}

func measuredWidth(_ text: String, size: CGFloat) -> CGFloat {
    (text as NSString).size(withAttributes: [
        .font: NSFont.systemFont(ofSize: size, weight: .heavy),
        .kern: CGFloat(1.5),
    ]).width
}

func fitFontSizeAndSplit(text: String, maxWidth: CGFloat, start: CGFloat = 62, min: CGFloat = 14) -> (CGFloat, String) {
    // Try single-line
    var size = start
    while size > 30 {
        if measuredWidth(text, size: size) <= maxWidth { return (size, text) }
        size -= 1
    }

    // Try split version
    let splitText = smartSplit(text)
    if splitText != text {
        let lines = splitText.components(separatedBy: "\n")
        let labelH: CGFloat = 96
        var splitSize = Swift.min(start, floor(labelH / 2.6))  // ~36pt max for two lines
        while splitSize > min {
            let maxW = lines.map { measuredWidth($0, size: splitSize) }.max() ?? 0
            if maxW <= maxWidth { return (splitSize, splitText) }
            splitSize -= 1
        }
        return (min, splitText)
    }

    // No split possible, keep shrinking
    while size > min {
        if measuredWidth(text, size: size) <= maxWidth { return (size, text) }
        size -= 1
    }
    return (min, text)
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

// Derive a default speech-recognition locale from the TTS voice name.
// Only Spanish and Brazilian voices deviate from en-US in our NICE_VOICES set.
func inferLocaleFromVoice(_ voice: String) -> String {
    let v = voice.lowercased()
    if v == "paulina" || v == "mónica" || v == "monica" { return "es-MX" }
    if v.contains("português") || v == "luciana" || v == "felipe" { return "pt-BR" }
    if v.contains("français") || v == "thomas" || v == "aurelie" { return "fr-FR" }
    if v.contains("deutsch") || v == "anna" || v == "markus" || v == "petra" { return "de-DE" }
    return "en-US"
}

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
    private var engine = AVAudioEngine()
    private var lastText: String = ""
    private(set) var isRecording = false

    var onResult: ((String) -> Void)?
    var onStateChange: ((Bool) -> Void)?

    init(locale: String = "es-MX") {
        recognizer = SFSpeechRecognizer(locale: Locale(identifier: locale))
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(engineConfigChanged),
            name: .AVAudioEngineConfigurationChange,
            object: engine
        )
    }

    // Fired when another app interrupts the audio hardware (video, music, etc.)
    @objc private func engineConfigChanged(_ notification: Notification) {
        guard isRecording else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.teardownEngine()
            self.engine = AVAudioEngine()
            NotificationCenter.default.addObserver(
                self,
                selector: #selector(self.engineConfigChanged),
                name: .AVAudioEngineConfigurationChange,
                object: self.engine
            )
            self.startRecording()
        }
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
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: nil) { [weak self] buffer, _ in
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

    private func teardownEngine() {
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.cancel()
        request = nil
        task = nil
    }

    func stopRecording() {
        guard isRecording else { return }
        isRecording = false
        let text = lastText
        teardownEngine()
        onStateChange?(false)
        if !text.isEmpty {
            DispatchQueue.main.async { self.onResult?(text) }
        }
    }
}

// MARK: - Outlined label

class OutlinedLabel: NSView {
    var text: String = "" { didSet { needsDisplay = true } }
    var textFont: NSFont = NSFont.systemFont(ofSize: 48, weight: .heavy)
    var fillColor: NSColor = .black  { didSet { needsDisplay = true } }
    var strokeOpacity: CGFloat = 0.72

    override var isFlipped: Bool { true }

    override func draw(_ dirtyRect: NSRect) {
        let paragraphStyle = NSMutableParagraphStyle()
        paragraphStyle.lineBreakMode = .byWordWrapping
        let base: [NSAttributedString.Key: Any] = [
            .font: textFont,
            .kern: CGFloat(1.5),
            .paragraphStyle: paragraphStyle,
        ]
        let shadow = NSShadow()
        shadow.shadowColor      = NSColor.white.withAlphaComponent(strokeOpacity * 0.90)
        shadow.shadowBlurRadius = 2.0
        shadow.shadowOffset     = .zero

        var fillAttrs = base
        fillAttrs[.foregroundColor] = fillColor
        fillAttrs[.shadow]          = shadow
        NSAttributedString(string: text, attributes: fillAttrs).draw(in: bounds)
    }
}

func drawMicImage(fill: NSColor, stroke: NSColor) -> NSImage {
    NSImage(size: NSSize(width: 40, height: 40), flipped: true) { bounds in
        let cx = bounds.midX

        // Capsule body
        let bodyW: CGFloat = 14, bodyH: CGFloat = 20
        let body = NSBezierPath(roundedRect: NSRect(x: cx - bodyW/2, y: 3,
                                                    width: bodyW, height: bodyH),
                                xRadius: bodyW/2, yRadius: bodyW/2)
        fill.setFill();   body.fill()
        stroke.setStroke(); body.lineWidth = 1.3; body.stroke()

        // Arc stand (∪ below body)
        let arc = NSBezierPath()
        arc.move(to: NSPoint(x: cx - 13, y: 16))
        arc.curve(to: NSPoint(x: cx + 13, y: 16),
                  controlPoint1: NSPoint(x: cx - 13, y: 32),
                  controlPoint2: NSPoint(x: cx + 13, y: 32))
        arc.lineWidth = 1.3; arc.stroke()

        // Vertical stem
        let stem = NSBezierPath()
        stem.move(to: NSPoint(x: cx, y: 32))
        stem.line(to: NSPoint(x: cx, y: 37))
        stem.lineWidth = 1.3; stem.stroke()

        // Base
        let base = NSBezierPath()
        base.move(to: NSPoint(x: cx - 8, y: 37))
        base.line(to: NSPoint(x: cx + 8, y: 37))
        base.lineWidth = 1.8; base.stroke()

        return true
    }
}

func drawDotsImage(fill: NSColor, stroke: NSColor) -> NSImage {
    NSImage(size: NSSize(width: 28, height: 28), flipped: true) { bounds in
        let r: CGFloat = 3.5
        let cy = bounds.midY
        fill.setFill(); stroke.setStroke()
        for cx in [CGFloat(4.0), CGFloat(14), CGFloat(24.0)] {
            let dot = NSBezierPath(ovalIn: NSRect(x: cx - r, y: cy - r, width: r*2, height: r*2))
            dot.fill()
            dot.lineWidth = 1.0; dot.stroke()
        }
        return true
    }
}

// MARK: - Widget window



class WidgetWindow: NSObject, NSWindowDelegate {
    let family: String
    let agentPath: String
    let agentVoice: String
    let window: NSWindow
    var onClose: (() -> Void)?
    var configPopover: NSPopover?
    var langPopover:   NSPopover?
    var nameLbl: OutlinedLabel!
    var dotsBtn: NSButton!
    var micBtn: MicButton!
    var infoBtn: NSButton!
    var voice: VoiceInputManager!
    var idleFill: NSColor = NSColor.black.withAlphaComponent(0.85)

    var isInfoExpanded = false
    var infoPanelView: NSView?
    var infoKeyLabels: [NSTextField] = []
    var infoValLabels: [NSTextField] = []

    static let infoH: CGFloat = 90

    init(family: String, index: Int, path: String, voice agentVoiceArg: String = "") {
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
        self.family     = family
        self.agentPath  = path
        self.agentVoice = agentVoiceArg
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
        let (fontSize, displayText) = fitFontSizeAndSplit(text: family, maxWidth: labelWidth)
        nameLbl = OutlinedLabel(frame: NSRect(x: 18, y: H * 0.28, width: labelWidth, height: H * 0.60))
        nameLbl.text       = displayText
        nameLbl.textFont   = NSFont.systemFont(ofSize: fontSize, weight: .heavy)
        content.addSubview(nameLbl)

        // Settings button (bottom-right, small)
        dotsBtn = NSButton(frame: NSRect(x: W - 44, y: 10, width: 28, height: 28))
        let dotsImg = drawDotsImage(
            fill: NSColor.white.withAlphaComponent(0.12),
            stroke: NSColor.white.withAlphaComponent(0.88)
        )
        dotsBtn.image = dotsImg
        dotsBtn.imageScaling = .scaleAxesIndependently
        dotsBtn.bezelStyle = .inline
        dotsBtn.isBordered = false
        dotsBtn.target     = self
        dotsBtn.action     = #selector(showConfig(_:))
        content.addSubview(dotsBtn)

        // Mic button — larger, darker, prominent
        micBtn = MicButton(frame: NSRect(x: W - 92, y: 10, width: 40, height: 40))
        updateMicIcon(color: idleFill)
        micBtn.bezelStyle       = .inline
        micBtn.isBordered       = false

        micBtn.onShortPress = { [weak self] in self?.voice.toggle() }
        micBtn.onLongPress  = { [weak self] in self?.showLangPicker() }
        content.addSubview(micBtn)

        // Info button — bottom-left
        infoBtn = NSButton(frame: NSRect(x: 10, y: 10, width: 28, height: 28))
        infoBtn.image = NSImage(systemSymbolName: "info.circle", accessibilityDescription: "Info")
        infoBtn.imageScaling = .scaleProportionallyUpOrDown
        infoBtn.bezelStyle = .inline
        infoBtn.isBordered = false
        infoBtn.target = self
        infoBtn.action = #selector(toggleInfo(_:))
        content.addSubview(infoBtn)

        // Voice manager — seed locale from TTS voice on first run if user never set it
        if UserDefaults.standard.string(forKey: "voiceLocale.\(family)") == nil && !agentVoice.isEmpty {
            Prefs.save(voiceLocale: inferLocaleFromVoice(agentVoice), for: family)
        }
        voice = VoiceInputManager(locale: Prefs.voiceLocale(for: family))
        voice.onStateChange = { [weak self] active in
            self?.updateMicIcon(color: active ? .systemRed : (self?.idleFill ?? .black))
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
        let opacity = Prefs.opacity(for: family)
        let bgColor = Prefs.color(for: family)
        window.backgroundColor = bgColor.withAlphaComponent(opacity)
        window.level = Prefs.ontop(for: family) ? .floating : .normal

        // Shared dark fill: 85% black + 15% background tint, darker than before
        let darkFill = (NSColor.black.blended(withFraction: 0.15, of: bgColor) ?? .black)
            .withAlphaComponent(min(opacity * 1.6, 0.98))
        idleFill = darkFill

        nameLbl?.fillColor     = darkFill
        nameLbl?.strokeOpacity = opacity
        nameLbl?.needsDisplay  = true

        dotsBtn?.alphaValue = opacity
        micBtn?.alphaValue  = opacity
        infoBtn?.alphaValue = opacity
        let strokeA = min(opacity * 1.1 + 0.1, 1.0)
        dotsBtn?.image = drawDotsImage(fill: darkFill, stroke: NSColor.white.withAlphaComponent(strokeA))
        dotsBtn?.imageScaling = .scaleAxesIndependently
        updateMicIcon(color: idleFill)
        let infoBtnTint = isInfoExpanded
            ? NSColor.white.withAlphaComponent(min(strokeA + 0.15, 1.0))
            : NSColor.white.withAlphaComponent(strokeA)
        infoBtn?.contentTintColor = infoBtnTint

        if isInfoExpanded {
            let (panelBg, textColor) = infoPanelColors()
            infoPanelView?.layer?.backgroundColor = panelBg.cgColor
            for lbl in infoKeyLabels { lbl.textColor = textColor.withAlphaComponent(0.60) }
            for lbl in infoValLabels { lbl.textColor = textColor }
        }
    }

    @objc func showConfig(_ sender: NSButton) {
        if let p = configPopover, p.isShown { p.close(); return }
        let p = NSPopover()
        p.contentViewController = ConfigVC(family: family, widget: self)
        p.behavior = .transient
        p.show(relativeTo: sender.bounds, of: sender, preferredEdge: .maxY)
        configPopover = p
    }

    func updateMicIcon(color: NSColor) {
        let img = drawMicImage(fill: color, stroke: NSColor.white.withAlphaComponent(0.85))
        micBtn.image = img
        micBtn.imageScaling = .scaleAxesIndependently
    }

    // MARK: Info panel

    @objc func toggleInfo(_ sender: NSButton) {
        isInfoExpanded.toggle()
        let content = window.contentView!
        let curFrame = window.frame
        let addH = WidgetWindow.infoH

        if isInfoExpanded {
            let newWinFrame = NSRect(x: curFrame.minX, y: curFrame.minY - addH,
                                     width: curFrame.width, height: curFrame.height + addH)
            window.setFrame(newWinFrame, display: false)
            for sub in content.subviews { sub.frame = sub.frame.offsetBy(dx: 0, dy: addH) }
            infoBtn?.contentTintColor = NSColor.white.withAlphaComponent(min(Prefs.opacity(for: family) * 1.1 + 0.25, 1.0))
            fetchAgentPorts { [weak self] ports in
                DispatchQueue.main.async {
                    guard let self = self else { return }
                    let panel = self.makeInfoPanel(ports: ports)
                    content.addSubview(panel)
                    self.infoPanelView = panel
                    self.window.display()
                }
            }
        } else {
            infoPanelView?.removeFromSuperview()
            infoPanelView = nil
            infoKeyLabels = []
            infoValLabels = []
            for sub in content.subviews { sub.frame = sub.frame.offsetBy(dx: 0, dy: -addH) }
            let newWinFrame = NSRect(x: curFrame.minX, y: curFrame.minY + addH,
                                     width: curFrame.width, height: curFrame.height - addH)
            window.setFrame(newWinFrame, display: true)
            infoBtn?.contentTintColor = NSColor.white.withAlphaComponent(min(Prefs.opacity(for: family) * 1.1 + 0.1, 1.0))
        }
    }

    private func infoPanelColors() -> (bg: NSColor, text: NSColor) {
        let bgColor = Prefs.color(for: family)
        let panelBg  = bgColor.blended(withFraction: 0.22, of: NSColor.black) ?? bgColor
        let textColor = panelBg.blended(withFraction: 0.32, of: NSColor.white) ?? NSColor.white
        return (panelBg, textColor)
    }

    private func makeInfoPanel(ports: [Int]) -> NSView {
        let W: CGFloat = 300
        let H = WidgetWindow.infoH
        let (panelBg, textColor) = infoPanelColors()

        let panel = NSView(frame: NSRect(x: 0, y: 0, width: W, height: H))
        panel.wantsLayer = true
        panel.layer?.backgroundColor = panelBg.cgColor

        let sep = NSView(frame: NSRect(x: 0, y: H - 1, width: W, height: 1))
        sep.wantsLayer = true
        sep.layer?.backgroundColor = textColor.withAlphaComponent(0.20).cgColor
        panel.addSubview(sep)

        let rows: [(key: String, value: String)] = [
            ("Voice",  agentVoice.isEmpty ? "—" : agentVoice),
            ("Speech", localeName(for: Prefs.voiceLocale(for: family))),
            ("Ports",  ports.isEmpty ? "None" : ports.map { String($0) }.joined(separator: " · ")),
        ]

        infoKeyLabels = []
        infoValLabels = []

        for (i, row) in rows.enumerated() {
            let yPos: CGFloat = H - 22 - CGFloat(i) * 22

            let keyLbl = NSTextField(labelWithString: row.key)
            keyLbl.font = NSFont.systemFont(ofSize: 10, weight: .semibold)
            keyLbl.textColor = textColor.withAlphaComponent(0.60)
            keyLbl.backgroundColor = .clear
            keyLbl.drawsBackground = false
            keyLbl.frame = NSRect(x: 16, y: yPos, width: 52, height: 15)
            panel.addSubview(keyLbl)
            infoKeyLabels.append(keyLbl)

            let valLbl = NSTextField(labelWithString: row.value)
            valLbl.font = NSFont.systemFont(ofSize: 10, weight: .regular)
            valLbl.textColor = textColor
            valLbl.backgroundColor = .clear
            valLbl.drawsBackground = false
            valLbl.frame = NSRect(x: 72, y: yPos, width: W - 88, height: 15)
            panel.addSubview(valLbl)
            infoValLabels.append(valLbl)
        }

        return panel
    }

    private func localeName(for localeId: String) -> String {
        supportedLocales.first(where: { $0.id == localeId })
            .map { "\($0.flag) \($0.name)" } ?? localeId
    }

    private func fetchAgentPorts(completion: @escaping ([Int]) -> Void) {
        guard let url = URL(string: "http://localhost:8700/ports") else {
            completion([]); return
        }
        URLSession.shared.dataTask(with: url) { [weak self] data, _, _ in
            guard let self = self,
                  let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: [String: Any]]
            else { completion([]); return }
            let ports = json.compactMap { (_, val) -> Int? in
                // Old registrations use "agent_family"; new /ports/claim uses "local_agent"
                let fam = (val["agent_family"] as? String) ?? (val["local_agent"] as? String)
                guard let fam = fam, fam == self.family,
                      let p = val["port"] as? Int else { return nil }
                return p
            }.sorted()
            completion(ports)
        }.resume()
    }

    func showLangPicker() {
        if let p = langPopover, p.isShown { p.close(); return }
        let p = NSPopover()
        p.contentViewController = LangPickerVC(family: family, widget: self, popover: p)
        p.behavior = .transient
        p.show(relativeTo: micBtn.bounds, of: micBtn, preferredEdge: .maxY)
        langPopover = p
        // Blue tint while picker is open
        updateMicIcon(color: .systemBlue)
        p.contentViewController?.view.window?.windowController?.window?.makeKeyAndOrderFront(nil)
    }

    private func injectToSession(_ text: String) {
        NSLog("[inject] → name=%@ len=%d text=%@", family, text.count, text)
        guard let url = URL(string: "http://localhost:8700/agents/\(family)/inject") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: [
            "message": text,
            "source":  "voice",
        ])
        req.timeoutInterval = 5

        URLSession.shared.dataTask(with: req) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self = self else { return }
                let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                guard status == 200, let data = data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                else {
                    NSLog("[inject] ✗ name=%@ HTTP status=%d error=%@", self.family, status, error?.localizedDescription ?? "nil")
                    self.updateMicIcon(color: .systemOrange)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak self] in
                        self?.updateMicIcon(color: self?.idleFill ?? .black)
                    }
                    return
                }
                let injected = json["injected"] as? Bool ?? false
                let tty = json["tty"] as? String ?? "?"
                NSLog("[inject] ✓ name=%@ injected=%@ tty=%@", self.family, injected ? "true" : "false", tty)
                // green = live injection into terminal; yellow = inbox only (agent not at prompt)
                self.updateMicIcon(color: injected ? .systemGreen : .systemYellow)
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak self] in
                    self?.updateMicIcon(color: self?.idleFill ?? .black)
                }
            }
        }.resume()
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

        guard let agents = fetchAgents() else { return }
        for (idx, family) in agents.keys.sorted().enumerated() {
            guard let info = agents[family] else { continue }
            let path  = info["path"]  as? String ?? ""
            let voice = info["voice"] as? String ?? ""
            spawnWidget(family: family, index: idx, path: path, voice: voice)
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
                let path  = info["path"]  as? String ?? ""
                let voice = info["voice"] as? String ?? ""
                spawnWidget(family: family, index: idx, path: path, voice: voice)
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
        let idx   = agents.keys.sorted().firstIndex(of: family) ?? 0
        let path  = info["path"]  as? String ?? ""
        let voice = info["voice"] as? String ?? ""
        spawnWidget(family: family, index: idx, path: path, voice: voice)
    }

    private func spawnWidget(family: String, index: Int, path: String, voice: String = "") {
        guard widgets[family] == nil else { return }
        let widget = WidgetWindow(family: family, index: index, path: path, voice: voice)
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
