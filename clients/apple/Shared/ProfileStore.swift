import Foundation
import Security

enum ProfileStore {
    static var group: String { Bundle.main.object(forInfoDictionaryKey: "XPNKeychainGroup") as! String }
    static var query: [String: Any] { [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "XPN.profile", kSecAttrAccount as String: "device", kSecAttrAccessGroup as String: group] }
    static func save(_ text: String) throws {
        guard text.withCString({ xpn_validate_profile($0) }) == 0 else { throw failure("Invalid XPN profile") }
        var values = query
        let data = Data(text.utf8)
        let result = SecItemUpdate(values as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if result == errSecItemNotFound {
            values[kSecValueData as String] = data
            values[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            guard SecItemAdd(values as CFDictionary, nil) == errSecSuccess else { throw failure("Cannot save profile to shared Keychain") }
        } else if result != errSecSuccess { throw failure("Cannot update profile") }
    }
    static func load() throws -> String {
        var values = query
        values[kSecReturnData as String] = true
        values[kSecMatchLimit as String] = kSecMatchLimitOne
        var output: CFTypeRef?
        guard SecItemCopyMatching(values as CFDictionary, &output) == errSecSuccess,
              let data = output as? Data, let text = String(data: data, encoding: .utf8) else { throw failure("Enroll this device first") }
        return text
    }
    static func failure(_ message: String) -> NSError { NSError(domain: "XPN", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
}
