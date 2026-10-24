// swift-tools-version:5.10
// Swift 5 language mode: the engine shells out and blocks on purpose, off the main
// actor, which Swift 6's strict checking would make a lot of ceremony for no gain.
import PackageDescription

let package = Package(
    name: "TonieUpdater",
    platforms: [.macOS(.v14)],
    targets: [
        // Everything that is not a widget, so the self-test can reach it
        .target(name: "TonieCore"),
        .executableTarget(name: "TonieUpdater", dependencies: ["TonieCore"]),
        // swift-testing and XCTest both need Xcode; this runs with the command line tools
        .executableTarget(name: "SelfTest", dependencies: ["TonieCore"]),
    ]
)
