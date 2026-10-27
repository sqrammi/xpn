import Foundation
import Security

@main struct ProfileKeychainTests {
    final class Store {
        let original = Data("test-device-secret".utf8)
        var modern: Data?
        var modernError: OSStatus = errSecItemNotFound
        var legacyError: OSStatus = errSecSuccess
        var writeError: OSStatus = errSecSuccess
        var legacyReads = 0
        var writes = 0
        func client() -> ProfileKeychain {
            ProfileKeychain(accessGroup: "TEAM.xpn.shared", read: { [self] query in
                if query[kSecUseDataProtectionKeychain as String] as? Bool == true {
                    precondition(query[kSecAttrAccessGroup as String] as? String == "TEAM.xpn.shared")
                    return modern.map { (errSecSuccess, $0) } ?? (modernError, nil)
                }
                legacyReads += 1
                precondition(query[kSecAttrAccessGroup as String] == nil)
                return (legacyError, legacyError == errSecSuccess ? original : nil)
            }, update: { [self] query, values in
                precondition(query[kSecUseDataProtectionKeychain as String] as? Bool == true)
                guard modern != nil else { return errSecItemNotFound }
                writes += 1
                if writeError == errSecSuccess { modern = values[kSecValueData as String] as? Data }
                return writeError
            }, add: { [self] values in
                precondition(values[kSecUseDataProtectionKeychain as String] as? Bool == true)
                precondition(values[kSecAttrAccessGroup as String] as? String == "TEAM.xpn.shared")
                precondition(values[kSecAttrAccessible as String] as? String == kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly as String)
                writes += 1
                if writeError == errSecSuccess { modern = values[kSecValueData as String] as? Data }
                return writeError
            })
        }
    }
    static func rejects(_ status: OSStatus, _ action: () throws -> Void) {
        do { try action(); fatalError("Expected Keychain failure") }
        catch { precondition((error as NSError).code == Int(status)) }
    }
    static func main() throws {
        let store = Store()
        // Extensions cannot prompt through a legacy fallback.
        rejects(errSecItemNotFound) { _ = try store.client().load() }
        precondition(store.legacyReads == 0 && store.writes == 0)
        let migrated = try store.client().load(allowLegacyMigration: true)
        precondition(migrated == store.original && store.modern == store.original)
        precondition(store.legacyReads == 1 && store.writes == 1)
        for _ in 0..<3 {
            let reconnect = try store.client().load()
            precondition(reconnect == store.original)
        }
        precondition(store.legacyReads == 1 && store.writes == 1)
        let replacement = Data("rotated-test-device-secret".utf8)
        try store.client().save(replacement)
        let updated = try store.client().load()
        precondition(updated == replacement && store.legacyReads == 1)
        for status in [errSecAuthFailed, errSecInteractionNotAllowed, errSecMissingEntitlement] {
            let denied = Store(); denied.modernError = status
            rejects(status) { _ = try denied.client().load(allowLegacyMigration: true) }
            precondition(denied.legacyReads == 0 && denied.writes == 0)
        }
        let cancelled = Store(); cancelled.legacyError = errSecUserCanceled
        rejects(errSecUserCanceled) { _ = try cancelled.client().load(allowLegacyMigration: true) }
        precondition(cancelled.modern == nil && cancelled.writes == 0)
        let failed = Store(); failed.writeError = errSecMissingEntitlement
        rejects(errSecMissingEntitlement) { _ = try failed.client().load(allowLegacyMigration: true) }
        precondition(failed.modern == nil)
        var collectionReads = 0
        let collection = ProfileKeychain(accessGroup: "TEAM.xpn.shared", account: "connections", read: { query in
            collectionReads += 1
            precondition(query[kSecAttrAccount as String] as? String == "connections")
            precondition(query[kSecUseDataProtectionKeychain as String] as? Bool == true)
            return (errSecItemNotFound, nil)
        })
        rejects(errSecItemNotFound) { _ = try collection.load(allowLegacyMigration: true) }
        precondition(collectionReads == 1) // Only the old device item may use legacy migration.
        print("Keychain migration tests passed: app-only migration, shared protected storage, reconnects without legacy access, failure and cancellation handling.")
    }
}
