import Foundation
import Security

struct ProfileKeychain {
    var accessGroup: String
    var account = "device"
    var read: ([String: Any]) -> (OSStatus, Data?) = { query in
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        return (status, result as? Data)
    }
    var update: ([String: Any], [String: Any]) -> OSStatus = {
        SecItemUpdate($0 as CFDictionary, $1 as CFDictionary)
    }
    var add: ([String: Any]) -> OSStatus = { SecItemAdd($0 as CFDictionary, nil) }

    var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: "XPN.profile", kSecAttrAccount as String: account,
         kSecAttrAccessGroup as String: accessGroup,
         kSecUseDataProtectionKeychain as String: true]
    }
    func save(_ data: Data) throws {
        let status = update(query, [kSecValueData as String: data])
        if status == errSecItemNotFound {
            var values = query
            values[kSecValueData as String] = data
            values[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            let added = add(values)
            guard added == errSecSuccess else { throw failure(added) }
        } else if status != errSecSuccess { throw failure(status) }
    }
    func load(allowLegacyMigration: Bool = false) throws -> Data {
        var values = query
        values[kSecReturnData as String] = true
        values[kSecMatchLimit as String] = kSecMatchLimitOne
        let (status, data) = read(values)
        if status == errSecSuccess {
            guard let data else { throw failure(errSecDecode) }
            return data
        }
        #if os(macOS)
        if status == errSecItemNotFound && allowLegacyMigration && account == "device" {
            // Only the containing app migrates. The extension never falls back
            // to legacy ACL prompts. Preserve the old item as a recovery copy.
            values[kSecUseDataProtectionKeychain as String] = false
            values.removeValue(forKey: kSecAttrAccessGroup as String)
            let (legacyStatus, legacyData) = read(values)
            guard legacyStatus == errSecSuccess else { throw failure(legacyStatus) }
            guard let legacyData else { throw failure(errSecDecode) }
            try save(legacyData)
            return legacyData
        }
        #endif
        throw failure(status)
    }
    private func failure(_ status: OSStatus) -> NSError {
        let message = status == errSecItemNotFound
            ? "Open XPN and connect to migrate your saved profile, or enroll this device first."
            : "Cannot access the XPN Keychain profile (status \(status))."
        return NSError(domain: "XPN.Keychain", code: Int(status), userInfo: [NSLocalizedDescriptionKey: message])
    }
}
