import Foundation
import Security

/// The account password lives only in the login Keychain, under the same service name
/// the Qt app uses, so a password it saved is found here too. The username is not a
/// secret and lives in UserDefaults to prefill the sign-in sheet.
public enum Account {
    static let service = "tonie-audio-updater"
    static let usernameKey = "account/username"

    public static func saved() -> (username: String?, password: String?) {
        guard let username = UserDefaults.standard.string(forKey: usernameKey),
              !username.isEmpty else { return (nil, nil) }
        return (username, loadPassword(username))
    }

    /// Remember the username always; the password only if asked.
    public static func save(username: String, password: String, remember: Bool) {
        UserDefaults.standard.set(username, forKey: usernameKey)
        deletePassword(username)
        if remember { storePassword(username, password) }
    }

    public static func forget(_ username: String?) {
        UserDefaults.standard.removeObject(forKey: usernameKey)
        if let username { deletePassword(username) }
    }

    static func query(_ username: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: username]
    }

    static func loadPassword(_ username: String) -> String? {
        var item = query(username)
        item[kSecReturnData as String] = true
        item[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: AnyObject?
        guard SecItemCopyMatching(item as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func storePassword(_ username: String, _ password: String) {
        var item = query(username)
        item[kSecValueData as String] = Data(password.utf8)
        SecItemAdd(item as CFDictionary, nil)
    }

    static func deletePassword(_ username: String) {
        SecItemDelete(query(username) as CFDictionary)
    }
}
