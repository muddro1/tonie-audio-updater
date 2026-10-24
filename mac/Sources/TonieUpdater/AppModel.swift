import AppKit
import Observation
import TonieCore
import UniformTypeIdentifiers

let limitHint = "Creative Tonies hold 90 minutes"

/// Everything the window shows and does. Slow work runs off the main actor, one piece
/// at a time; while it runs every input is disabled and Cancel is the only way out.
@MainActor
@Observable
final class AppModel {
    var sources: [SourceNode] = []
    var sourceSelection = Set<UUID>()

    var tonies: [CreativeTonie] = []
    var households: [String: String] = [:]
    var images: [String: NSImage] = [:]
    var checkedTonies = Set<String>()

    var options = Options() {
        didSet {
            // A measurement only holds for the settings it was taken with
            if options.silenceThreshold != oldValue.silenceThreshold
                || options.minSilenceDuration != oldValue.minSilenceDuration {
                trimmable(sources).forEach { $0.trimmed = nil }
            }
        }
    }
    var showLog = false

    var log: [String] = []
    var banner: String?
    var installCommand = ""

    var busy = false
    var uploading = false
    let cancel = CancelFlag()

    var cloud: TonieCloud?
    var username: String?
    var password: String?
    var signInPrompt: SignInPrompt?

    // Dialogs the view presents
    var askingForLink = false
    var confirmingUpload = false
    var confirmingCancel = false

    struct SignInPrompt: Identifiable {
        let id = UUID()
        let message: String?
    }

    init() {
        (username, password) = Account.saved()
    }

    // MARK: - Running work

    /// Log lines arrive in order: DispatchQueue.main is FIFO, unlike separate Tasks.
    nonisolated func logger() -> Log {
        { [weak self] line in
            DispatchQueue.main.async { MainActor.assumeIsolated { self?.append(line) } }
        }
    }

    func append(_ line: String) {
        log.append(line)
        if log.count > 5000 { log.removeFirst(log.count - 5000) }
    }

    /// Run one piece of work in the background, unless something already is.
    func run<T>(_ work: @escaping @Sendable (Log) async throws -> T,
                done: @escaping (T) -> Void,
                failed: ((String) -> Void)? = nil) {
        guard !busy else {
            banner = "Something is already running."
            return
        }
        busy = true
        let log = logger()
        Task.detached {
            do {
                let result = try await work(log)
                await MainActor.run {
                    self.busy = false
                    done(result)
                }
            } catch {
                let message = error.localizedDescription
                await MainActor.run {
                    self.busy = false
                    self.uploading = false
                    self.append(message)
                    self.banner = message
                    failed?(message)
                }
            }
        }
    }

    func cancelPressed() {
        if busy && uploading {
            confirmingCancel = true
        } else {
            confirmCancel()
        }
    }

    func confirmCancel() {
        cancel.set()
        append("Cancelling after the current step...")
    }

    // MARK: - Tools

    func checkTools() {
        let options = options
        Task.detached {
            var warnings: [(String, String)] = []
            if !ffmpegAvailable(options) {
                warnings.append(("FFmpeg is not installed. Video conversion, silence trimming, the "
                                 + "duration check and links are unavailable; plain audio still uploads.",
                                 "brew install ffmpeg"))
            }
            if !ytdlpAvailable(options) {
                warnings.append(("yt-dlp is not installed. Links and playlists are unavailable; "
                                 + "files and folders still work.", "brew install yt-dlp"))
            }
            let found = warnings
            await MainActor.run {
                let warnings = found
                guard !warnings.isEmpty else { return }
                self.banner = warnings.map { "\($0.0) (\($0.1))" }.joined(separator: "\n")
                self.installCommand = warnings.map(\.1).joined(separator: "; ")
            }
        }
    }

    func copyInstallCommand() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(installCommand, forType: .string)
    }

    func dismissBanner() {
        banner = nil
        installCommand = ""
    }

    // MARK: - Sources

    func addSources(_ values: [String]) {
        let values = values.filter { !$0.isEmpty }
        guard !values.isEmpty else { return }
        let options = options
        run({ _ in values.map { expandSource($0, options) } },
            done: { self.sources.append(contentsOf: $0) })
    }

    func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.message = "Choose a folder of audio"
        if panel.runModal() == .OK { addSources(panel.urls.map(\.path)) }
    }

    func chooseFiles() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.allowedContentTypes = (audioExtensions + videoExtensions).compactMap {
            UTType(filenameExtension: $0)
        }
        panel.message = "Choose audio or video files"
        if panel.runModal() == .OK { addSources(panel.urls.map(\.path)) }
    }

    /// Top-level sources touched by the selection. Selecting a file inside a folder
    /// counts as selecting the folder - Remove and the move buttons work on whole sources.
    var selectedTopLevel: [Int] {
        sources.indices.filter { i in sourceSelection.contains { sources[i].contains($0) } }
    }

    func removeSelected() {
        let doomed = Set(selectedTopLevel)
        sources = sources.enumerated().filter { !doomed.contains($0.offset) }.map(\.element)
        sourceSelection = []
    }

    /// Shift the selected sources one place; a contiguous block moves as a unit.
    func moveSelected(_ delta: Int) {
        let indices = selectedTopLevel
        var moved = Set(indices)
        for i in (delta < 0 ? indices : indices.reversed()) {
            let j = i + delta
            guard sources.indices.contains(j), !moved.contains(j) else { continue }
            sources.swapAt(i, j)
            moved.remove(i)
            moved.insert(j)
        }
    }

    func totals(_ items: [SourceNode]? = nil) -> (count: Int, seconds: Double) {
        TonieCore.totals(items ?? sources, trim: options.trimSilence)
    }

    func lengthText(_ node: SourceNode) -> String {
        if !node.children.isEmpty { return formatDuration(totals([node]).seconds) }
        return length(of: node, trim: options.trimSilence).map(formatDuration) ?? ""
    }

    var isOverLimit: Bool {
        !options.noDurationLimit && totals().seconds > options.maxDuration * 60
    }

    var summaryText: String {
        let (count, seconds) = totals()
        guard count > 0 else { return "No files selected" }
        var text = "\(count) \(count == 1 ? "file" : "files") · \(formatDuration(seconds))"
        if isOverLimit { text += " · over the \(options.maxDuration.clean) minute limit" }
        return text
    }

    /// Measure each video's trailing silence now, so the totals show what will upload.
    func measureTrim() {
        let items = trimmable(sources)
        guard !items.isEmpty else {
            banner = "Only videos are trimmed, and there are none in the list."
            return
        }
        let jobs = items.map { ($0.value, $0.title, $0.duration) }
        let options = options
        let cancel = cancel
        cancel.clear()
        run({ log in
            var lengths: [Double?] = []
            for (path, title, duration) in jobs {
                if cancel.isSet { break }
                log("Measuring trailing silence: \(title)")
                lengths.append(detectSilenceEnd(path, options) ?? duration)
            }
            return lengths
        }, done: { lengths in
            for (item, seconds) in zip(items, lengths) { item.trimmed = seconds }
            // Keep what was measured, but a cancelled measurement does not opt in
            if !self.cancel.isSet { self.options.trimSilence = true }
        })
    }

    // MARK: - Tonies

    var selectedTonies: [CreativeTonie] { tonies.filter { checkedTonies.contains($0.id) } }

    /// The titles the upload would give the ticked files, in upload order.
    var previewTitles: [String] { uploadLeaves(sources).map { truncateTitle($0.title) } }

    func selectNeedingUpdate() {
        let titles = previewTitles
        checkedTonies = Set(tonies.filter {
            needsUpdate(chapters: $0.chapterTitles, files: titles, force: false).0
        }.map(\.id))
    }

    // MARK: - Account

    func ensureSignedIn() {
        if username != nil && password != nil {
            refreshTonies()
        } else {
            signInPrompt = SignInPrompt(message: nil)
        }
    }

    func signIn(username: String, password: String, remember: Bool) {
        Account.save(username: username, password: password, remember: remember)
        self.username = username
        self.password = password
        refreshTonies()
    }

    func refreshTonies() {
        guard let username, let password else {
            signInPrompt = SignInPrompt(message: nil)
            return
        }
        run({ log -> (TonieCloud, [CreativeTonie], [String: String], [String: NSImage]) in
            let cloud = TonieCloud(username: username, password: password)
            try await cloud.signIn()
            let (tonies, households) = try await cloud.creativeTonies()
            var images: [String: NSImage] = [:]
            for tonie in tonies {
                if let url = await tonieImage(tonie), let image = NSImage(contentsOf: url) {
                    images[tonie.id] = image
                }
            }
            return (cloud, tonies, households, images)
        }, done: { cloud, tonies, households, images in
            self.cloud = cloud
            self.tonies = tonies
            self.households = households
            self.images = images
            // Keep whatever was ticked and is still there
            self.checkedTonies.formIntersection(tonies.map(\.id))
        }, failed: { message in
            self.signInPrompt = SignInPrompt(message: message)
        })
    }

    func signOut() {
        Account.forget(username)
        cloud = nil
        username = nil
        password = nil
        tonies = []
        checkedTonies = []
        banner = "Signed out."
    }

    // MARK: - Upload

    var canUpload: Bool { !busy && !uploadLeaves(sources).isEmpty && !checkedTonies.isEmpty }

    func uploadPressed() {
        guard !busy else { banner = "Something is already running."; return }
        guard !selectedTonies.isEmpty else { banner = "Choose at least one Creative Tonie."; return }
        guard !uploadLeaves(sources).isEmpty else { banner = "Add some audio first."; return }
        guard cloud != nil else { signInPrompt = SignInPrompt(message: nil); return }
        confirmingUpload = true
    }

    /// What the confirmation says: how much is going where, what each Tonie holds now,
    /// what will be cleared, and whether the run is over the limit.
    var confirmationText: String {
        let selected = selectedTonies
        let (count, seconds) = totals()
        let titles = previewTitles
        let clearing = selected.reduce(0) { $0 + $1.chapters.count }

        var lines = ["Upload \(count) file\(count == 1 ? "" : "s") (\(formatDuration(seconds))) to "
                     + "\(selected.count) Creative Tonie\(selected.count == 1 ? "" : "s"):", ""]
        for tonie in selected {
            let needed = needsUpdate(chapters: tonie.chapterTitles, files: titles,
                                     force: options.forceUpdate).0
            lines.append("  • \(tonie.name) (\(households[tonie.id] ?? "Unknown")), "
                         + "\(tonie.chapters.count) chapters"
                         + (needed ? "" : "  — already up to date, will be skipped"))
        }
        lines += ["", "\(clearing) chapters will be cleared and replaced."]
        if isOverLimit {
            lines += ["", "WARNING: \(formatDuration(seconds - options.maxDuration * 60)) over the "
                      + "\(options.maxDuration.clean) minute limit. \(limitHint).",
                      "The upload will likely be rejected."]
        }
        return lines.joined(separator: "\n")
    }

    var cancelConfirmationText: String {
        var lines = ["Stopping now may leave a Creative Tonie incomplete: its existing chapters "
                     + "are cleared before the new ones are uploaded."]
        let titles = selectedTonies.flatMap(\.chapterTitles)
        if !titles.isEmpty {
            lines += ["", "Chapters that were on the ticked Creative Tonies:"]
            lines += titles.map { "  • \($0)" }
        }
        return lines.joined(separator: "\n")
    }

    func startUpload() {
        guard let cloud else { return }
        let leaves = uploadLeaves(sources)
        let tonies = selectedTonies
        let households = households
        let options = options
        let cancel = cancel
        cancel.clear()
        log = []
        banner = nil
        uploading = true

        run({ log -> [Outcome] in
            let prepared = try prepareAudio(leaves, options, log: log, cancel: cancel)
            defer { prepared.cleanUp() }
            // Renew the token before the first write; preparing can outlast it
            if !options.dryRun { try await cloud.signIn() }
            return await uploadToTonies(cloud, tonies, households: households,
                                        audio: prepared.files, options, log: log, cancel: cancel)
        }, done: { outcomes in
            self.uploading = false
            self.finished(outcomes)
        })
    }

    /// One line per Tonie, worst news first, and the counts in the banner.
    func finished(_ outcomes: [Outcome]) {
        guard !outcomes.isEmpty else {
            banner = "Nothing to do"
            return
        }
        let order = ["failed": 0, "cancelled": 1, "updated": 2, "skipped": 3]
        for outcome in outcomes.sorted(by: { order[$0.status, default: 9] < order[$1.status, default: 9] }) {
            append("\(outcome.name): \(outcome.status)" + (outcome.detail.isEmpty ? "" : " — \(outcome.detail)"))
        }
        let counts = Dictionary(grouping: outcomes, by: \.status).mapValues(\.count)
        banner = counts.sorted { $0.key < $1.key }.map { "\($0.value) \($0.key)" }.joined(separator: ", ")

        // Read back what the Tonies hold now, so Select Needing Update stays right
        if outcomes.contains(where: { $0.status != "skipped" }) && !options.dryRun {
            let banner = banner
            refreshTonies()
            self.banner = banner
        }
    }
}
