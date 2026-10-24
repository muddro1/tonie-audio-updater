import Foundation
import Observation

/// One row in the source list. A folder or a link also has tickable children.
///
/// Expanding is deliberately cheap - a folder is scanned, a file's duration is read,
/// a link's metadata is fetched. Nothing is converted or downloaded until Upload.
@Observable
public final class SourceNode: Identifiable {
    public enum Kind: Sendable { case file, folder, link }

    public let id = UUID()
    public let kind: Kind
    public let value: String          // path or URL
    public var title: String
    public var duration: Double?
    public var trimmed: Double?       // duration once trailing silence is cut, if measured
    public var children: [SourceNode] = []
    public var selected = true
    public var error: String?

    public init(kind: Kind, value: String, title: String, duration: Double? = nil,
                error: String? = nil) {
        self.kind = kind
        self.value = value
        self.title = title
        self.duration = duration
        self.error = error
    }

    /// For OutlineGroup, which reads an empty array as "expandable but empty".
    public var childrenOrNil: [SourceNode]? { children.isEmpty ? nil : children }

    public func setSelected(_ value: Bool) {
        selected = value
        children.forEach { $0.setSelected(value) }
    }

    /// Whether node is this one or anywhere beneath it.
    public func contains(_ id: UUID) -> Bool {
        self.id == id || children.contains { $0.contains(id) }
    }
}

/// Turn a dropped or chosen path or link into a node. Never throws: a source that
/// cannot be read stays in the list carrying its reason.
public func expandSource(_ value: String, _ o: Options) -> SourceNode {
    if isURL(value) { return expandLink(value, o) }
    var isDir: ObjCBool = false
    guard FileManager.default.fileExists(atPath: value, isDirectory: &isDir) else {
        return SourceNode(kind: .file, value: value, title: stem(value),
                          error: "No such file or folder")
    }
    if isDir.boolValue {
        let folder = SourceNode(kind: .folder, value: value,
                                title: fileName((value as NSString).standardizingPath))
        let found = findFiles(value, audioExtensions) + findFiles(value, videoExtensions)
        folder.children = found.sorted().map { expandFile($0, o) }
        return folder
    }
    return expandFile(value, o)
}

func expandFile(_ path: String, _ o: Options) -> SourceNode {
    SourceNode(kind: .file, value: path, title: stem(path), duration: audioDuration(path, o))
}

func expandLink(_ url: String, _ o: Options) -> SourceNode {
    let node = SourceNode(kind: .link, value: url, title: url)
    let entries: [LinkEntry]
    do {
        entries = try probeURL(url, o)
    } catch {
        node.error = error.localizedDescription
        return node
    }
    guard !entries.isEmpty else {
        node.error = "No playable videos found at this link"
        return node
    }
    node.children = entries.map {
        SourceNode(kind: .link, value: $0.url, title: $0.title, duration: $0.duration)
    }
    node.title = entries.count == 1 ? entries[0].title : "\(entries.count) videos"
    return node
}

/// What makes two sources the same upload: a resolved path, or the URL itself.
func dedupKey(_ value: String) -> String {
    isURL(value) ? value : URL(fileURLWithPath: value).resolvingSymlinksInPath().path
}

/// Every ticked, real, uploadable leaf, each once, in list order. A folder is never a
/// leaf, even empty, and a link that failed carries no media - one bad link must not
/// sink the run. Totals and the upload both walk this, so they cannot disagree.
public func uploadLeaves(_ items: [SourceNode]) -> [SourceNode] {
    var seen = Set<String>()
    var leaves: [SourceNode] = []
    func walk(_ nodes: [SourceNode]) {
        for node in nodes {
            if !node.children.isEmpty {
                walk(node.children)
            } else if node.selected && node.error == nil && node.kind != .folder,
                      seen.insert(dedupKey(node.value)).inserted {
                leaves.append(node)
            }
        }
    }
    walk(items)
    return leaves
}

/// A leaf's seconds as it would upload: its measured trimmed length when trimming.
public func length(of node: SourceNode, trim: Bool) -> Double? {
    trim && node.trimmed != nil ? node.trimmed : node.duration
}

/// (file count, seconds) for everything ticked. An unknown duration counts as a file
/// but adds no time, so the total reads as a floor rather than pretending to be exact.
public func totals(_ items: [SourceNode], trim: Bool) -> (count: Int, seconds: Double) {
    let leaves = uploadLeaves(items)
    return (leaves.count, leaves.compactMap { length(of: $0, trim: trim) }.reduce(0, +))
}

/// Every local video, ticked or not - the only files trimmed, since trimming happens
/// while a video is converted.
public func trimmable(_ items: [SourceNode]) -> [SourceNode] {
    items.flatMap { node -> [SourceNode] in
        if !node.children.isEmpty { return trimmable(node.children) }
        return node.error == nil && node.kind == .file && isVideo(node.value) ? [node] : []
    }
}
