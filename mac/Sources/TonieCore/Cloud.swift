import Foundation
import UniformTypeIdentifiers

// The same calls the Python tonie-api library makes.

public struct Chapter: Decodable, Sendable {
    public let title: String
    public let seconds: Double?
}

public struct CreativeTonie: Decodable, Identifiable, Sendable {
    public let id: String
    public let householdId: String
    public let name: String
    public let imageUrl: String?
    public var chapters: [Chapter]

    public var chapterTitles: [String] { chapters.map(\.title) }
}

struct Household: Decodable {
    let id: String
    let name: String
}

/// A Tonie Cloud session. Its access tokens are short-lived, and everything between
/// sign-in and the first write - picking sources, downloading, converting - can easily
/// outlast one, so a 401 signs in again and retries once.
public final class TonieCloud: @unchecked Sendable {
    static let api = URL(string: "https://api.tonie.cloud/v2")!
    static let login = URL(string:
        "https://login.tonies.com/auth/realms/tonies/protocol/openid-connect/token")!

    let username: String
    let password: String
    private let lock = NSLock()
    private var token: String?
    private let session: URLSession

    public init(username: String, password: String) {
        self.username = username
        self.password = password
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 30
        session = URLSession(configuration: config)
    }

    /// Sign in, replacing whatever token is currently held.
    public func signIn() async throws {
        var request = URLRequest(url: Self.login)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.httpBody = formEncode(["grant_type": "password", "client_id": "my-tonies",
                                       "scope": "openid", "username": username,
                                       "password": password])
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 400 || status == 401 {
            throw EngineError("Tonie Cloud did not accept that username and password.")
        }
        guard (200..<300).contains(status),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let fresh = json["access_token"] as? String else {
            throw EngineError("Could not sign in to Tonie Cloud (HTTP \(status)).")
        }
        lock.withLock { token = fresh }
    }

    @discardableResult
    func call(_ method: String, _ path: String, json: Any? = nil) async throws -> Data {
        for attempt in 1...2 {
            var request = URLRequest(url: Self.api.appendingPathComponent(path))
            request.httpMethod = method
            request.setValue("Bearer \(lock.withLock { token ?? "" })",
                             forHTTPHeaderField: "Authorization")
            if let json {
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.httpBody = try JSONSerialization.data(withJSONObject: json)
            }
            let (data, response) = try await session.data(for: request)
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            if status == 401 && attempt == 1 {
                try await signIn()
                continue
            }
            // Never treat a failure as an empty success: a "cleared" Tonie that was
            // not, or an upload that silently went nowhere, is worse than an error
            guard (200..<300).contains(status) else {
                throw EngineError("Tonie Cloud answered HTTP \(status) to \(method) \(path)")
            }
            return data
        }
        throw EngineError("Tonie Cloud kept rejecting the session for \(method) \(path)")
    }

    /// Every Creative Tonie on the account, with the name of the household each is in.
    public func creativeTonies() async throws -> ([CreativeTonie], [String: String]) {
        let households = try JSONDecoder().decode([Household].self, from: try await call("GET", "households"))
        var tonies: [CreativeTonie] = []
        var names: [String: String] = [:]
        for household in households {
            let data = try await call("GET", "households/\(household.id)/creativetonies")
            for tonie in try JSONDecoder().decode([CreativeTonie].self, from: data) {
                tonies.append(tonie)
                names[tonie.id] = household.name
            }
        }
        return (tonies, names)
    }

    func toniePath(_ tonie: CreativeTonie) -> String {
        "households/\(tonie.householdId)/creativetonies/\(tonie.id)"
    }

    public func clearChapters(_ tonie: CreativeTonie) async throws {
        try await call("PATCH", toniePath(tonie), json: ["chapters": []])
    }

    /// Upload a file to S3 through a presigned form, then append it as a chapter.
    public func upload(_ path: String, title: String, to tonie: CreativeTonie) async throws {
        let ticket = try JSONSerialization.jsonObject(with: try await call("POST", "file")) as? [String: Any]
        guard let fileId = ticket?["fileId"] as? String,
              let form = ticket?["request"] as? [String: Any],
              let urlString = form["url"] as? String, let url = URL(string: urlString),
              let fields = form["fields"] as? [String: Any],
              let key = fields["key"] else {
            throw EngineError("Tonie Cloud returned an upload ticket this app does not understand")
        }

        let boundary = "tonie-\(UUID().uuidString)"
        let body = try multipartBody(fields: fields.mapValues { "\($0)" }, filename: "\(key)",
                                     file: path, boundary: boundary)
        defer { try? FileManager.default.removeItem(at: body) }

        var request = URLRequest(url: url, timeoutInterval: 180)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        let (_, response) = try await session.upload(for: request, fromFile: body)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw EngineError("The file store answered HTTP \(status) to the upload")
        }

        try await call("POST", "\(toniePath(tonie))/chapters", json: ["title": title, "file": fileId])
    }
}

func formEncode(_ values: [String: String]) -> Data {
    var allowed = CharacterSet.alphanumerics
    allowed.insert(charactersIn: "-._~")
    return Data(values.map { key, value in
        "\(key)=\(value.addingPercentEncoding(withAllowedCharacters: allowed) ?? "")"
    }.joined(separator: "&").utf8)
}

/// The multipart form written to a temp file and streamed from there, so a 90 minute
/// file is never held in memory whole. The file part goes last, as S3 requires.
func multipartBody(fields: [String: String], filename: String, file: String,
                   boundary: String) throws -> URL {
    let body = FileManager.default.temporaryDirectory.appendingPathComponent("tonie-upload-\(UUID().uuidString)")
    FileManager.default.createFile(atPath: body.path, contents: nil)
    let out = try FileHandle(forWritingTo: body)
    defer { try? out.close() }

    for (name, value) in fields.sorted(by: { $0.key < $1.key }) {
        out.write(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8))
    }
    let mime = UTType(filenameExtension: fileExtension(file))?.preferredMIMEType ?? "application/octet-stream"
    out.write(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\nContent-Type: \(mime)\r\n\r\n".utf8))

    let input = try FileHandle(forReadingFrom: URL(fileURLWithPath: file))
    defer { try? input.close() }
    while let chunk = try input.read(upToCount: 1 << 20), !chunk.isEmpty {
        out.write(chunk)
    }
    out.write(Data("\r\n--\(boundary)--\r\n".utf8))
    return body
}

/// A Tonie's picture, cached on disk - in the same place the Qt app caches it - since
/// a figure's artwork never changes. Any failure just means no picture.
public func tonieImage(_ tonie: CreativeTonie) async -> URL? {
    let dir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("tonie-audio-updater/tonie-images")
    let path = dir.appendingPathComponent("\(tonie.id).image")
    if FileManager.default.fileExists(atPath: path.path) { return path }

    guard let string = tonie.imageUrl, let url = URL(string: string),
          let (data, response) = try? await URLSession.shared.data(from: url),
          ((response as? HTTPURLResponse)?.statusCode ?? 0) / 100 == 2 else { return nil }

    // Written beside and renamed in, so a half-written file is never taken for a hit
    try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    let partial = path.appendingPathExtension("tmp")
    guard (try? data.write(to: partial)) != nil,
          (try? FileManager.default.moveItem(at: partial, to: path)) != nil else { return nil }
    return path
}
