import Foundation

/// Every setting the Qt window's Advanced section exposes, with the same defaults -
/// except trimming, which the app has on by default.
public struct Options: Sendable {
    public var ffmpegPath = "ffmpeg"
    public var ytdlpPath = "yt-dlp"
    public var audioBitrate = "128k"
    public var keepConverted = false

    public var trimSilence = true
    public var silenceThreshold = "-50dB"
    public var minSilenceDuration = 2.0

    public var maxDuration = 90.0          // minutes
    public var noDurationLimit = false
    public var uploadRetries = 3
    public var retryDelay = 2.0            // seconds, doubling each attempt

    public var dryRun = false
    public var forceUpdate = false

    public init() {}
}

public typealias Log = @Sendable (String) -> Void

public struct EngineError: LocalizedError {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}

/// Polled between steps that can safely be stopped between.
public final class CancelFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var value = false
    public init() {}
    public var isSet: Bool { lock.withLock { value } }
    public func set() { lock.withLock { value = true } }
    public func clear() { lock.withLock { value = false } }
}

/// Homebrew (Apple Silicon and Intel) and MacPorts. An app opened from Finder gets
/// launchd's minimal PATH, which holds none of them, so an installed ffmpeg would
/// read as missing - and yt-dlp, which finds ffmpeg itself, would fail to extract.
let extraPaths = ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin",
                  "/usr/local/sbin", "/opt/local/bin", "/opt/local/sbin"]

var searchPath: [String] {
    let current = (ProcessInfo.processInfo.environment["PATH"] ?? "")
        .split(separator: ":").map(String.init)
    return current + extraPaths.filter { !current.contains($0) }
}

func resolveTool(_ tool: String) -> String? {
    let fm = FileManager.default
    if tool.contains("/") {
        let path = (tool as NSString).expandingTildeInPath
        return fm.isExecutableFile(atPath: path) ? path : nil
    }
    return searchPath.map { "\($0)/\(tool)" }.first { fm.isExecutableFile(atPath: $0) }
}

struct ToolResult {
    let status: Int32
    let stdout: String
    let stderr: String

    var lastErrorLine: String {
        stderr.split(separator: "\n").last.map(String.init) ?? "unknown error"
    }
}

/// Run a tool to completion. A timeout fails toward "not read" rather than waiting
/// forever on, say, a spun-down network drive.
func runTool(_ tool: String, _ args: [String], timeout: TimeInterval? = nil) throws -> ToolResult {
    guard let executable = resolveTool(tool) else {
        throw EngineError("\(tool) was not found. Install it with: brew install \(tool)")
    }

    let process = Process()
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = args
    var environment = ProcessInfo.processInfo.environment
    environment["PATH"] = searchPath.joined(separator: ":")
    process.environment = environment

    let out = Pipe(), err = Pipe()
    process.standardOutput = out
    process.standardError = err
    process.standardInput = FileHandle.nullDevice
    try process.run()

    // Both pipes drained at once, so a tool filling one cannot deadlock on the other
    var outData = Data(), errData = Data()
    let group = DispatchGroup()
    DispatchQueue.global().async(group: group) { outData = out.fileHandleForReading.readDataToEndOfFile() }
    DispatchQueue.global().async(group: group) { errData = err.fileHandleForReading.readDataToEndOfFile() }

    if let timeout, group.wait(timeout: .now() + timeout) == .timedOut {
        process.terminate()
        group.wait()
        process.waitUntilExit()
        throw EngineError("\(tool) timed out")
    }
    group.wait()
    process.waitUntilExit()

    return ToolResult(status: process.terminationStatus,
                      stdout: String(decoding: outData, as: UTF8.self),
                      stderr: String(decoding: errData, as: UTF8.self))
}

public func ffmpegAvailable(_ o: Options) -> Bool {
    (try? runTool(o.ffmpegPath, ["-version"], timeout: 15))?.status == 0
}

public func ytdlpAvailable(_ o: Options) -> Bool {
    (try? runTool(o.ytdlpPath, ["--version"], timeout: 15))?.status == 0
}
