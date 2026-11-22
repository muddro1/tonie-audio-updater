// The engine's checks: swift run SelfTest
// (swift-testing and XCTest need Xcode; this needs only the command line tools.)
import Foundation
@testable import TonieCore

var failures = 0
func check(_ ok: Bool, _ what: String, line: Int = #line) {
    if !ok {
        failures += 1
        print("FAIL line \(line): \(what)")
    }
}
let quiet: Log = { _ in }

/// Run async engine code to completion. Top-level await would make every global here
/// main-actor isolated, and the engine's @Sendable callbacks would warn about it.
func blocking(_ body: @escaping @Sendable () async -> Void) {
    let done = DispatchSemaphore(value: 0)
    Task.detached { await body(); done.signal() }
    done.wait()
}

// Formatting and titles
check(formatDuration(3725.4) == "1:02:05", "formatDuration")
check(truncateTitle("short") == "short", "short title untouched")
let long = String(repeating: "word ", count: 30)
check(truncateTitle(long).count <= 100 && !truncateTitle(long).hasSuffix(" "), "breaks at a word")
check(truncateTitle(String(repeating: "x", count: 120)) == String(repeating: "x", count: 97) + "...",
      "ellipsis when no good break")
check(90.0.clean == "90" && 2.5.clean == "2.5", "clean numbers")

// ffmpeg output parsing
check(parseDuration("  Duration: 00:01:30.50, start: 0") == 90.5, "parseDuration")
check(parseDuration("  Duration: N/A, bitrate: N/A") == nil, "unknown duration")
check(silenceEnd(stderr: "[silencedetect] silence_start: 6.02", total: 10, minSilence: 2) == 6.02,
      "silence running to the end")
check(silenceEnd(stderr: "silence_start: 3\nsilence_end: 5 | silence_duration: 2", total: 10, minSilence: 2) == nil,
      "silence in the middle is kept")
check(silenceEnd(stderr: "silence_start: 7\nsilence_end: 9.5 | x", total: 10, minSilence: 2) == 7,
      "under a second of sound after silence still trims")

// Deciding what needs updating
check(needsUpdate(chapters: ["A", "B"], files: ["a ", "b"], force: false) == (false, "Up to date"),
      "case and spaces ignored")
check(needsUpdate(chapters: ["A", "B"], files: ["B", "A"], force: false).1 == "Same files in a different order",
      "order matters")
check(needsUpdate(chapters: [], files: ["A"], force: false).0, "empty Tonie")
check(needsUpdate(chapters: ["A"], files: ["A"], force: true).0, "forced")
check(needsUpdate(chapters: ["A", "X"], files: ["A", "B"], force: false).1
      == "Different files: tonie holds ['X'], not ['B']", "names what differs")

// The source list
let a = SourceNode(kind: .file, value: "/tmp/a.mp3", title: "a", duration: 60)
let v = SourceNode(kind: .file, value: "/tmp/v.mp4", title: "v", duration: 600)
let dup = SourceNode(kind: .file, value: "/tmp/a.mp3", title: "a", duration: 60)
let bad = SourceNode(kind: .link, value: "https://x", title: "x", error: "nope")
let empty = SourceNode(kind: .folder, value: "/tmp/empty", title: "empty")
let list = [a, v, dup, bad, empty]
check(uploadLeaves(list).map(\.title) == ["a", "v"], "dedupes, skips errors and empty folders")
v.trimmed = 300
check(totals(list, trim: true).seconds == 360 && totals(list, trim: false).seconds == 660,
      "trimmed length only when trimming")
check(trimmable(list).map(\.title) == ["v"], "only local videos are trimmable")
v.setSelected(false)
check(totals(list, trim: false).count == 1, "unticked leaves drop out")

// Multipart form: fields first, file last
let tmp = makeTempDir("tonie_selftest_")
let payload = join(tmp, "x.mp3")
try Data("AUDIO".utf8).write(to: URL(fileURLWithPath: payload))
let body = try String(contentsOf: multipartBody(fields: ["key": "k1", "policy": "p"], filename: "k1",
                                                file: payload, boundary: "B"), encoding: .utf8)
check(body.hasPrefix("--B\r\nContent-Disposition: form-data; name=\"key\"") && body.hasSuffix("AUDIO\r\n--B--\r\n"),
      "multipart layout")
check(String(decoding: formEncode(["p": "a&b c"]), as: UTF8.self) == "p=a%26b%20c", "form encoding")

// The real thing, through ffmpeg: 6 seconds of tone, then 4 of silence
var o = Options()
if ffmpegAvailable(o) {
    let video = join(tmp, "clip.mp4")
    _ = try runTool("ffmpeg", ["-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=10:s=160x120",
                               "-f", "lavfi", "-i", "sine=d=6", "-af", "apad", "-t", "10", "-shortest", video])
    check(abs((audioDuration(video, o) ?? 0) - 10) < 0.2, "reads a video's duration")
    check(abs((detectSilenceEnd(video, o) ?? 0) - 6) < 0.3, "finds trailing silence in a video")

    let node = expandSource(video, o)
    let prepared = try prepareAudio([node], o, log: quiet, cancel: CancelFlag())
    let converted = prepared.files[0]
    check(converted.isConverted && abs((audioDuration(converted.path, o) ?? 0) - 6) < 0.3,
          "converts and trims")

    o.maxDuration = 0.05                       // 3 seconds
    let capped = try prepareAudio([node], o, log: quiet, cancel: CancelFlag())
    check(capped.files[0].isCapped && (audioDuration(capped.files[0].path, o) ?? 99) <= 3,
          "a single over-long file is truncated under the limit")
    let paths = prepared.files.map(\.path) + capped.files.map(\.path)
    prepared.cleanUp()
    capped.cleanUp()
    check(!paths.contains { FileManager.default.fileExists(atPath: $0) }, "temporary files cleaned up")

    let folder = expandSource(tmp, o)
    check(folder.kind == .folder && folder.children.map(\.title).contains("clip"), "folder expands")
} else {
    print("skipped the ffmpeg checks: ffmpeg not found")
}

// Kept conversions go in a "converted" folder, so a second run does not take the MP3
// as more audio and convert the video again
if ffmpegAvailable(o) {
    var keep = Options()
    keep.keepConverted = true
    keep.noDurationLimit = true
    let shelf = makeTempDir("tonie_selftest_keep_")
    _ = try runTool("ffmpeg", ["-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=d=2",
                               "-c:a", "aac", join(shelf, "Story.mp4")])
    let runs = try (1...2).map { _ in
        try prepareAudio(uploadLeaves([expandSource(shelf, keep)]), keep, log: quiet,
                         cancel: CancelFlag()).files
    }
    check(runs.allSatisfy { $0.map(\.title) == ["Story"] }, "a kept conversion is not uploaded twice")
    check(runs[0].first.map { ($0.path as NSString).deletingLastPathComponent } == join(shelf, "converted"),
          "kept conversions go in a converted folder")
    try? FileManager.default.removeItem(atPath: shelf)
}
try? FileManager.default.removeItem(atPath: tmp)

// Tonie Cloud, through a stubbed network: what the server answers decides what happens
final class Stub: URLProtocol {
    static var answer: (URLRequest) -> (Int, String) = { _ in (500, "") }
    static var seen: [String] = []
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Stub.seen.append("\(request.httpMethod ?? "") \(request.url!.host ?? "")\(request.url!.path)")
        let (status, body) = Stub.answer(request)
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status,
                                                               httpVersion: nil, headerFields: nil)!,
                            cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
func stubbedCloud() -> TonieCloud {
    let config = URLSessionConfiguration.ephemeral
    config.protocolClasses = [Stub.self]
    Stub.seen = []
    return TonieCloud(username: "u", password: "p", configuration: config)
}

Stub.answer = { _ in (500, "") }
blocking {
    do {
        try await stubbedCloud().call("GET", "households")
        check(false, "an error answer throws")
    } catch {}
}

var expired = true
Stub.answer = { request in
    if request.url!.host == "login.tonies.com" { return (200, #"{"access_token":"fresh"}"#) }
    if expired { expired = false; return (401, "") }
    return (200, "[]")
}
let reauthed = stubbedCloud()
blocking { _ = try? await reauthed.call("GET", "households") }
check(Stub.seen == ["GET api.tonie.cloud/v2/households", "POST login.tonies.com/auth/realms/tonies/protocol/openid-connect/token",
                    "GET api.tonie.cloud/v2/households"], "a 401 signs in again and retries once")

// The chapter is added, but its answer is lost: the retry must not add it again
var chapters = 0
Stub.answer = { request in
    switch (request.httpMethod!, request.url!.path) {
    case ("POST", "/v2/file"):
        return (200, #"{"fileId":"f1","request":{"url":"https://s3.test/","fields":{"key":"k1"}}}"#)
    case ("POST", "/"): return (204, "")
    case ("POST", let path) where path.hasSuffix("/chapters"):
        chapters += 1
        return (500, "")
    case (_, "/v2/households"): return (200, #"[{"id":"h1","name":"Home"}]"#)
    case (_, let path) where path.hasSuffix("/creativetonies"):
        let held = Array(repeating: #"{"title":"One"}"#, count: chapters).joined(separator: ",")
        return (200, #"[{"id":"t1","householdId":"h1","name":"Lion","chapters":["# + held + "]}]")
    default: return (404, "")
    }
}
let audioFile = join(NSTemporaryDirectory(), "tonie_selftest_\(UUID().uuidString).mp3")
try Data("AUDIO".utf8).write(to: URL(fileURLWithPath: audioFile))
let lion = CreativeTonie(id: "t1", householdId: "h1", name: "Lion", imageUrl: nil, chapters: [])
var retrying = Options()
retrying.retryDelay = 0
blocking {
    try? await uploadWithRetries(stubbedCloud(), AudioTitle(path: audioFile, title: "One"), to: lion,
                                 uploadedBefore: 0, retrying, log: quiet)
}
check(chapters == 1, "a retry does not add a chapter that already landed")
try? FileManager.default.removeItem(atPath: audioFile)

print(failures == 0 ? "All checks passed" : "\(failures) check(s) failed")
exit(failures == 0 ? 0 : 1)
