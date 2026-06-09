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

// MARK: - Persistent prefs per agent

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
        return UserDefaults.standard.string(forKey: "voiceLocale.\(f)") ?? "en-US"
    }
    static func voiceLocaleIsManual(for f: String) -> Bool {
        return UserDefaults.standard.bool(forKey: "voiceLocaleManual.\(f)")
    }
    static func markVoiceLocaleManual(for f: String) {
        UserDefaults.standard.set(true, forKey: "voiceLocaleManual.\(f)")
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
    static func expandOnSpaceChange(for f: String) -> Bool {
        guard UserDefaults.standard.object(forKey: "expandOnSpace.\(f)") != nil else { return false }
        return UserDefaults.standard.bool(forKey: "expandOnSpace.\(f)")
    }
    static func save(voiceLocale locale: String, for f: String) {
        UserDefaults.standard.set(locale, forKey: "voiceLocale.\(f)")
    }
    static func save(expandOnSpaceChange v: Bool, for f: String) {
        UserDefaults.standard.set(v, forKey: "expandOnSpace.\(f)")
    }
    static func muted(for f: String) -> Bool {
        return UserDefaults.standard.bool(forKey: "muted.\(f)")
    }
    static func save(muted v: Bool, for f: String) {
        UserDefaults.standard.set(v, forKey: "muted.\(f)")
    }
}

// MARK: - Config popover

class ConfigVC: NSViewController {
    let agentName: String
    weak var widget: WidgetWindow?
    var colorWell: NSColorWell!
    var opacitySlider: NSSlider!
    var ontopCheck: NSButton!
    var expandCheck: NSButton!
    var voiceNameVal: NSTextField!
    var voiceLangVal: NSTextField!
    var voicePickerPopover: NSPopover?

    init(agentName: String, widget: WidgetWindow) {
        self.agentName = agentName
        self.widget = widget
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError() }

    override func loadView() {
        let W: CGFloat = 220, pad: CGFloat = 14
        let H: CGFloat = 264

        // ── Color ─────────────────────────────────────────────────────────────
        let colorLbl = rowLabel("Color")
        colorLbl.frame = NSRect(x: pad, y: 228, width: 60, height: 15)

        colorWell = NSColorWell(frame: NSRect(x: W - pad - 36, y: 224, width: 36, height: 24))
        colorWell.color = Prefs.color(for: agentName)
        colorWell.target = self
        colorWell.action = #selector(colorChanged(_:))

        // ── Opacity ───────────────────────────────────────────────────────────
        let opacLbl = rowLabel("Opacity")
        opacLbl.frame = NSRect(x: pad, y: 194, width: 60, height: 15)

        opacitySlider = NSSlider(value: Prefs.opacity(for: agentName),
                                  minValue: 0.1, maxValue: 1.0,
                                  target: self, action: #selector(opacityChanged(_:)))
        opacitySlider.frame = NSRect(x: pad, y: 172, width: W - pad * 2, height: 18)

        // ── Checkboxes ────────────────────────────────────────────────────────
        ontopCheck = NSButton(checkboxWithTitle: "Always on top",
                               target: self, action: #selector(ontopChanged(_:)))
        ontopCheck.state = Prefs.ontop(for: agentName) ? .on : .off
        ontopCheck.frame = NSRect(x: pad, y: 136, width: W - pad * 2, height: 20)
        ontopCheck.font = NSFont.systemFont(ofSize: 11)

        expandCheck = NSButton(checkboxWithTitle: "Expand on space change",
                                target: self, action: #selector(expandChanged(_:)))
        expandCheck.state = Prefs.expandOnSpaceChange(for: agentName) ? .on : .off
        expandCheck.frame = NSRect(x: pad, y: 112, width: W - pad * 2, height: 20)
        expandCheck.font = NSFont.systemFont(ofSize: 11)

        // ── Separator ─────────────────────────────────────────────────────────
        let sep = NSView(frame: NSRect(x: pad, y: 98, width: W - pad * 2, height: 1))
        sep.wantsLayer = true
        sep.layer?.backgroundColor = NSColor.separatorColor.cgColor

        // ── Voice section ─────────────────────────────────────────────────────
        let curVoice = widget?.agentVoice ?? ""
        let voiceInfo = allVoices.first(where: { $0.name == curVoice })

        let voiceSectionLbl = rowLabel("Voice")
        voiceSectionLbl.frame = NSRect(x: pad, y: 76, width: 50, height: 15)

        voiceNameVal = NSTextField(labelWithString: curVoice.isEmpty ? "—" : curVoice)
        voiceNameVal.frame = NSRect(x: pad + 54, y: 76, width: W - pad * 2 - 54, height: 15)
        voiceNameVal.font = NSFont.systemFont(ofSize: 11, weight: .semibold)
        voiceNameVal.textColor = .labelColor
        voiceNameVal.alignment = .right

        let langSectionLbl = rowLabel("Language")
        langSectionLbl.frame = NSRect(x: pad, y: 56, width: 64, height: 15)

        let langStr = voiceInfo.map { "\($0.flag) \($0.lang)" } ?? "—"
        voiceLangVal = NSTextField(labelWithString: langStr)
        voiceLangVal.frame = NSRect(x: pad + 68, y: 56, width: W - pad * 2 - 68, height: 15)
        voiceLangVal.font = NSFont.monospacedSystemFont(ofSize: 10, weight: .medium)
        voiceLangVal.textColor = .secondaryLabelColor
        voiceLangVal.alignment = .right

        let btnW: CGFloat = (W - pad * 2 - 6) / 2
        let testBtn = NSButton(frame: NSRect(x: pad, y: 20, width: btnW, height: 22))
        testBtn.title = "Test voice"
        testBtn.bezelStyle = .rounded
        testBtn.font = NSFont.systemFont(ofSize: 10)
        testBtn.target = self
        testBtn.action = #selector(testVoiceTapped(_:))

        let changeBtn = NSButton(frame: NSRect(x: pad + btnW + 6, y: 20, width: btnW, height: 22))
        changeBtn.title = "Change voice…"
        changeBtn.bezelStyle = .rounded
        changeBtn.font = NSFont.systemFont(ofSize: 10)
        changeBtn.target = self
        changeBtn.action = #selector(changeVoiceTapped(_:))

        let v = NSView(frame: NSRect(x: 0, y: 0, width: W, height: H))
        [colorLbl, colorWell, opacLbl, opacitySlider, ontopCheck, expandCheck,
         sep, voiceSectionLbl, voiceNameVal, langSectionLbl, voiceLangVal, testBtn, changeBtn
        ].forEach { v.addSubview($0) }
        self.view = v
    }

    private func rowLabel(_ s: String) -> NSTextField {
        let f = NSTextField(labelWithString: s)
        f.font = NSFont.systemFont(ofSize: 11, weight: .medium)
        f.textColor = .secondaryLabelColor
        return f
    }

    func refreshVoiceDisplay() {
        guard let w = widget else { return }
        let info = allVoices.first(where: { $0.name == w.agentVoice })
        voiceNameVal.stringValue = w.agentVoice.isEmpty ? "—" : w.agentVoice
        voiceLangVal.stringValue = info.map { "\($0.flag) \($0.lang)" } ?? "—"
    }

    @objc func colorChanged(_ sender: NSColorWell) {
        Prefs.save(color: sender.color, for: agentName)
        widget?.applyPrefs()
    }
    @objc func opacityChanged(_ sender: NSSlider) {
        Prefs.save(opacity: sender.doubleValue, for: agentName)
        widget?.applyPrefs()
    }
    @objc func ontopChanged(_ sender: NSButton) {
        Prefs.save(ontop: sender.state == .on, for: agentName)
        widget?.applyPrefs()
    }
    @objc func expandChanged(_ sender: NSButton) {
        Prefs.save(expandOnSpaceChange: sender.state == .on, for: agentName)
    }

    @objc func testVoiceTapped(_ sender: NSButton) {
        guard let w = widget, !w.agentVoice.isEmpty else { return }
        let lang = allVoices.first(where: { $0.name == w.agentVoice })?.lang ?? "en-US"
        let text = lang.hasPrefix("es") ? "Hola, soy \(w.agentName)" : "Hello, I'm \(w.agentName)"
        guard let url = URL(string: "http://localhost:8700/queue/speak") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: [
            "text": text, "voice": w.agentVoice, "name": w.agentName,
        ])
        req.timeoutInterval = 3
        URLSession.shared.dataTask(with: req).resume()
    }

    @objc func changeVoiceTapped(_ sender: NSButton) {
        if let p = voicePickerPopover, p.isShown { p.close(); voicePickerPopover = nil; return }
        guard let w = widget else { return }
        let p = NSPopover()
        let vc = VoicePickerVC(agentName: agentName, widget: w, popover: p) { [weak self] in
            self?.refreshVoiceDisplay()
        }
        p.contentViewController = vc
        p.behavior = .transient
        p.show(relativeTo: sender.bounds, of: sender, preferredEdge: .maxY)
        voicePickerPopover = p
    }
}

extension ConfigVC: NSPopoverDelegate {
    func popoverWillClose(_ notification: Notification) {
        colorWell.deactivate()
        if NSColorPanel.shared.isVisible {
            NSColorPanel.shared.orderOut(nil)
        }
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

// TTS voice catalogue — name must match exactly what `say -v '?'` outputs.
let allVoices: [(name: String, lang: String, flag: String)] = [
    ("Samantha",               "en-US", "🇺🇸"),
    ("Daniel",                 "en-GB", "🇬🇧"),
    ("Moira",                  "en-IE", "🇮🇪"),
    ("Karen",                  "en-AU", "🇦🇺"),
    ("Tessa",                  "en-ZA", "🇿🇦"),
    ("Rishi",                  "en-IN", "🇮🇳"),
    ("Paulina",                "es-MX", "🇲🇽"),
    ("Mónica",                 "es-ES", "🇪🇸"),
    ("Flo (English (US))",     "en-US", "🇺🇸"),
    ("Sandy (English (US))",   "en-US", "🇺🇸"),
    ("Shelley (English (US))", "en-US", "🇺🇸"),
    ("Reed (English (US))",    "en-US", "🇺🇸"),
    ("Eddy (English (US))",    "en-US", "🇺🇸"),
]

func inferLocaleFromVoice(_ voice: String) -> String {
    return allVoices.first(where: { $0.name == voice })?.lang ?? "en-US"
}

class LangPickerVC: NSViewController {
    let agentName: String
    weak var widget: WidgetWindow?
    weak var popover: NSPopover?

    init(agentName: String, widget: WidgetWindow, popover: NSPopover) {
        self.agentName  = agentName
        self.widget  = widget
        self.popover = popover
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError() }

    override func loadView() {
        let W: CGFloat = 160, rowH: CGFloat = 30, pad: CGFloat = 8
        let H = CGFloat(supportedLocales.count) * rowH + pad * 2
        let v = NSView(frame: NSRect(x: 0, y: 0, width: W, height: H))

        let current = Prefs.voiceLocale(for: agentName)
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
        Prefs.markVoiceLocaleManual(for: agentName)
        Prefs.save(voiceLocale: lang.id, for: agentName)
        widget?.voice.setLocale(lang.id)
        popover?.close()
    }
}

// MARK: - Voice picker popover

class VoicePickerVC: NSViewController {
    let agentName: String
    weak var widget: WidgetWindow?
    weak var popover: NSPopover?
    let onVoiceChanged: () -> Void

    init(agentName: String, widget: WidgetWindow, popover: NSPopover, onVoiceChanged: @escaping () -> Void) {
        self.agentName = agentName
        self.widget = widget
        self.popover = popover
        self.onVoiceChanged = onVoiceChanged
        super.init(nibName: nil, bundle: nil)
    }
    required init?(coder: NSCoder) { fatalError() }

    override func loadView() {
        let W: CGFloat = 252, rowH: CGFloat = 26, pad: CGFloat = 8
        let H = CGFloat(allVoices.count) * rowH + pad * 2
        let v = NSView(frame: NSRect(x: 0, y: 0, width: W, height: H))

        let current = widget?.agentVoice ?? ""
        for (i, voice) in allVoices.enumerated() {
            let y = H - pad - CGFloat(i + 1) * rowH
            let isSelected = voice.name == current
            let btn = NSButton(frame: NSRect(x: pad, y: y, width: W - pad * 2, height: rowH - 2))
            btn.title = "\(voice.flag)  \(voice.name)  ·  \(voice.lang)"
            btn.tag = i
            btn.alignment = .left
            btn.bezelStyle = .rounded
            btn.isBordered = isSelected
            btn.font = isSelected
                ? NSFont.boldSystemFont(ofSize: 11)
                : NSFont.systemFont(ofSize: 11)
            btn.target = self
            btn.action = #selector(selectVoice(_:))
            v.addSubview(btn)
        }
        self.view = v
    }

    @objc func selectVoice(_ sender: NSButton) {
        let voice = allVoices[sender.tag]
        widget?.changeVoice(to: voice.name)
        popover?.close()
        onVoiceChanged()
    }
}

// MARK: - Non-focusable button base (prevents tab-focus highlight in the widget)

class WidgetButton: NSButton {
    override var acceptsFirstResponder: Bool { false }
}

// MARK: - Mic button (short press = toggle, long press = language picker)

class MicButton: NSButton {
    override var acceptsFirstResponder: Bool { false }
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
    var onPermissionDenied: (() -> Void)?

    init(locale: String = "es-MX") {
        recognizer = SFSpeechRecognizer(locale: Locale(identifier: locale))
        registerEngineObserver()
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(systemWillSleep),
            name: NSWorkspace.willSleepNotification,
            object: nil
        )
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(systemDidWake),
            name: NSWorkspace.didWakeNotification,
            object: nil
        )
    }

    private func registerEngineObserver() {
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(engineConfigChanged),
            name: .AVAudioEngineConfigurationChange,
            object: engine
        )
    }

    @objc private func systemWillSleep(_ notification: Notification) {
        if isRecording {
            DispatchQueue.main.async { [weak self] in self?.stopRecording() }
        }
    }

    @objc private func systemDidWake(_ notification: Notification) {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            NotificationCenter.default.removeObserver(self, name: .AVAudioEngineConfigurationChange, object: self.engine)
            self.engine = AVAudioEngine()
            self.registerEngineObserver()
        }
    }

    // Fired when another app interrupts the audio hardware (video, music, etc.)
    @objc private func engineConfigChanged(_ notification: Notification) {
        guard isRecording else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.teardownEngine()
            NotificationCenter.default.removeObserver(self, name: .AVAudioEngineConfigurationChange, object: self.engine)
            self.engine = AVAudioEngine()
            self.registerEngineObserver()
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
            guard let self = self else { return }
            guard status == .authorized else {
                DispatchQueue.main.async { self.onPermissionDenied?() }
                return
            }
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

// MARK: - Phosphor icon images (128×128 PNG, RGBA, black on transparent — template)
private let phInfoPNG = "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"
private let phBroomPNG = "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"
private let phSpeakerHighPNG = "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"
private let phSpeakerSlashPNG = "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"
private let phMicPNG = "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"
private let phGearPNG = "iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAAAAAXNSR0IArs4c6QAAAERlWElmTU0AKgAAAAgAAYdpAAQAAAABAAAAGgAAAAAAA6ABAAMAAAABAAEAAKACAAQAAAABAAAAgKADAAQAAAABAAAAgAAAAABIjgR3AAASX0lEQVR4Ae2ce8wfVZnHuZVSChYQKLfyFrnIpaBATFdt6f6hC4KAqyTIwopkC3+Yze5iFAzlD1cXNnJZTDTZRBtx62KiSHQ3FHDNmreFRcwCclEoUm25lVvRcpWbuJ/P9h07jHPO3Of9/XS+yfedmXOe8zzPeWbmnOec+bVbbTVgiMAQgSECQwSGCAwRGCIwRGCIwBCBIQJDBIYIDBEYIjBEYIjAEIEhAkME/sgjsO0fSf+2ph8Hwr3hC/B12AV2QKl2doLPdmFg0Fk+ArMQXQT/Ed4Kn4S/hj+BZ8G2cSYK74Ab4Qa4Cl4EF8Lt4YCeIvBO7HwO3g1903+Xw99SdiXcETaFOq6A6syz9Qrlt8NlcAEc0EEEZqPzI3AldIjPuxF5ZcrvD+tiHg3Vkac7r2wTst+FJ0OniwENIzCH9ufBO2FewMuU3U/b42BVLKbBfbCMjTyZ22h7NtwJDqgYAd+ec+A9MC+4VctM2JbCslDWNlXt5MmbN5g/DHkCQSgDk6pJmBfMJmXO4VdBp5MQrFMmNN83sf8D9B4dMjyUb47AURweh00CXdT2RvRPbDb3pr+WWVfUvkn9I+g/7E1Wh4s3ReAarpoEuGzbNdhZkrLsuWVl2zeR+1rK7rSfuoEyKnDeN+k6oKJDdyF/A3RJeAEsm327mvgFFMnmzuar+N+XqL4MzoQnwnfAKliL8OHwtSqN/hRk59HJp2CZt+tXyK2AfwHTWfapXD8Gy+ioI/Mwuk+CCXbm5AToyPVrWEbnE8jtAwdkInAM10VrfG/upfCQTNv05ZFc/AiWuRlVZFajMzZ/H0r9F2BRDvM8Mm5mDchEwLf5DRi6Ke4FzIdlsCtC/wZDuqqWfxVdc8oYRsbpJLZ8dYVhXwdkIuBaOXZjHGarYFuEL4S/gTG9sTpHpPPhNrAKvo1wTG8X3yqq+Pd72aod+33DDk6K5kXzgyrwTXNIPh06dVSF8/1p8CroyFQFRb7uV0VZl7Kj9AAUBaXOTTR2/wk/AM0LymI1gsfDm8o2yMg9mrnOXprwjgRG6QHYtyAiRUGNNb+XSrP3L8GNEUHf3H+BH4TuC9RFka8j8wBsV7eHHbSLjQDOp3VHgMRVl2l/By+He0F1vgxFsnfgEq3o5v1/g4I/RTr2p717MPowgAh4A34JQ4mT39zNrscFB+HoqzDUH/OLsquKTvs8KlPAHvTSDzEh+PY+F6ocwXJ91ecQ7Oueoco+y0flAdiFTscegCepdzk3LtDX2ErA3cvdRqEzo/IA+GufHSMBeZq6cXoA/F4QewC2p/7Dkf72VjVdSaA322HfYdCM+2JoUhSCD4Dr+nGBvupzDJ+m8nV4HVTW1UnvD3kXD4BP91uhNze5yf5c28zXTN8lUDLnOxTOgkVwf33csKHAYR94f1X89/DFKfogPAJd8biSsN+WJZyWhwT7pXAYUsvhg1DHn4fuoIUy4SrlThHjBn2u0seYrFvS5kHr4L/Dd8CRgj918smNdaJu3ffRG8sPRioQKWf0Wd/r9jvWzv2Kd6dsTevpTKz/EMYcrls3id6ibwSIjCz0fRLW7X+s3a3oHYkX44yOOug+vLnCuMM+2JfYzaxbt3S6gzMbB/zZc90OhNpNonN32CX8XGwSLD3vEvZlEob6W7f8PnTOgbURW3qVUXo2Ql8vI1hBxnnzHNhm5j8XfcfCBdBkdQL6ZiZDqOt2M+310KD+FPoDlKdgW9gbRVfD49tSOKXnExz/ta7OJg+Ay7dV8F0Vjfu0u/71n1GZ2Rpk6Q2/Ba6Er8Cm8FdBBvs0uBi6LK0CfVsNXaf7UOpvU8xEwUnwvdAPUvqU0J3BGbDqPbmXNu+BL8DKqGosbeBkLv4DxnT4JvlG+XYla9tknet++UtTbHOTx4CeA50fD4Jt4OcocYn7dWhf2oI7sTtO0T0Rk0Y/i7tf4tG+HAGLfkP4UWS+BXuFN9+3OUTfoLZuQJmOGcyz4BoY8qlpuQ/zGTD20FPdKuajzdEx5vt/Ud91HoOJLfCp9A2OOXXZFvHOz9xdvLbAn5ivVet823xL+8KlGIr5+CL1x/TljHaWwZhDzpdvV7AHHIeNLt/6UD8dDZzL+8DBGPHzcsgXy31IeoE/3iha+l3TiydbbfUh7DwDY4Hpss58wFyoD6zASKwv5luz+3BkIUb8ahVyxoTO7LtrePPNfEN+FJW/StuXp+h5kXyo3qmwj4fgfdgxtiE/7MMS2DmKhv978KDrJ3ExNqq++Q6h18OL4SnwKDgxRc8ts06ZouE2exP8Stf1dGBM74JZ2+nrzqcBM81VBU5cQn2XMPl6EKY7Hjtfi+xF8ABYFsraxrYx3em6B5DdB3aJz6M8bTN7/mPqZ3TpgN/0i5Ykn+3Qge3Q/R2Y7XjetdPU5XAurAvbqiM25aVtfxvZLpdjRQ+AI5EJY2cwsy8ael2SnNiRB2eiNx3w0Pl65D7Qog/qUmfIXrrcTZkucCpKX4JpW9lz85EFXRhPdLprdSfMGs5eP4zMoUmjlo57oKfM0H8/cl0EQZ3qzvY1e+1U8FbYJrT9GMzayl67Lbxzm4bzdP0Vha/DrPHs9S3I7JKnoGbZhSVsPoTMETX1l2mmbm1k+5q9/lQZZSVldkPOuT1rI3vtCuFjJXU2FruihEM6uBy2MSf6IBUlZA6PJ8CuoY2iodiRak4LjpjQfQNmb3be9RdbsFdaxSwkbyjp2PmltYYFnVfzOp0u86HsC2VegNNbcOYz6Ej3MXR+E3KzW7BXScU8pNfAkFNJuUlh0zfzugI766g3R+gL2tJm0se847UNnXFf4uUCG9r9OZyA04JFWC2zaeK8eUhND+fS7kmYF+SkbFlN3U2aaTOxn3d8gvo9axow1yiT9G1Czm8h04q/wXqZpPBm5OrMiy7BYlugBmE+7BvzMajtvJtvmTGpsyVu0ndbRG9iz5icC0cCV+FF4ljseGUNby8o0L2S+q1r6G3aRJvajvW36mpAnV8u0JnY6zXpw6coTEBMRBLnQseNyOwX1fSHlVcX6L34D5v0VqLtUF8t1/cqMK8qM6X6E7VWkj5/RdMGXkTJedDlTwxukOwdE8jU+UZMZMrSlwbZj0/TBW3rQwgx3/Pa7EXhLnkVqTJj7NBvzBujrQdAR9z9Wwqf9SKCWMCyzfRvj2xh6tp5dn3quu9TbetDCPpeZR/ktZCiqXJja4yNdSto8wHQodVwXYFnLm3KQv/cfg7BROi5UGUP5drWhxD0vUqMX0E+9oIYW2PcGqo4V9bodCRkZX0b5DIRaPsBcE06P2Mje7lDtiBy/QZ1bruG4PD6llBlD+Xajg3xztP2oSxmIhh7gQ6gvtV1f5sPwP44txwWrfWr2DR4T8MQ/H3A/FBlD+Xa1ocQXPXEpohsu6LYGFtjbKxbQZHBskZcknwFHlzQwCXO4wUy6Wrnw4fSBZlz35ajMmV9XmpbH0KI+Z7Xxh1PH5oYjLGxHqll4CU4VGbX6xrkHoVV4Df4GN5NZewmxNo2qdOmtmO4L1aZU/cYZStyyrNFxvqfsoXTdb0Uww5zvq0xur25G6yKcd0KNiYnVO0s8g7zbpvHYmmdy09jP61YhHWH9SJnfbKPqOnpuH4McjjX9zrww5nTR1Fcjb33YFowD6sPwCInXfef3NDDcfwcrM9N4OjhKqIovmuQ8V70Cjc4boBFzll/YQuefbSELX+k0Re0VdR3fW6Kf0BBkR3rvRezmhqr0t6vemUcM6GZUUVxQNb98bUwZtP9gjpzbsBksFgb2or5oq9Fe/pBA6kK9xi+CmO2krreXoCzcOj1Ek7dhkydpI9muXAkSTobOjpv1s01co1mCtVdZm5uY9RLTJsUroahPifl3hN/sNspdkL73TAxGjq61FvQsid+WPFLWMhmUn5/B7btiv1Rd2IndNRHfW0TZZPCOzEa+3bS2KfD0bAJhjpvucPjKbALnInSmO2kbj1yLh/bgrrWw0R/7KiPXcCp53kYs/0M9W/vwnii80BOnoIxJz6XCHdw3A6d3ymwn/j2G+Quh3NhXdhWHepK9MaO+qaPXeFiFMfsP059a9vEeZ2wc7cWOPH5vIYtlu2HrjJTQRKotchfBA+o4IOytrFtoqfoqE/7wi7hyxXzYxX1Jo6dosiJu7A+u1MPNv+vXw53sWBk69w08Z9++xY5RbmPPzFFzy2zTpkym1tp/fqyGHYJY/oTmLabPV/WpQOJ7kWcJD9cyDrgtVug70+EOzx+CN0vwDwfypS9Sls3qaTnZdrkyeiDvnSN92HA2Ob5YJnT1ELYOcwy74EhRyz/RudebDZg4KuOBDG/q9Zpu4+bb29XwJh/t1O/g4J9wHk+5oxD6MF9OIKN4+AaGPOnizptarsPHISRommpl+E/6ew7OSkafv85Ee7h6F74tbCLG52nU1va7AuXYijPj6TM3yYe0Zcz2tkG3ggTB/KOLknmw76gT2fBLkcDdWtDW33hbRgylnkxTsq+V9eZres2pN1HoOveGO6i8mfwaegn4UenuIGjI4ibRvIN2Bb2RNE5cCl06GwDa1GyHF4N3QdpCy7ZzKnkW+A+0JFlP+iS0r4cBo+EIfgQuIK5PiQQK2/yAMxG8S3Q6aAKdPg1+CtoMBM+wfn/wJXQVUZT7IqC4+FpcDE0mFWgXzdDH/LvQ+fgppiJgpPgIrgXnAv1S+rvdrDqPflf2iyBrgIqo6qxrIFzKfhKtrDhtcH2DXbYawsG+li4APpGTUD3633zxEvQUeoheD/8KbwDPgnbwt4ouhr6ULaJs1G2ok2FVXTtjPC98HctcxJ9u8Mu4fDrGyc97xL2ZRK2HScfUkfiacXHsd52x9R3E2z7qxoqe4d9sC9dxOiM3nuTY3AWZeYCXXRwEr0mRuMKfZ+EXcTmh+g1pxgJLMQL5+wuOmpOkMzVI9HZkk7os753EZNH0Ht0ST96EzsKSyYj66DJ0wuwrc675Bw3fBiH2+r/8+hylfQgdDlqItsKTIDagt8HPgadEkx6nPsSmgG7tk1ouclLQk6jeC+110UlRq9Sn8vgVYR8WV6ELo19ux+eonsnrk58oVyWboTKt4Y2H4DEKdejdkKGkH5I/hKhZTC2JB3HPMCHPgZHh8vg9TC5wW7pWv4nh0vocWy4/G/qtx2jqOjrDyJ9cufT/f0BUxF4F8eXYeghcK/BPYdxwU44ejcM9cch/8hR6Mw2o+AEPjj3GZQQ3Mlz2hgX6Gts69n5ftModGZUHgATHIMSwi5UzAlVjmC5o5V7+yHYV5O7aUcXSWCdTrnMeQbuH2g8g3JXEA8G6qsUqydJKk1Yhb+kMQl1LyOWvFJdCurfPiLpA++UNyAVge9xHpozLf/rlGydU9/KK6HBD9nxrfwSjL29VBfidCRCNiz3C+NIYFSmAINR9Ob55tbFoTR0ufVJuEdEye7U/S28AR4ZkSuqKvLV9f1IYJwegH1rRuwE2rkle1yF9n+GrB9wTqnQJi1a5OujaeHpPB+lB6DorYhl1XkxtG/nQ4fbUG6R1y4pcx7/FvwMrLoHUeTrhsTIcNwSgfdz+lsYmjvdaj5wi3j0zBXDchjSVbV8Bbp2i1rcUjmf0ztgyIabQG3/KASV4w9/WuZqIBQ4y83SvwCd00M4jIrVMKanTt2P0BnLCw6h3t09R7KYfvc7joEDMhFwyH0CxoKX1Pn7vGug8/vOMMFJnDwME7m2j97cUxNjHN3xc+RyhHgGlrHnKmQeHAnEPsD07eAMDN4HD6po2C1Xs/ZX4AVwR1gGvom/mBJ0avFmloHr98vhNvBEeDSsgnUIHw7VMyATga9xXeYtaiqzBjtLUrY9t6yp3jLtv5myO5xmIuD87X5AmUDWlbkR/RMZu15adhOsq7dMO6c4c50BkQg4pMY+pZYJdJ6MK4yr4OyIbeu+CM3U83Q0KbsZne+BA0pEYHtkzoSx5VSVm/EsupaWsJuInMfJc7CKjZDsz9BzLiybmyA6IImAidnZ8McwFOCichPLxbAq/pwGD8Ai/aF6k9NPwF3hgIYR2IH2J8Pvwk0wFPRs+Upkmyy5JmhvzpDVG7r2M6/bzn4MSi9PuRzQVgQWoGgZvB269Mu7Gc73V8A2ht2ivEBb/mLJTaBj4YCeImCesBBeBFfBDXAjNG8wf2gbH0eh29HmE09Dp6VL4BIYSyypHl2M0kZQ0yhNoMCp4iHY1SaLN/ptU/p/ydG3f8AQgSECQwSGCAwRGCIwRGCIwBCBIQJDBIYIDBEYIjBEYIjAEIEhAkMEhggMERjlCPwf9U/syvJ47EcAAAAASUVORK5CYII="

private func phImage(_ base64: String) -> NSImage {
    guard let data = Data(base64Encoded: base64) else { return NSImage() }
    let img = NSImage(data: data) ?? NSImage()
    img.isTemplate = true
    return img
}

// MARK: - Widget window



class WidgetWindow: NSObject, NSWindowDelegate {
    let agentName: String
    let agentPath: String
    var agentVoice: String
    let window: NSWindow
    var onClose: (() -> Void)?
    var configPopover: NSPopover?
    var langPopover:   NSPopover?
    var nameLbl: OutlinedLabel!
    var dotsBtn: WidgetButton!
    var micBtn: MicButton!
    var speakerBtn: WidgetButton!
    var clearBtn: WidgetButton!
    var infoBtn: WidgetButton!
    var voice: VoiceInputManager!
    var idleFill: NSColor = NSColor.black.withAlphaComponent(0.85)
    var isMuted: Bool = false

    var isInfoExpanded = false
    var infoPanelView: NSView?
    var infoKeyLabels: [NSTextField] = []
    var infoValLabels: [NSTextField] = []

    var isOccluded  = false
    var shrinkTimer: Timer?
    var savedFrame:  NSRect?

    static let infoH: CGFloat = 130

    init(agentName: String, index: Int, path: String, voice agentVoiceArg: String = "") {
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
        self.agentName     = agentName
        self.agentPath  = path
        self.agentVoice = agentVoiceArg
        super.init()

        window.title = agentName
        window.collectionBehavior    = [.managed, .participatesInCycle]
        window.isOpaque              = false
        window.titlebarAppearsTransparent = true
        window.titleVisibility       = .hidden
        window.isReleasedWhenClosed  = false
        window.delegate              = self

        let content = window.contentView!

        // Agent name label
        let labelWidth = W - 28
        let (fontSize, displayText) = fitFontSizeAndSplit(text: agentName, maxWidth: labelWidth)
        nameLbl = OutlinedLabel(frame: NSRect(x: 18, y: H * 0.28, width: labelWidth, height: H * 0.60))
        nameLbl.text       = displayText
        nameLbl.textFont   = NSFont.systemFont(ofSize: fontSize, weight: .heavy)
        content.addSubview(nameLbl)

        // All bottom buttons: 32×32, y=12, right margin=10, gap=8
        // Right to left: dots(258), mic(218), speaker(178) | left: info(10)

        // Settings button (bottom-right)
        dotsBtn = WidgetButton(frame: NSRect(x: W - 50, y: 16, width: 32, height: 32))
        dotsBtn.imageScaling = .scaleProportionallyUpOrDown
        dotsBtn.bezelStyle   = .inline
        dotsBtn.isBordered   = false
        dotsBtn.focusRingType = .none
        dotsBtn.target       = self
        dotsBtn.action       = #selector(showConfig(_:))
        content.addSubview(dotsBtn)

        // Mic button
        micBtn = MicButton(frame: NSRect(x: W - 90, y: 16, width: 32, height: 32))
        micBtn.bezelStyle    = .inline
        micBtn.isBordered    = false
        micBtn.focusRingType = .none
        micBtn.onShortPress  = { [weak self] in self?.voice.toggle() }
        micBtn.onLongPress   = { [weak self] in self?.showLangPicker() }
        content.addSubview(micBtn)

        // Speaker/mute button
        speakerBtn = WidgetButton(frame: NSRect(x: W - 130, y: 16, width: 32, height: 32))
        speakerBtn.imageScaling  = .scaleProportionallyUpOrDown
        speakerBtn.bezelStyle    = .inline
        speakerBtn.isBordered    = false
        speakerBtn.focusRingType = .none
        speakerBtn.target        = self
        speakerBtn.action        = #selector(toggleMute(_:))
        content.addSubview(speakerBtn)

        // Clear button — bottom-left, next to info
        clearBtn = WidgetButton(frame: NSRect(x: 58, y: 16, width: 32, height: 32))
        clearBtn.imageScaling  = .scaleProportionallyUpOrDown
        clearBtn.bezelStyle    = .inline
        clearBtn.isBordered    = false
        clearBtn.focusRingType = .none
        clearBtn.target        = self
        clearBtn.action        = #selector(clearSession(_:))
        content.addSubview(clearBtn)

        // Info button — bottom-left
        infoBtn = WidgetButton(frame: NSRect(x: 18, y: 16, width: 32, height: 32))
        infoBtn.imageScaling  = .scaleProportionallyUpOrDown
        infoBtn.bezelStyle    = .inline
        infoBtn.isBordered    = false
        infoBtn.focusRingType = .none
        infoBtn.target        = self
        infoBtn.action        = #selector(toggleInfo(_:))
        content.addSubview(infoBtn)

        // Sync STT locale to match TTS voice unless user explicitly set it via the language picker
        if !Prefs.voiceLocaleIsManual(for: agentName) && !agentVoice.isEmpty {
            Prefs.save(voiceLocale: inferLocaleFromVoice(agentVoice), for: agentName)
        }
        isMuted = Prefs.muted(for: agentName)
        voice = VoiceInputManager(locale: Prefs.voiceLocale(for: agentName))
        voice.onStateChange = { [weak self] active in
            self?.updateMicIcon(color: active ? .systemRed : (self?.idleFill ?? .black))
        }
        voice.onResult = { [weak self] text in
            self?.injectToSession(text)
        }
        voice.onPermissionDenied = { [weak self] in
            guard let self = self else { return }
            self.updateMicIcon(color: .systemOrange)
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
                self?.updateMicIcon(color: self?.idleFill ?? .black)
            }
        }

        applyPrefs()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        DistributedNotificationCenter.default().addObserver(
            forName: Notification.Name("com.localagentsociety.focus.\(agentName)"),
            object: nil, queue: .main
        ) { [weak self] _ in
            self?.window.orderFrontRegardless()
        }

        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(activeSpaceChanged),
            name: NSWorkspace.activeSpaceDidChangeNotification,
            object: nil
        )
    }

    func applyPrefs() {
        let opacity = Prefs.opacity(for: agentName)
        let bgColor = Prefs.color(for: agentName)
        window.backgroundColor = bgColor.withAlphaComponent(opacity)
        window.level = Prefs.ontop(for: agentName) ? .floating : .normal

        // Shared dark fill: 85% black + 15% background tint, darker than before
        let darkFill = (NSColor.black.blended(withFraction: 0.15, of: bgColor) ?? .black)
            .withAlphaComponent(min(opacity * 1.6, 0.98))
        idleFill = darkFill

        nameLbl?.fillColor     = darkFill
        nameLbl?.strokeOpacity = opacity
        nameLbl?.needsDisplay  = true

        dotsBtn?.alphaValue    = opacity
        micBtn?.alphaValue     = opacity
        speakerBtn?.alphaValue = opacity
        clearBtn?.alphaValue   = opacity
        infoBtn?.alphaValue    = opacity
        let strokeA = min(opacity * 1.1 + 0.1, 1.0)
        let iconColor = NSColor.white.withAlphaComponent(strokeA)
        dotsBtn?.image = phImage(phGearPNG)
        dotsBtn?.imageScaling = .scaleProportionallyUpOrDown
        dotsBtn?.contentTintColor = iconColor
        clearBtn?.image = phImage(phBroomPNG)
        clearBtn?.imageScaling = .scaleProportionallyUpOrDown
        clearBtn?.contentTintColor = iconColor
        micBtn?.image = phImage(phMicPNG)
        micBtn?.imageScaling = .scaleProportionallyUpOrDown
        updateMicIcon(color: idleFill)
        infoBtn?.image = phImage(phInfoPNG)
        infoBtn?.imageScaling = .scaleProportionallyUpOrDown
        updateSpeakerIcon()
        updateInfoIcon()

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
        let configVC = ConfigVC(agentName: agentName, widget: self)
        p.contentViewController = configVC
        p.delegate = configVC
        p.behavior = .transient
        p.show(relativeTo: sender.bounds, of: sender, preferredEdge: .maxY)
        configPopover = p
    }

    func updateMicIcon(color: NSColor) {
        micBtn.contentTintColor = color
    }

    // MARK: Speaker / mute

    @objc func toggleMute(_ sender: NSButton) {
        isMuted.toggle()
        Prefs.save(muted: isMuted, for: agentName)
        updateSpeakerIcon()
        setBackendMute(isMuted)
    }

    @objc func clearSession(_ sender: NSButton) {
        injectToSession("/clear", source: "raw")
    }

    func updateSpeakerIcon() {
        let opacity = Prefs.opacity(for: agentName)
        let strokeA = min(opacity * 1.1 + 0.1, 1.0)
        if isMuted {
            speakerBtn.image = phImage(phSpeakerSlashPNG)
            speakerBtn.imageScaling = .scaleProportionallyUpOrDown
            speakerBtn.contentTintColor = NSColor.systemRed.withAlphaComponent(min(strokeA + 0.15, 1.0))
        } else {
            speakerBtn.image = phImage(phSpeakerHighPNG)
            speakerBtn.imageScaling = .scaleProportionallyUpOrDown
            speakerBtn.contentTintColor = NSColor.white.withAlphaComponent(strokeA)
        }
    }

    func updateInfoIcon() {
        let opacity = Prefs.opacity(for: agentName)
        let strokeA = min(opacity * 1.1 + 0.1, 1.0)
        infoBtn?.contentTintColor = isInfoExpanded
            ? NSColor.white.withAlphaComponent(min(strokeA + 0.15, 1.0))
            : NSColor.white.withAlphaComponent(strokeA)
    }

    private func setBackendMute(_ muted: Bool) {
        let method = muted ? "POST" : "DELETE"
        guard let url = URL(string: "http://localhost:8700/agents/\(agentName)/mute") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.timeoutInterval = 3
        URLSession.shared.dataTask(with: req).resume()
    }

    func changeVoice(to newVoice: String) {
        agentVoice = newVoice

        // Re-sync STT locale to match new TTS voice (only if not manually overridden)
        if !Prefs.voiceLocaleIsManual(for: agentName) {
            let locale = inferLocaleFromVoice(newVoice)
            Prefs.save(voiceLocale: locale, for: agentName)
            voice.setLocale(locale)
        }

        // Update .agent.json
        if !agentPath.isEmpty {
            let jsonURL = URL(fileURLWithPath: agentPath + "/.agent.json")
            if let data = try? Data(contentsOf: jsonURL),
               var json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                json["voice"] = newVoice
                if let updated = try? JSONSerialization.data(withJSONObject: json, options: .prettyPrinted) {
                    try? updated.write(to: jsonURL)
                }
            }
        }

        // Update backend registry
        guard let url = URL(string: "http://localhost:8700/agents") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: [
            "name": agentName,
            "voice": newVoice,
            "path": agentPath,
            "backend_url": "http://localhost:8700",
            "frontend_url": "http://localhost:8700/widget/\(agentName)",
        ])
        req.timeoutInterval = 3
        URLSession.shared.dataTask(with: req).resume()
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
            updateInfoIcon()
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
            updateInfoIcon()
        }
    }

    private func infoPanelColors() -> (bg: NSColor, text: NSColor) {
        let bgColor = Prefs.color(for: agentName)
        let panelBg  = bgColor.blended(withFraction: 0.22, of: NSColor.black) ?? bgColor
        let textColor = panelBg.blended(withFraction: 0.32, of: NSColor.white) ?? NSColor.white
        return (panelBg, textColor)
    }

    private func currentGitBranch(for path: String) -> String {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/git")
        proc.arguments = ["-C", path, "branch", "--show-current"]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError  = Pipe()
        do {
            try proc.run()
            proc.waitUntilExit()
            let data   = pipe.fileHandleForReading.readDataToEndOfFile()
            let branch = String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return branch.isEmpty ? "—" : branch
        } catch {
            return "—"
        }
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

        let folderName = agentPath.isEmpty ? "—" : URL(fileURLWithPath: agentPath).lastPathComponent
        let branch     = agentPath.isEmpty ? "—" : currentGitBranch(for: agentPath)

        let rows: [(key: String, value: String)] = [
            ("Voice",  agentVoice.isEmpty ? "—" : agentVoice),
            ("Speech", localeName(for: Prefs.voiceLocale(for: agentName))),
            ("Ports",  ports.isEmpty ? "None" : ports.map { String($0) }.joined(separator: " · ")),
            ("Folder", folderName),
            ("Branch", branch),
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
                guard let n = val["local_agent"] as? String, n == self.agentName,
                      let p = val["port"] as? Int else { return nil }
                return p
            }.sorted()
            completion(ports)
        }.resume()
    }

    func showLangPicker() {
        if let p = langPopover, p.isShown { p.close(); return }
        let p = NSPopover()
        p.contentViewController = LangPickerVC(agentName: agentName, widget: self, popover: p)
        p.behavior = .transient
        p.show(relativeTo: micBtn.bounds, of: micBtn, preferredEdge: .maxY)
        langPopover = p
        // Blue tint while picker is open
        updateMicIcon(color: .systemBlue)
        p.contentViewController?.view.window?.windowController?.window?.makeKeyAndOrderFront(nil)
    }

    private func injectToSession(_ text: String, source: String = "voice") {
        NSLog("[inject] → name=%@ len=%d text=%@", agentName, text.count, text)
        guard let url = URL(string: "http://localhost:8700/agents/\(agentName)/inject") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: [
            "message": text,
            "source":  source,
        ])
        req.timeoutInterval = 5

        URLSession.shared.dataTask(with: req) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self = self else { return }
                let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                guard status == 200, let data = data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                else {
                    NSLog("[inject] ✗ name=%@ HTTP status=%d error=%@", self.agentName, status, error?.localizedDescription ?? "nil")
                    self.updateMicIcon(color: .systemOrange)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak self] in
                        self?.updateMicIcon(color: self?.idleFill ?? .black)
                    }
                    return
                }
                let injected = json["injected"] as? Bool ?? false
                let tty = json["tty"] as? String ?? "?"
                NSLog("[inject] ✓ name=%@ injected=%@ tty=%@", self.agentName, injected ? "true" : "false", tty)
                // green = live injection into terminal; yellow = inbox only (agent not at prompt)
                self.updateMicIcon(color: injected ? .systemGreen : .systemYellow)
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak self] in
                    self?.updateMicIcon(color: self?.idleFill ?? .black)
                }
            }
        }.resume()
    }

    // MARK: Space-change expand/shrink

    @objc func activeSpaceChanged() {
        guard Prefs.expandOnSpaceChange(for: agentName) else { return }
        let onCurrentSpace = window.isOnActiveSpace
        if onCurrentSpace && isOccluded {
            isOccluded = false
            shrinkTimer?.invalidate()
            setOccludedExpanded(false)
        } else if !onCurrentSpace && !isOccluded {
            isOccluded = true
            setOccludedExpanded(true)
        }
    }

    private func collapseInfoPanelIfNeeded() {
        guard isInfoExpanded else { return }
        let content = window.contentView!
        let addH = WidgetWindow.infoH
        infoPanelView?.removeFromSuperview()
        infoPanelView = nil
        infoKeyLabels = []
        infoValLabels = []
        for sub in content.subviews { sub.frame = sub.frame.offsetBy(dx: 0, dy: -addH) }
        let curFrame = window.frame
        window.setFrame(NSRect(x: curFrame.minX, y: curFrame.minY + addH,
                               width: curFrame.width, height: curFrame.height - addH), display: true)
        isInfoExpanded = false
        updateInfoIcon()
    }

    func setOccludedExpanded(_ expanded: Bool) {
        if expanded {
            collapseInfoPanelIfNeeded()
            savedFrame = window.frame

            let screen = NSScreen.main?.frame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
            window.setFrame(screen, display: true, animate: false)
            window.backgroundColor = Prefs.color(for: agentName).withAlphaComponent(Prefs.opacity(for: agentName))
            window.level = .floating

            dotsBtn.isHidden     = true
            micBtn.isHidden      = true
            speakerBtn.isHidden  = true
            clearBtn.isHidden    = true
            infoBtn.isHidden     = true

            let W = screen.width, H = screen.height
            let labelH = H * 0.30
            let labelW = W - 80
            nameLbl.frame = NSRect(x: 40, y: H * 0.58, width: labelW, height: labelH)
            let (fontSize, displayText) = fitFontSizeAndSplit(text: agentName, maxWidth: labelW, start: 300)
            nameLbl.text     = displayText
            nameLbl.textFont = NSFont.systemFont(ofSize: fontSize, weight: .heavy)
            nameLbl.needsDisplay = true
        } else {
            dotsBtn.isHidden    = false
            micBtn.isHidden     = false
            speakerBtn.isHidden = false
            clearBtn.isHidden   = false
            infoBtn.isHidden    = false

            let W: CGFloat = 300, H: CGFloat = 160
            let target: NSRect
            if let saved = savedFrame {
                target    = saved
                savedFrame = nil
            } else {
                let f = window.frame
                target = NSRect(x: f.origin.x, y: f.origin.y + f.height - H, width: W, height: H)
            }
            window.setFrame(target, display: true, animate: false)
            window.backgroundColor = Prefs.color(for: agentName).withAlphaComponent(Prefs.opacity(for: agentName))
            window.level = Prefs.ontop(for: agentName) ? .floating : .normal

            let labelWidth = W - 28
            nameLbl.frame = NSRect(x: 18, y: H * 0.28, width: labelWidth, height: H * 0.60)
            let (fontSize, displayText) = fitFontSizeAndSplit(text: agentName, maxWidth: labelWidth, start: 62)
            nameLbl.text     = displayText
            nameLbl.textFont = NSFont.systemFont(ofSize: fontSize, weight: .heavy)
            nameLbl.needsDisplay = true

            dotsBtn.frame    = NSRect(x: W - 50,  y: 16, width: 32, height: 32)
            micBtn.frame     = NSRect(x: W - 90,  y: 16, width: 32, height: 32)
            speakerBtn.frame = NSRect(x: W - 130, y: 16, width: 32, height: 32)
            clearBtn.frame   = NSRect(x: 58,       y: 16, width: 32, height: 32)
        }
    }

    func windowWillClose(_: Notification) {
        shrinkTimer?.invalidate()
        onClose?()
    }
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
        for (idx, name) in agents.keys.sorted().enumerated() {
            guard let info = agents[name] else { continue }
            let path  = info["path"]  as? String ?? ""
            let voice = info["voice"] as? String ?? ""
            spawnWidget(agentName: name, index: idx, path: path, voice: voice)
        }
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls {
            guard url.scheme == "localagentsociety",
                  let name = url.host, !name.isEmpty else { continue }
            let action = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                .queryItems?.first(where: { $0.name == "action" })?.value
            if action == "reopen" {
                reopenWidget(for: name)
            } else {
                openWidget(for: name)
            }
        }
    }

    func applicationShouldHandleReopen(_ app: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !hasVisibleWindows {
            closedByUser.removeAll()
            guard let agents = fetchAgents() else { return true }
            for (idx, name) in agents.keys.sorted().enumerated() {
                guard let info = agents[name] else { continue }
                let path  = info["path"]  as? String ?? ""
                let voice = info["voice"] as? String ?? ""
                spawnWidget(agentName: name, index: idx, path: path, voice: voice)
            }
        }
        return true
    }

    func applicationDockMenu(_: NSApplication) -> NSMenu? {
        guard let agents = fetchAgents(), !agents.isEmpty else { return nil }
        let menu = NSMenu()
        for name in agents.keys.sorted() {
            let item = NSMenuItem(title: name, action: #selector(focusAgent(_:)), keyEquivalent: "")
            item.image = NSImage(systemSymbolName: "macwindow", accessibilityDescription: nil)
            item.target = self
            item.representedObject = name
            menu.addItem(item)
        }
        return menu
    }

    @objc func focusAgent(_ sender: NSMenuItem) {
        guard let name = sender.representedObject as? String else { return }
        openWidget(for: name)
    }

    func openWidget(for name: String) {
        closedByUser.remove(name)
        if let w = widgets[name] {
            w.window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        guard let agents = fetchAgents(), let info = agents[name] else { return }
        let idx   = agents.keys.sorted().firstIndex(of: name) ?? 0
        let path  = info["path"]  as? String ?? ""
        let voice = info["voice"] as? String ?? ""
        spawnWidget(agentName: name, index: idx, path: path, voice: voice)
    }

    func reopenWidget(for name: String) {
        if let w = widgets[name] {
            w.window.close()
        }
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            self.closedByUser.remove(name)
            guard let agents = self.fetchAgents(), let info = agents[name] else { return }
            let idx   = agents.keys.sorted().firstIndex(of: name) ?? 0
            let path  = info["path"]  as? String ?? ""
            let voice = info["voice"] as? String ?? ""
            self.spawnWidget(agentName: name, index: idx, path: path, voice: voice)
        }
    }

    private func spawnWidget(agentName: String, index: Int, path: String, voice: String = "") {
        guard widgets[agentName] == nil else { return }
        let widget = WidgetWindow(agentName: agentName, index: index, path: path, voice: voice)
        widget.onClose = { [weak self] in
            self?.closedByUser.insert(agentName)
            self?.widgets.removeValue(forKey: agentName)
        }
        widgets[agentName] = widget
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
