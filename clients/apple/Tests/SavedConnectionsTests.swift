import Foundation

@main struct SavedConnectionsTests {
    static func profile(_ host: String, key: String = "synthetic-key") -> String {
        "{\"id\":\"same-device-id\",\"endpoint\":\"wss://\(host)/xpn/vpn\",\"psk\":\"\(key)\",\"mode\":\"psk\"}"
    }
    static func main() throws {
        var catalog = SavedConnections()
        try catalog.importProfile(profile("one.example"))
        let first = catalog.selectedID!
        catalog.connections[0].name = "Office"
        catalog.connections[0].innerEncryption = false
        catalog.connections[0].customSplit = true
        catalog.connections[0].subnets = "10.20.0.0/16"
        try catalog.importProfile(profile("two.example"))
        let second = catalog.selectedID!
        precondition(first != second && catalog.connections.count == 2)
        precondition(catalog.connections[1].innerEncryption && !catalog.connections[1].customSplit)
        try catalog.importProfile(profile("one.example", key: "rotated-key"))
        precondition(catalog.connections.count == 2 && catalog.selectedID == first)
        precondition(catalog.connections[0].name == "Office")
        precondition(!catalog.connections[0].innerEncryption && catalog.connections[0].customSplit)
        precondition(catalog.connections[0].subnets == "10.20.0.0/16")
        precondition(catalog.connections[0].profile.contains("rotated-key"))
        precondition(!catalog.connections[1].profile.contains("rotated-key"))
        let restored = try JSONDecoder().decode(SavedConnections.self, from: JSONEncoder().encode(catalog))
        precondition(restored.selectedID == first && restored.connections[0].profile == catalog.connections[0].profile)
        catalog.remove(second)
        precondition(catalog.selectedID == first && catalog.connections.count == 1)
        catalog.remove(first)
        precondition(catalog.selectedID == nil && catalog.connections.isEmpty)
        try catalog.importProfile(profile("one.example"))
        try catalog.importProfile(profile("two.example"))
        catalog.remove(catalog.selectedID!)
        precondition(catalog.selectedID == catalog.connections.first?.id)
        do { try catalog.importProfile("{}"); fatalError("Invalid profile accepted") } catch {}
        precondition(catalog.connections.count == 1)
        print("Saved connections tests passed: server isolation, rotation, preferences, selection, persistence and removal.")
    }
}
