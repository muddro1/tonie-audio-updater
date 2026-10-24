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
try? FileManager.default.removeItem(atPath: tmp)

print(failures == 0 ? "All checks passed" : "\(failures) check(s) failed")
exit(failures == 0 ? 0 : 1)
