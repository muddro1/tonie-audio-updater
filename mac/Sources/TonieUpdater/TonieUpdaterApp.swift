import AppKit
import SwiftUI

@main
struct TonieUpdaterApp: App {
    // A plain let: @State is a macro whose plugin ships only with Xcode, and the App
    // value is made once anyway
    private let model = AppModel()

    init() {
        // Also a regular, frontmost app when run straight from `swift run`, unbundled
        NSApplication.shared.setActivationPolicy(.regular)
        NSApplication.shared.activate()
    }

    var body: some Scene {
        Window("Tonie Audio Updater", id: "main") {
            ContentView(model: model)
                .frame(minWidth: 820, minHeight: 560)
        }
        .defaultSize(width: 980, height: 680)

        Settings {
            SettingsView(model: model)
        }
    }
}
