import Foundation

struct SavedConnection: Codable, Identifiable, Sendable {
    var id: String
    var name: String
    var profile: String
    var innerEncryption = true
    var requirePQ = false
    var customSplit = false
    var subnets = ""

    var fields: [String: Any] {
        (try? JSONSerialization.jsonObject(with: Data(profile.utf8))) as? [String: Any] ?? [:]
    }
    var endpoint: String { fields["endpoint"] as? String ?? "" }
    var deviceID: String { fields["id"] as? String ?? "" }
    var requiresHybrid: Bool { fields["mode"] as? String == "hybrid" }
}

struct SavedConnections: Codable, Sendable {
    var connections: [SavedConnection] = []
    var selectedID: String?

    // Reimporting a rotated profile updates only that server/device, retaining
    // its local name and preferences. Device IDs from different servers coexist.
    mutating func importProfile(_ text: String) throws {
        guard let fields = try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any],
              let device = fields["id"] as? String, !device.isEmpty,
              let endpoint = fields["endpoint"] as? String,
              let host = URLComponents(string: endpoint)?.host, !host.isEmpty else {
            throw NSError(domain: "XPN", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid XPN profile"])
        }
        if let index = connections.firstIndex(where: { $0.deviceID == device && $0.endpoint == endpoint }) {
            connections[index].profile = text
            selectedID = connections[index].id
        } else {
            let connection = SavedConnection(id: UUID().uuidString, name: host, profile: text)
            connections.append(connection)
            selectedID = connection.id
        }
    }
    mutating func remove(_ id: String) {
        connections.removeAll { $0.id == id }
        if selectedID == id { selectedID = connections.first?.id }
    }
}
