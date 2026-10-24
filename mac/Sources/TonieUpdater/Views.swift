import SwiftUI
import UniformTypeIdentifiers
import TonieCore

struct ContentView: View {
    @Bindable var model: AppModel
    // State used directly: the @State macro's plugin ships only with Xcode
    private let link = State(initialValue: "")

    var body: some View {
        VStack(spacing: 0) {
            if let banner = model.banner { bannerView(banner) }

            HSplitView {
                SourcesPane(model: model)
                    .frame(minWidth: 380)
                ToniesPane(model: model)
                    .frame(minWidth: 320)
            }

            Divider()
            ActivityView(model: model)
        }
        .toolbar { toolbar }
        .onDrop(of: [.fileURL, .url, .plainText], isTargeted: nil, perform: drop)
        .sheet(item: $model.signInPrompt) { prompt in
            SignInSheet(model: model, message: prompt.message, username: model.username ?? "")
        }
        .alert("Add a link", isPresented: $model.askingForLink) {
            TextField("Video or playlist address", text: link.projectedValue)
            Button("Add") {
                let value = link.wrappedValue.trimmingCharacters(in: .whitespaces)
                link.wrappedValue = ""
                if !value.isEmpty { model.addSources([value]) }
            }
            Button("Cancel", role: .cancel) { link.wrappedValue = "" }
        }
        .alert("Confirm upload", isPresented: $model.confirmingUpload) {
            Button("Upload", role: .destructive) { model.startUpload() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(model.confirmationText)
        }
        .alert("Stop the upload?", isPresented: $model.confirmingCancel) {
            Button("Stop", role: .destructive) { model.confirmCancel() }
            Button("Keep Going", role: .cancel) {}
        } message: {
            Text(model.cancelConfirmationText)
        }
        .task {
            model.checkTools()
            model.ensureSignedIn()
        }
    }

    @ToolbarContentBuilder
    var toolbar: some ToolbarContent {
        ToolbarItemGroup(placement: .navigation) {
            Menu {
                Button("Folder...") { model.chooseFolder() }
                Button("Files...") { model.chooseFiles() }
                Button("Link...") { model.askingForLink = true }
            } label: {
                Label("Add", systemImage: "plus")
            } primaryAction: {
                model.chooseFiles()
            }
            .help("Add files - or open the menu for a folder or a link")
            .disabled(model.busy)
        }

        ToolbarItemGroup(placement: .primaryAction) {
            if model.busy {
                ProgressView().controlSize(.small)
                Button { model.cancelPressed() } label: {
                    Label("Cancel", systemImage: "xmark.circle")
                }
                .help("Stop after the current step")
            }

            Menu {
                if model.cloud != nil, let username = model.username {
                    Text("Signed in as \(username)")
                    Button("Refresh Tonies") { model.refreshTonies() }
                    Divider()
                    Button("Sign Out") { model.signOut() }
                } else {
                    Button("Sign In...") { model.signInPrompt = .init(message: nil) }
                }
            } label: {
                Label("Account", systemImage: model.cloud != nil ? "person.crop.circle.fill"
                                                                : "person.crop.circle")
            }
            .disabled(model.busy)

            SettingsLink {
                Label("Settings", systemImage: "gearshape")
            }
            .help("Conversion, silence, limits and run options")

            Button { model.uploadPressed() } label: {
                Label(model.options.dryRun ? "Dry Run" : "Upload", systemImage: "arrow.up.circle.fill")
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(.borderedProminent)
            .keyboardShortcut(.defaultAction)
            .disabled(!model.canUpload)
        }
    }

    func bannerView(_ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: "exclamationmark.circle.fill").foregroundStyle(.orange)
            Text(text).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
            if !model.installCommand.isEmpty {
                Button("Copy Install Command") { model.copyInstallCommand() }
            }
            Button { model.dismissBanner() } label: { Image(systemName: "xmark") }
                .buttonStyle(.borderless)
                .help("Dismiss")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
        .background(.orange.opacity(0.12))
        .overlay(alignment: .bottom) { Divider() }
    }

    /// Everything dropped together is expanded together, as one batch.
    func drop(_ providers: [NSItemProvider]) -> Bool {
        let group = DispatchGroup()
        let collected = Collected()
        for provider in providers {
            group.enter()
            if provider.canLoadObject(ofClass: URL.self) {
                _ = provider.loadObject(ofClass: URL.self) { url, _ in
                    if let url { collected.add([url.isFileURL ? url.path : url.absoluteString]) }
                    group.leave()
                }
            } else {
                _ = provider.loadObject(ofClass: String.self) { text, _ in
                    let lines = (text ?? "").split(separator: "\n")
                        .map { $0.trimmingCharacters(in: .whitespaces) }
                        .filter { isURL($0) || FileManager.default.fileExists(atPath: $0) }
                    collected.add(lines)
                    group.leave()
                }
            }
        }
        group.notify(queue: .main) { model.addSources(collected.values) }
        return true
    }
}

final class Collected: @unchecked Sendable {
    private let lock = NSLock()
    private var items: [String] = []
    func add(_ values: [String]) { lock.withLock { items += values } }
    var values: [String] { lock.withLock { items } }
}

/// A pane's title row: a heading and whatever controls belong to it.
struct PaneHeader<Trailing: View>: View {
    let title: String
    @ViewBuilder let trailing: Trailing

    var body: some View {
        HStack {
            Text(title).font(.headline)
            Spacer()
            trailing
        }
        .padding(.horizontal, 14)
        .padding(.top, 12)
        .padding(.bottom, 6)
    }
}

struct SourcesPane: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            PaneHeader(title: "Audio") {
                ControlGroup {
                    Button { model.moveSelected(-1) } label: { Image(systemName: "chevron.up") }
                        .help("Move Up")
                    Button { model.moveSelected(1) } label: { Image(systemName: "chevron.down") }
                        .help("Move Down")
                }
                .fixedSize()
                Button { model.removeSelected() } label: { Image(systemName: "trash") }
                    .help("Remove")
            }
            .disabled(model.busy || model.sourceSelection.isEmpty)

            List(selection: $model.sourceSelection) {
                OutlineGroup(model.sources, children: \.childrenOrNil) { node in
                    SourceRow(model: model, node: node)
                }
            }
            .disabled(model.busy)
            .overlay {
                if model.sources.isEmpty {
                    ContentUnavailableView {
                        Label("No Audio", systemImage: "music.note.list")
                    } description: {
                        Text("Drop audio, video, folders or links here, or use Add in the toolbar.")
                    }
                }
            }

            Divider()
            CapacityFooter(model: model)
        }
    }
}

struct SourceRow: View {
    let model: AppModel
    @Bindable var node: SourceNode

    var icon: String {
        switch node.kind {
        case .folder: "folder"
        case .link: node.children.isEmpty ? "play.rectangle" : "list.and.film"
        case .file: isVideo(node.value) ? "film" : "music.note"
        }
    }

    var body: some View {
        HStack(spacing: 8) {
            if node.error == nil {
                Toggle("", isOn: Binding(get: { node.selected }, set: { node.setSelected($0) }))
                    .toggleStyle(.checkbox)
                    .labelsHidden()
            } else {
                // Kept so the reason can be read, but there is nothing to upload
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
            }
            Image(systemName: icon).foregroundStyle(.secondary).frame(width: 18)
            VStack(alignment: .leading, spacing: 1) {
                Text(node.title).lineLimit(1).truncationMode(.middle)
                if let error = node.error {
                    Text(error).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                }
            }
            .help(node.value)
            Spacer()
            if model.options.trimSilence, node.trimmed != nil, node.children.isEmpty {
                Image(systemName: "scissors").font(.caption).foregroundStyle(.secondary)
                    .help("Length after trimming trailing silence")
            }
            Text(model.lengthText(node)).monospacedDigit().foregroundStyle(.secondary)
        }
        .opacity(node.selected || node.error != nil ? 1 : 0.55)
    }
}

/// How full a Creative Tonie would be, with the trimming controls that change it.
struct CapacityFooter: View {
    @Bindable var model: AppModel

    var body: some View {
        let seconds = model.totals().seconds
        let limit = model.options.maxDuration * 60
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(model.summaryText).monospacedDigit()
                Spacer()
                if !model.options.noDurationLimit {
                    Text("of \(formatDuration(limit))").monospacedDigit().foregroundStyle(.secondary)
                }
            }
            if !model.options.noDurationLimit {
                ProgressView(value: min(seconds, limit), total: limit)
                    .tint(model.isOverLimit ? .red : .accentColor)
            }
            HStack {
                Toggle("Trim trailing silence", isOn: $model.options.trimSilence)
                    .toggleStyle(.checkbox)
                Spacer()
                Button("Measure Trimmed Length") { model.measureTrim() }
                    .controlSize(.small)
                    .help("Find each video's trailing silence now, so the total shows what will "
                          + "upload. Only videos are trimmed.")
            }
            .disabled(model.busy)
        }
        .font(.callout)
        .padding(14)
        .foregroundStyle(model.isOverLimit ? .red : .primary)
    }
}

struct ToniesPane: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            PaneHeader(title: "Creative Tonies") {
                Button("Select Needing Update") { model.selectNeedingUpdate() }
                    .controlSize(.small)
                    .disabled(model.busy || model.tonies.isEmpty)
            }

            List {
                ForEach(model.tonies) { tonie in
                    DisclosureGroup {
                        ForEach(Array(tonie.chapters.enumerated()), id: \.offset) { i, chapter in
                            HStack {
                                Text("\(i + 1)").monospacedDigit().foregroundStyle(.tertiary)
                                    .frame(width: 22, alignment: .trailing)
                                Text(chapter.title).lineLimit(1)
                                Spacer()
                                Text(chapter.seconds.map(formatDuration) ?? "")
                                    .monospacedDigit().foregroundStyle(.secondary)
                            }
                            .font(.callout)
                        }
                    } label: {
                        TonieRow(model: model, tonie: tonie)
                    }
                }
            }
            .disabled(model.busy)
            .overlay {
                if model.tonies.isEmpty {
                    if model.cloud == nil {
                        ContentUnavailableView {
                            Label("Not Signed In", systemImage: "person.crop.circle.badge.questionmark")
                        } description: {
                            Text("Sign in to see your Creative Tonies.")
                        } actions: {
                            Button("Sign In...") { model.signInPrompt = .init(message: nil) }
                                .disabled(model.busy)
                        }
                    } else {
                        ContentUnavailableView("No Creative Tonies", systemImage: "figure.child",
                                               description: Text("This account has none."))
                    }
                }
            }
        }
    }
}

struct TonieRow: View {
    @Bindable var model: AppModel
    let tonie: CreativeTonie

    var body: some View {
        HStack(spacing: 10) {
            Toggle("", isOn: Binding(
                get: { model.checkedTonies.contains(tonie.id) },
                set: { if $0 { model.checkedTonies.insert(tonie.id) } else { model.checkedTonies.remove(tonie.id) } }
            ))
            .toggleStyle(.checkbox)
            .labelsHidden()

            Group {
                if let image = model.images[tonie.id] {
                    Image(nsImage: image).resizable().scaledToFit()
                } else {
                    Image(systemName: "figure.child").font(.title2).foregroundStyle(.secondary)
                }
            }
            .frame(width: 40, height: 40)

            VStack(alignment: .leading, spacing: 2) {
                Text(tonie.name).font(.body.weight(.medium))
                Text(model.households[tonie.id] ?? "").font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Text("\(tonie.chapters.count) chapter\(tonie.chapters.count == 1 ? "" : "s")")
                Text(formatDuration(tonie.chapters.compactMap(\.seconds).reduce(0, +)))
                    .monospacedDigit()
            }
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 3)
    }
}

/// The log, folded away until there is something to watch.
struct ActivityView: View {
    @Bindable var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.snappy) { model.showLog.toggle() }
            } label: {
                HStack {
                    Image(systemName: "chevron.right")
                        .rotationEffect(.degrees(model.showLog ? 90 : 0))
                    Text("Activity").font(.headline)
                    if !model.showLog, let last = model.log.last {
                        Text(last).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Spacer()
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 14)
            .padding(.vertical, 8)

            if model.showLog {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 2) {
                            ForEach(Array(model.log.enumerated()), id: \.offset) { i, line in
                                Text(line).font(.system(.caption, design: .monospaced)).id(i)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                        .padding(10)
                    }
                    .frame(height: 150)
                    .background(.background.secondary)
                    .onChange(of: model.log.count) { proxy.scrollTo(model.log.count - 1, anchor: .bottom) }
                }
            }
        }
        .onChange(of: model.busy) { if model.busy { model.showLog = true } }
    }
}

struct SettingsView: View {
    @Bindable var model: AppModel

    var body: some View {
        TabView {
            Form {
                Section {
                    Toggle("Trim trailing silence", isOn: $model.options.trimSilence)
                    TextField("Threshold", text: $model.options.silenceThreshold)
                    LabeledContent("Minimum silence") {
                        numberField(value: $model.options.minSilenceDuration, suffix: "seconds",
                                    range: 0...60, step: 0.5)
                    }
                } footer: {
                    Text("Only videos are trimmed, as they are converted to audio.")
                        .foregroundStyle(.secondary)
                }
            }
            .tabItem { Label("Silence", systemImage: "waveform") }

            Form {
                Toggle("Keep converted files", isOn: $model.options.keepConverted)
                Picker("Bitrate", selection: $model.options.audioBitrate) {
                    ForEach(bitrates, id: \.self) { Text($0) }
                }
                TextField("ffmpeg", text: $model.options.ffmpegPath)
                TextField("yt-dlp", text: $model.options.ytdlpPath)
            }
            .tabItem { Label("Conversion", systemImage: "film") }

            Form {
                Section("Duration") {
                    Toggle("No duration limit", isOn: $model.options.noDurationLimit)
                    LabeledContent("Maximum") {
                        numberField(value: $model.options.maxDuration, suffix: "minutes",
                                    range: 1...1000, step: 5)
                    }
                    .disabled(model.options.noDurationLimit)
                }
                Section("Uploads") {
                    Stepper("Attempts per file: \(model.options.uploadRetries)",
                            value: $model.options.uploadRetries, in: 1...10)
                    LabeledContent("Delay between attempts") {
                        numberField(value: $model.options.retryDelay, suffix: "seconds",
                                    range: 0...60, step: 0.5)
                    }
                }
            }
            .tabItem { Label("Limits", systemImage: "gauge.with.dots.needle.67percent") }

            Form {
                Toggle("Dry run (change nothing)", isOn: $model.options.dryRun)
                Toggle("Force update, even when a Tonie looks up to date",
                       isOn: $model.options.forceUpdate)
            }
            .tabItem { Label("Run", systemImage: "play.circle") }
        }
        .formStyle(.grouped)
        // A checkmark says on or off plainly; a switch leans on colour, which an
        // inactive window drops
        .toggleStyle(.checkbox)
        .frame(width: 460, height: 300)
        .disabled(model.busy)
    }

    /// The presets, plus whatever custom value is already set.
    var bitrates: [String] {
        let presets = ["64k", "96k", "128k", "192k", "256k"]
        return presets.contains(model.options.audioBitrate) ? presets
                                                            : presets + [model.options.audioBitrate]
    }

    func numberField(value: Binding<Double>, suffix: String, range: ClosedRange<Double>,
                     step: Double) -> some View {
        HStack {
            TextField("", value: value, format: .number)
                .labelsHidden()
                .multilineTextAlignment(.trailing)
                .frame(width: 60)
            Text(suffix).foregroundStyle(.secondary)
            Stepper("", value: value, in: range, step: step).labelsHidden()
        }
    }
}

struct SignInSheet: View {
    let model: AppModel
    let message: String?
    private let username: State<String>
    private let password = State(initialValue: "")
    private let remember = State(initialValue: true)
    @Environment(\.dismiss) private var dismiss

    init(model: AppModel, message: String?, username: String) {
        self.model = model
        self.message = message
        self.username = State(initialValue: username)
    }

    var canSignIn: Bool {
        !username.wrappedValue.trimmingCharacters(in: .whitespaces).isEmpty
            && !password.wrappedValue.isEmpty
    }

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "person.crop.circle")
                .font(.system(size: 44))
                .foregroundStyle(.tint)
            Text("Sign in to Tonie Cloud").font(.title3.weight(.semibold))
            if let message {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
                    .font(.callout)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Form {
                TextField("Username", text: username.projectedValue, prompt: Text("you@example.com"))
                SecureField("Password", text: password.projectedValue)
                Toggle("Remember in Keychain", isOn: remember.projectedValue)
                    .toggleStyle(.checkbox)
            }
            .formStyle(.grouped)
            .scrollDisabled(true)
            .frame(height: 140)
            HStack {
                Button("Cancel", role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Spacer()
                Button("Sign In") {
                    dismiss()
                    model.signIn(username: username.wrappedValue.trimmingCharacters(in: .whitespaces),
                                 password: password.wrappedValue, remember: remember.wrappedValue)
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(!canSignIn)
            }
        }
        .padding(24)
        .frame(width: 400)
    }
}
