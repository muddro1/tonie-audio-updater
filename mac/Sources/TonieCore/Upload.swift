import Foundation

public struct AudioTitle: Sendable {
    public var path: String
    public var title: String
    var isConverted = false
    var isDownloaded = false
    var isCapped = false
    var duration: Double?

    var notes: String {
        var notes: [String] = []
        if isConverted { notes.append("converted from video") }
        if isDownloaded { notes.append("downloaded") }
        if isCapped { notes.append("truncated to the duration limit") }
        return notes.isEmpty ? "" : " (\(notes.joined(separator: ", ")))"
    }
}

/// The files to upload, and the temporary ones made along the way.
public final class PreparedAudio: @unchecked Sendable {
    public var files: [AudioTitle] = []
    var temporary: [String] = []
    let keep: Bool

    init(keep: Bool) { self.keep = keep }

    /// Remove converted, downloaded and truncated copies, unless asked to keep them,
    /// and any temp directory of ours they leave empty.
    public func cleanUp() {
        guard !keep else { return }
        let fm = FileManager.default
        for path in temporary { try? fm.removeItem(atPath: path) }
        for dir in Set(temporary.map { ($0 as NSString).deletingLastPathComponent })
        where dir.hasPrefix(NSTemporaryDirectory()) && ((try? fm.contentsOfDirectory(atPath: dir)) ?? ["x"]).isEmpty {
            try? fm.removeItem(atPath: dir)
        }
        temporary = []
    }
}

/// Turn the ticked leaves into uploadable audio, in list order - downloading links and
/// converting videos - then hold the set to the duration limit.
public func prepareAudio(_ leaves: [SourceNode], _ o: Options, log: Log,
                         cancel: CancelFlag) throws -> PreparedAudio {
    let prepared = PreparedAudio(keep: o.keepConverted)
    do {
        try gather(leaves, into: prepared, o, log: log, cancel: cancel)
        guard !prepared.files.isEmpty else { throw EngineError("No audio to upload.") }
        try enforceMaxDuration(prepared, o, log: log)
    } catch {
        prepared.cleanUp()
        throw error
    }
    return prepared
}

func gather(_ leaves: [SourceNode], into prepared: PreparedAudio, _ o: Options, log: Log,
            cancel: CancelFlag) throws {
    if leaves.contains(where: { isURL($0.value) }) && !ytdlpAvailable(o) {
        throw EngineError("yt-dlp not found at '\(o.ytdlpPath)'. It is required for links. "
                          + "Install it with: brew install yt-dlp")
    }
    if leaves.contains(where: { isVideo($0.value) }) && !ffmpegAvailable(o) {
        throw EngineError("ffmpeg not found at '\(o.ffmpegPath)'. It is required for video. "
                          + "Install it with: brew install ffmpeg")
    }

    var downloadDir: String?
    var convertDir: String?

    for leaf in leaves {
        if cancel.isSet { throw EngineError("Cancelled before anything was uploaded.") }

        if isURL(leaf.value) {
            let dir = downloadDir ?? (o.keepConverted ? defaultDownloadDir() : makeTempDir("tonie_download_"))
            downloadDir = dir
            log("Downloading \(leaf.title)")
            for item in try downloadURL(leaf.value, into: dir, o) {
                prepared.files.append(AudioTitle(path: item.path, title: truncateTitle(item.title),
                                                 isDownloaded: true))
                prepared.temporary.append(item.path)
                log("Downloaded: \(item.title)")
            }
        } else if isVideo(leaf.value) {
            // Kept files go beside their video; otherwise one temp directory for all
            let dir = o.keepConverted ? (leaf.value as NSString).deletingLastPathComponent
                                      : (convertDir ?? makeTempDir("tonie_converted_"))
            if !o.keepConverted { convertDir = dir }
            do {
                let audio = try convertVideo(leaf.value, into: dir, o, log: log)
                prepared.files.append(AudioTitle(path: audio, title: truncateTitle(stem(leaf.value)),
                                                 isConverted: true))
                prepared.temporary.append(audio)
            } catch {
                // One bad video is dropped, as the CLI drops it, rather than sinking the run
                log("Failed to convert \(fileName(leaf.value)): \(error.localizedDescription)")
            }
        } else {
            prepared.files.append(AudioTitle(path: leaf.value, title: truncateTitle(stem(leaf.value))))
        }
    }
}

/// A single file over the limit is replaced by a truncated copy; a set of several is
/// only warned about, since choosing which to cut is the user's call.
///
/// Throws when a single file cannot be truncated: uploading clears the Tonie first, so
/// sending a file the service will reject would wipe it and then fail.
func enforceMaxDuration(_ prepared: PreparedAudio, _ o: Options, log: Log) throws {
    guard !o.noDurationLimit else { return }
    let maxSeconds = o.maxDuration * 60
    guard ffmpegAvailable(o) else {
        log("ffmpeg not found - skipping the \(o.maxDuration.clean) minute duration check")
        return
    }

    for i in prepared.files.indices {
        prepared.files[i].duration = audioDuration(prepared.files[i].path, o)
        if prepared.files[i].duration == nil {
            log("Could not determine the duration of \(fileName(prepared.files[i].path)) - "
                + "it is excluded from the duration check")
        }
    }

    if prepared.files.count == 1 {
        let file = prepared.files[0]
        guard let duration = file.duration, duration > maxSeconds else { return }
        log("'\(file.title)' runs \(formatDuration(duration)), over the \(o.maxDuration.clean) "
            + "minute limit - truncating to \(formatDuration(maxSeconds))")
        guard let capped = capAudio(file.path, maxSeconds, prepared, o, log: log) else {
            throw EngineError("'\(file.title)' runs \(formatDuration(duration)) and could not be "
                + "truncated to the \(o.maxDuration.clean) minute limit. Stopping before any "
                + "Creative Tonie is modified. Shorten the file yourself, or tick No duration limit.")
        }
        prepared.files[0].path = capped
        prepared.files[0].duration = audioDuration(capped, o)
        prepared.files[0].isCapped = true
        log("Truncated copy written to \(capped) (original left untouched)")
        return
    }

    let total = prepared.files.compactMap(\.duration).reduce(0, +)
    if total > maxSeconds {
        log("WARNING: \(prepared.files.count) files total \(formatDuration(total)), which is "
            + "\(formatDuration(total - maxSeconds)) over the \(o.maxDuration.clean) minute "
            + "Creative Tonie limit. Sets of several files are never truncated - uploading as "
            + "is will clear the Tonie's chapters and then be rejected.")
    }
}

/// Stream copying cuts on a frame boundary, which rounds up - enough for the service to
/// reject it. Aim under the limit, measure, and widen the margin until it fits.
func capAudio(_ source: String, _ maxSeconds: Double, _ prepared: PreparedAudio, _ o: Options,
              log: Log) -> String? {
    let parent = (source as NSString).deletingLastPathComponent
    let dir = parent.hasPrefix(NSTemporaryDirectory()) ? parent : makeTempDir("tonie_capped_")
    let ext = fileExtension(source)
    var capped = join(dir, "\(stem(source))_capped.\(ext)")
    var counter = 1
    while FileManager.default.fileExists(atPath: capped) {
        capped = join(dir, "\(stem(source))_capped_\(counter).\(ext)")
        counter += 1
    }
    prepared.temporary.append(capped)

    var margin = 1.0
    for _ in 1...4 {                            // margins of 1s, 5s, 21s, 85s
        let target = maxSeconds - margin
        guard target > 0,
              let result = try? runTool(o.ffmpegPath, ["-i", source, "-t", "\(target)",
                                                       "-acodec", "copy", "-y", capped]),
              result.status == 0 else { return nil }
        guard let actual = audioDuration(capped, o) else {
            log("Could not measure the truncated copy - assuming it is within the limit")
            return capped
        }
        if actual <= maxSeconds { return capped }
        margin = margin * 4 + 1
    }
    return nil
}

// MARK: - Deciding what needs updating

func normalize(_ title: String) -> String {
    title.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
}

/// Name a few titles from a multiset, and how many more there were.
func sampleTitles(_ titles: [String], originals: [String: String], limit: Int = 3) -> String {
    let sorted = titles.sorted()
    let names = sorted.prefix(limit).map { "'\(originals[$0] ?? $0)'" }
    let list = "[\(names.joined(separator: ", "))]"
    let leftOut = sorted.count - names.count
    return leftOut > 0 ? "\(list) and \(leftOut) more" : list
}

/// Remove one occurrence from a for each element of b, like Counter subtraction.
func subtract(_ a: [String], _ b: [String]) -> [String] {
    var remaining = a
    for title in b {
        if let i = remaining.firstIndex(of: title) { remaining.remove(at: i) }
    }
    return remaining
}

/// Whether a Tonie holding these chapter titles needs these files, and why.
/// Compared in order: a Tonie plays its chapters in the order they are stored.
public func needsUpdate(chapters: [String], files: [String], force: Bool) -> (Bool, String) {
    if force { return (true, "Force update requested") }
    if chapters.isEmpty { return (true, "No chapters on tonie") }
    if files.count != chapters.count {
        return (true, "Different number of files (\(files.count) vs \(chapters.count) chapters)")
    }

    let audio = files.map(normalize), held = chapters.map(normalize)
    if audio == held { return (false, "Up to date") }
    if audio.sorted() == held.sorted() { return (true, "Same files in a different order") }

    let incoming = sampleTitles(subtract(audio, held),
                                originals: Dictionary(zip(audio, files), uniquingKeysWith: { a, _ in a }))
    let outgoing = sampleTitles(subtract(held, audio),
                                originals: Dictionary(zip(held, chapters), uniquingKeysWith: { a, _ in a }))
    return (true, "Different files: tonie holds \(outgoing), not \(incoming)")
}

// MARK: - Uploading

public struct Outcome: Sendable {
    public let name: String
    public let status: String       // updated | skipped | failed | cancelled
    public let detail: String
}

/// Upload the prepared files to each Tonie in turn. A Tonie already holding them is
/// skipped unless forced; one that fails does not abandon the rest; cancelling stops
/// before the next file, and a Tonie stopped partway is reported cancelled - its
/// chapters were already cleared, so "updated" would be a lie.
public func uploadToTonies(_ cloud: TonieCloud, _ tonies: [CreativeTonie],
                           households: [String: String], audio: [AudioTitle], _ o: Options,
                           log: Log, cancel: CancelFlag) async -> [Outcome] {
    var outcomes: [Outcome] = []
    var cancelled = false

    for tonie in tonies {
        if cancelled || cancel.isSet {
            cancelled = true
            outcomes.append(Outcome(name: tonie.name, status: "cancelled", detail: "Not started"))
            continue
        }

        let (needed, reason) = needsUpdate(chapters: tonie.chapterTitles,
                                           files: audio.map(\.title), force: o.forceUpdate)
        guard needed else {
            log("'\(tonie.name)' is already up to date")
            outcomes.append(Outcome(name: tonie.name, status: "skipped", detail: reason))
            continue
        }
        log("Update reason for '\(tonie.name)': \(reason)")

        do {
            let finished = try await updateTonie(cloud, tonie, household: households[tonie.id] ?? "Unknown",
                                                 audio: audio, o, log: log, cancel: cancel)
            if finished {
                outcomes.append(Outcome(name: tonie.name, status: "updated", detail: reason))
            } else {
                cancelled = true
                outcomes.append(Outcome(name: tonie.name, status: "cancelled",
                                        detail: "Stopped partway through the upload; this Tonie may be incomplete"))
            }
        } catch {
            log("Failed to update '\(tonie.name)': \(error.localizedDescription)")
            outcomes.append(Outcome(name: tonie.name, status: "failed", detail: error.localizedDescription))
        }
    }
    return outcomes
}

/// Clear one Tonie and upload every file to it. False when cancelled partway.
func updateTonie(_ cloud: TonieCloud, _ tonie: CreativeTonie, household: String,
                 audio: [AudioTitle], _ o: Options, log: Log, cancel: CancelFlag) async throws -> Bool {
    let dry = o.dryRun ? "[DRY RUN] " : ""
    log("\(dry)Updating '\(tonie.name)' (Household: \(household)) with \(audio.count) files")

    if o.dryRun {
        for (i, file) in audio.enumerated() {
            log("[DRY RUN] Would upload (\(i + 1)/\(audio.count)): \(file.title)\(file.notes)")
        }
        log("[DRY RUN] Successfully updated '\(tonie.name)'")
        return true
    }

    // Clearing is unavoidable - the 90 minute limit is on the whole Tonie - so record
    // what is there first: if the upload then fails, this is the only trace of it
    let previous = tonie.chapterTitles
    if !previous.isEmpty {
        log("'\(tonie.name)' currently holds \(previous.count) chapters, about to be replaced: \(previous)")
    }
    log("Clearing all chapters from '\(tonie.name)'")
    try await cloud.clearChapters(tonie)

    for (i, file) in audio.enumerated() {
        if cancel.isSet {
            log("Cancelled after \(i) of \(audio.count) files. '\(tonie.name)' is incomplete.")
            if !previous.isEmpty {
                log("These chapters were cleared and are no longer on '\(tonie.name)': \(previous)")
            }
            return false
        }
        log("Uploading (\(i + 1)/\(audio.count)): \(file.title)\(file.notes)")
        do {
            try await uploadWithRetries(cloud, file, to: tonie, o, log: log)
        } catch {
            log("'\(tonie.name)' is now incomplete: \(i) of \(audio.count) files uploaded")
            if !previous.isEmpty {
                log("These chapters were cleared and are no longer on '\(tonie.name)': \(previous)")
            }
            throw error
        }
    }
    log("Successfully updated '\(tonie.name)'")
    return true
}

/// The Tonie is already cleared by now, so a dropped connection is worth a few tries.
func uploadWithRetries(_ cloud: TonieCloud, _ file: AudioTitle, to tonie: CreativeTonie,
                       _ o: Options, log: Log) async throws {
    let attempts = max(1, o.uploadRetries)
    var delay = o.retryDelay
    for attempt in 1...attempts {
        do {
            try await cloud.upload(file.path, title: file.title, to: tonie)
            return
        } catch {
            if attempt == attempts {
                log("Giving up on '\(file.title)' after \(attempts) attempts: \(error.localizedDescription)")
                throw error
            }
            log("Upload of '\(file.title)' failed (attempt \(attempt)/\(attempts)): \(error.localizedDescription)")
            if delay > 0 {
                log("Retrying in \(delay.clean)s")
                try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            }
            delay *= 2
        }
    }
}

extension Double {
    /// 90 rather than 90.0, as Python's :g prints it.
    public var clean: String { String(format: "%g", self) }
}
