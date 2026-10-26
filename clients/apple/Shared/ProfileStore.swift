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
    static func failure(_ message: String) -> NSError { NSError(domain: "XPN", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
}
