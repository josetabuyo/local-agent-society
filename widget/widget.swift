import AppKit

let args = CommandLine.arguments
let family  = args.count > 1 ? args[1] : "Agent"
let members = args.count > 2 ? args[2] : ""

func fitFontSize(text: String, maxWidth: CGFloat, start: CGFloat = 62, min: CGFloat = 11) -> CGFloat {
    var size = start
    while size > min {
        let w = (text as NSString).size(withAttributes: [.font: NSFont.boldSystemFont(ofSize: size)]).width
        if w <= maxWidth { break }
        size -= 1
    }
    return size
}

class Delegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var nameLbl: NSTextField!
    var subLbl: NSTextField?

    let normalW: CGFloat   = 300
    let normalH: CGFloat   = 160
    let expandedW: CGFloat = 560
    let expandedH: CGFloat = 280

    func applicationDidFinishLaunching(_ n: Notification) {
        let W = normalW
        let H = normalH

        let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1440, height: 900)
        let x: CGFloat = screen.minX + 60
        let y: CGFloat = screen.maxY - H - 60

        window = NSWindow(
            contentRect: NSRect(x: x, y: y, width: W, height: H),
            styleMask: [.titled, .closable, .miniaturizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = family
        window.level = .floating
        window.collectionBehavior = [.managed, .participatesInCycle]
        window.isOpaque = false
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.backgroundColor = NSColor(
            calibratedRed: 0.565, green: 0.753, blue: 0.376, alpha: 0.72
        )

        let content = window.contentView!

        let labelWidth = W - 28
        nameLbl = NSTextField(wrappingLabelWithString: family)
        nameLbl.frame = NSRect(x: 18, y: H * 0.28, width: labelWidth, height: H * 0.60)
        nameLbl.font = NSFont.boldSystemFont(ofSize: fitFontSize(text: family, maxWidth: labelWidth))
        nameLbl.textColor = NSColor(calibratedRed: 0.08, green: 0.08, blue: 0.08, alpha: 1.0)
        nameLbl.backgroundColor = .clear
        nameLbl.drawsBackground = false
        nameLbl.lineBreakMode = .byClipping
        content.addSubview(nameLbl)

        if !members.isEmpty {
            let lbl = NSTextField(labelWithString: members)
            lbl.frame = NSRect(x: 20, y: 10, width: W - 28, height: 20)
            lbl.font = NSFont.systemFont(ofSize: 10, weight: .medium)
            lbl.textColor = NSColor(calibratedRed: 0.22, green: 0.40, blue: 0.08, alpha: 1.0)
            lbl.backgroundColor = .clear
            lbl.drawsBackground = false
            content.addSubview(lbl)
            subLbl = lbl
        }

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        // Fires when the widget enters or leaves the visible Space
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(occlusionChanged),
            name: NSNotification.Name("NSWindowDidChangeOcclusionStateNotification"),
            object: window
        )

        DistributedNotificationCenter.default().addObserver(
            forName: Notification.Name("com.localagentsociety.focus.\(family)"),
            object: nil, queue: .main
        ) { [weak self] _ in
            self?.window.orderFrontRegardless()
        }
    }

    @objc func occlusionChanged() {
        setExpanded(!window.occlusionState.contains(.visible))
    }

    func setExpanded(_ expanded: Bool) {
        let W = expanded ? expandedW : normalW
        let H = expanded ? expandedH : normalH

        // Keep top-left corner anchored while resizing
        let f = window.frame
        window.setFrame(
            NSRect(x: f.origin.x, y: f.origin.y + f.height - H, width: W, height: H),
            display: true, animate: false
        )

        let labelWidth = W - 28
        nameLbl.frame = NSRect(x: 18, y: H * 0.28, width: labelWidth, height: H * 0.60)
        nameLbl.font = NSFont.boldSystemFont(
            ofSize: fitFontSize(text: family, maxWidth: labelWidth, start: expanded ? 140 : 62)
        )

        if let sub = subLbl {
            sub.frame = NSRect(x: 20, y: 10, width: W - 28, height: expanded ? 28 : 20)
            sub.font = NSFont.systemFont(ofSize: expanded ? 16 : 10, weight: .medium)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool {
        return true
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = Delegate()
app.delegate = delegate
app.run()
