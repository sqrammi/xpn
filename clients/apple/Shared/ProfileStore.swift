import Foundation
import Security

enum ProfileStore {
    static var group: String { Bundle.main.object(forInfoDictionaryKey: "XPNKeychainGroup") as! String }
    static func save(_ text: String) throws {
        guard text.utf8.count <= 8192, !text.contains("\0"),
              text.withCString({ xpn_validate_profile($0) }) == 0 else { throw failure("Invalid XPN profile") }
        try ProfileKeychain(accessGroup: group).save(Data(text.utf8))
    }
    static func load(allowLegacyMigration: Bool = false) throws -> String {
        let data = try ProfileKeychain(accessGroup: group).load(allowLegacyMigration: allowLegacyMigration)
        guard let text = String(data: data, encoding: .utf8) else { throw failure("Invalid saved XPN profile") }
        return text
    }
    static func connections(allowLegacyMigration: Bool = false) throws -> SavedConnections {
        let keychain = ProfileKeychain(accessGroup: group, account: "connections")
        do {
            return try JSONDecoder().decode(SavedConnections.self, from: keychain.load())
        } catch let error as NSError where error.domain == "XPN.Keychain" && error.code == Int(errSecItemNotFound) {
            var catalog = SavedConnections()
            do {
                let text = try load(allowLegacyMigration: allowLegacyMigration)
                try catalog.importProfile(text)
                let device = catalog.connections[0].deviceID
                catalog.connections[0].innerEncryption = UserDefaults.standard.object(forKey: "xpn.inner." + device) as? Bool ?? true
                catalog.connections[0].requirePQ = UserDefaults.standard.bool(forKey: "xpn.pq." + device)
                try saveConnections(catalog)
            } catch let missing as NSError where missing.domain == "XPN.Keychain" && missing.code == Int(errSecItemNotFound) {
                // Do not persist an empty collection until explicitly edited:
                // an older macOS ACL profile may still need app-only migration.
            }
            return catalog
        }
    }
    static func saveConnections(_ catalog: SavedConnections) throws {
        try ProfileKeychain(accessGroup: group, account: "connections").save(JSONEncoder().encode(catalog))
    }
    static func loadConnection(_ id: String) throws -> String {
        // Never substitute the current selection for the ID bound to a tunnel.
        let catalog = try JSONDecoder().decode(SavedConnections.self,
            from: ProfileKeychain(accessGroup: group, account: "connections").load())
        guard let connection = catalog.connections.first(where: { $0.id == id }) else {
            throw failure("Saved connection was removed. Choose a connection in XPN.")
        }
        return connection.profile
    }
    static func failure(_ message: String) -> NSError { NSError(domain: "XPN", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
}
