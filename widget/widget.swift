import AppKit

let args = CommandLine.arguments
let family  = args.count > 1 ? args[1] : "Agent"
let members = args.count > 2 ? args[2] : ""

class Delegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!

    func applicationDidFinishLaunching(_ n: Notification) {
        let W: CGFloat = 300
        let H: CGFloat = 160

        // Position: top-left, 60pt from edges
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

        // Family name
        let nameLbl = NSTextField(wrappingLabelWithString: family)
        nameLbl.frame = NSRect(x: 18, y: H * 0.28, width: W - 28, height: H * 0.60)
        nameLbl.font = NSFont.boldSystemFont(ofSize: 62)
        nameLbl.textColor = NSColor(calibratedRed: 0.08, green: 0.08, blue: 0.08, alpha: 1.0)
        nameLbl.backgroundColor = .clear
        nameLbl.drawsBackground = false
        nameLbl.lineBreakMode = .byTruncatingTail
        content.addSubview(nameLbl)

        // Members row
        if !members.isEmpty {
            let subLbl = NSTextField(labelWithString: members)
            subLbl.frame = NSRect(x: 20, y: 10, width: W - 28, height: 20)
            subLbl.font = NSFont.systemFont(ofSize: 10, weight: .medium)
            subLbl.textColor = NSColor(calibratedRed: 0.22, green: 0.40, blue: 0.08, alpha: 1.0)
            subLbl.backgroundColor = .clear
            subLbl.drawsBackground = false
            content.addSubview(subLbl)
        }

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool {
        return true
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)   // no dock icon
let delegate = Delegate()
app.delegate = delegate
app.run()
