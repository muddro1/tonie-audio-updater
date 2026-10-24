import Foundation

// Ported from tony.py. Same ffmpeg and yt-dlp invocations, same parsing, same limits.

public let audioExtensions = ["mp3", "wav", "m4a", "ogg"]
public let videoExtensions = ["mkv", "mp4", "avi", "mov", "wmv", "flv"]

public func isURL(_ value: String) -> Bool {
    let lower = value.lowercased()
    return lower.hasPrefix("http://") || lower.hasPrefix("https://")
}

func fileExtension(_ path: String) -> String { (path as NSString).pathExtension.lowercased() }
func fileName(_ path: String) -> String { (path as NSString).lastPathComponent }
func stem(_ path: String) -> String { (fileName(path) as NSString).deletingPathExtension }
func join(_ dir: String, _ name: String) -> String { (dir as NSString).appendingPathComponent(name) }

public func isVideo(_ value: String) -> Bool {
    !isURL(value) && videoExtensions.contains(fileExtension(value))
}

/// Files in dir with one of these extensions, matched ignoring case - a track off a
/// ripper is often Story.MP3.
public func findFiles(_ dir: String, _ extensions: [String]) -> [String] {
    let fm = FileManager.default
    let names = (try? fm.contentsOfDirectory(atPath: dir)) ?? []
    return names.map { join(dir, $0) }.filter { path in
        var isDir: ObjCBool = false
        return fm.fileExists(atPath: path, isDirectory: &isDir) && !isDir.boolValue
            && extensions.contains(fileExtension(path))
    }.sorted()
}

public func formatDuration(_ seconds: Double) -> String {
    let total = Int(seconds.rounded(.toNearestOrEven))
    return String(format: "%d:%02d:%02d", total / 3600, total % 3600 / 60, total % 60)
}

public func truncateTitle(_ title: String, _ maxLength: Int = 100) -> String {
    guard title.count > maxLength else { return title }
    let truncated = String(title.prefix(maxLength))
    // Break at a word when that still keeps at least 70% of the allowance
    if let space = truncated.lastIndex(of: " "),
       Double(truncated.distance(from: truncated.startIndex, to: space)) > Double(maxLength) * 0.7 {
        return String(truncated[..<space]).replacingOccurrences(of: "\\s+$", with: "",
                                                                options: .regularExpression)
    }
    return String(title.prefix(maxLength - 3)) + "..."
}

func parseDuration(_ stderr: String) -> Double? {
    for line in stderr.split(separator: "\n") {
        guard let range = line.range(of: "Duration: ") else { continue }
        let stamp = line[range.upperBound...].split(separator: ",").first ?? ""
        let parts = stamp.split(separator: ":").compactMap { Double($0) }
        if parts.count == 3 { return parts[0] * 3600 + parts[1] * 60 + parts[2] }
    }
    return nil
}

/// Seconds, from ffmpeg's banner alone - never a full decode, so it stays cheap.
public func audioDuration(_ path: String, _ o: Options) -> Double? {
    guard let result = try? runTool(o.ffmpegPath, ["-i", path], timeout: 15) else { return nil }
    return parseDuration(result.stderr)
}

func number(after key: String, in line: Substring) -> Double? {
    guard let range = line.range(of: key) else { return nil }
    return Double(line[range.upperBound...].split(separator: " ").first ?? "")
}

/// Where trailing silence starts, or nil when there is none worth cutting.
func silenceEnd(stderr: String, total: Double, minSilence: Double) -> Double? {
    var starts: [Double] = [], ends: [Double] = []
    for line in stderr.split(separator: "\n") {
        if let value = number(after: "silence_start: ", in: line) { starts.append(value) }
        else if let value = number(after: "silence_end: ", in: line) { ends.append(value) }
    }
    guard let lastStart = starts.last, total - lastStart >= minSilence else { return nil }
    if ends.count < starts.count || ends.last! < lastStart { return lastStart }
    // Less than a second of sound after the last silence still counts as trailing
    return total - ends.last! < 1.0 ? lastStart : nil
}

public func detectSilenceEnd(_ path: String, _ o: Options) -> Double? {
    let args = ["-i", path, "-vn",
                "-af", "silencedetect=noise=\(o.silenceThreshold):d=\(o.minSilenceDuration)",
                "-f", "null", "-"]
    guard let result = try? runTool(o.ffmpegPath, args),
          let total = audioDuration(path, o) else { return nil }
    return silenceEnd(stderr: result.stderr, total: total, minSilence: o.minSilenceDuration)
}

/// dir/base.ext, or dir/base_1.ext and so on when that is taken.
func uniquePath(_ dir: String, _ base: String, _ ext: String) -> String {
    var path = join(dir, "\(base).\(ext)")
    var counter = 1
    while FileManager.default.fileExists(atPath: path) {
        path = join(dir, "\(base)_\(counter).\(ext)")
        counter += 1
    }
    return path
}

/// An MP3 of the video's sound, with its trailing silence cut when trimming is on.
func convertVideo(_ video: String, into dir: String, _ o: Options, log: Log) throws -> String {
    let output = uniquePath(dir, stem(video), "mp3")
    log("Converting video to audio: \(fileName(video)) -> \(fileName(output))")

    let result = try runTool(o.ffmpegPath, ["-i", video, "-vn", "-acodec", "mp3",
                                            "-ab", o.audioBitrate, "-ar", "44100", "-y", output])
    guard result.status == 0 else {
        throw EngineError("Failed to convert \(fileName(video)): \(result.lastErrorLine)")
    }

    guard o.trimSilence else { return output }
    log("Analyzing audio for trailing silence: \(fileName(output))")
    guard let point = detectSilenceEnd(output, o) else {
        log("No significant trailing silence detected in \(fileName(output))")
        return output
    }

    log(String(format: "Trimming trailing silence from %.1fs to end", point))
    let trimmed = join(dir, "\(stem(output))_trimmed.mp3")
    let trim = try runTool(o.ffmpegPath, ["-i", output, "-t", "\(point)", "-acodec", "copy",
                                          "-y", trimmed])
    guard trim.status == 0 else {
        throw EngineError("Failed to trim \(fileName(output)): \(trim.lastErrorLine)")
    }
    try FileManager.default.removeItem(atPath: output)
    try FileManager.default.moveItem(atPath: trimmed, toPath: output)
    log("Successfully trimmed \(fileName(output))")
    return output
}

public struct LinkEntry: Sendable {
    public let url: String
    public let title: String
    public let duration: Double?
}

func nonEmpty(_ dict: [String: Any], _ key: String) -> String? {
    guard let value = dict[key] as? String, !value.isEmpty else { return nil }
    return value
}

/// What a link holds, without downloading it: one entry per video.
public func probeURL(_ url: String, _ o: Options) throws -> [LinkEntry] {
    let result = try runTool(o.ytdlpPath, ["-J", "--flat-playlist", "--no-warnings", url])
    guard result.status == 0 else {
        throw EngineError("Could not read \(url): \(result.lastErrorLine)")
    }
    guard let payload = try? JSONSerialization.jsonObject(with: Data(result.stdout.utf8))
            as? [String: Any] else {
        throw EngineError("Could not read \(url): unexpected output from yt-dlp")
    }

    func entry(_ item: [String: Any]) -> LinkEntry {
        LinkEntry(url: nonEmpty(item, "webpage_url") ?? nonEmpty(item, "url") ?? url,
                  title: nonEmpty(item, "title") ?? "Untitled",
                  duration: (item["duration"] as? NSNumber)?.doubleValue)
    }

    if payload["_type"] as? String == "playlist" {
        // A removed or private video appears as a null entry
        return ((payload["entries"] as? [Any]) ?? []).compactMap { $0 as? [String: Any] }.map(entry)
    }
    return [entry(payload)]
}

/// Download a link's audio as MP3, returning each file with the title the site gives it.
func downloadURL(_ url: String, into dir: String, _ o: Options) throws -> [(path: String, title: String)] {
    try FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    let result = try runTool(o.ytdlpPath, [
        "-x", "--audio-format", "mp3", "--audio-quality", o.audioBitrate,
        "--no-playlist-reverse",
        "--print-to-file", "%(title)s", "/dev/null",   // keeps stdout to the JSON below
        // after_move, or the path prints before extraction renames it
        "--print", #"after_move:{"title":%(title)j,"filepath":%(filepath)j}"#,
        "--no-simulate",
        "-o", join(dir, "%(title)s.%(ext)s"),
        url,
    ])
    guard result.status == 0 else {
        throw EngineError("Could not download \(url): \(result.lastErrorLine)")
    }

    let downloaded: [(path: String, title: String)] = result.stdout.split(separator: "\n").compactMap { line in
        guard let item = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any],
              let path = nonEmpty(item, "filepath") else { return nil }
        return (path, nonEmpty(item, "title") ?? "Untitled")
    }
    guard !downloaded.isEmpty else {
        throw EngineError("Could not download \(url): yt-dlp reported no output file")
    }
    return downloaded
}

/// ~/Downloads, where a kept download is easy to find - an app's working directory
/// is "/", which is read-only.
func defaultDownloadDir() -> String {
    let downloads = join(NSHomeDirectory(), "Downloads")
    if FileManager.default.isWritableFile(atPath: downloads) { return downloads }
    return makeTempDir("tonie_download_")
}

func makeTempDir(_ prefix: String) -> String {
    let dir = join(NSTemporaryDirectory(), prefix + UUID().uuidString.prefix(8))
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    return dir
}
