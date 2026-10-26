import Foundation

enum ConnectionInput: Equatable {
    case invitation(String)
    case profile(String)

    static func parse(_ input: String) throws -> ConnectionInput {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        func failure(_ message: String) -> NSError {
            NSError(domain: "XPN", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
        }
        guard !text.isEmpty else {
            throw failure("Paste an invitation link or profile JSON, or choose Import JSON.")
        }
        guard text.utf8.count <= 8192, !text.contains("\0") else {
            throw failure("Connection input is too large or contains invalid characters.")
        }
        if text.hasPrefix("{") || text.hasPrefix("[") {
            guard let object = try? JSONSerialization.jsonObject(with: Data(text.utf8)),
                  object is [String: Any] else {
                throw failure("Invalid profile JSON. Import the downloaded xpn-profile.json file.")
            }
            // ProfileStore applies the native schema validation before saving.
            // Downloaded profiles already redeemed the one-use invitation.
            return .profile(text)
        }
        guard text.hasPrefix("https://") else {
            throw failure("Expected an HTTPS invitation link or profile JSON. You can also choose Import JSON.")
        }
        return .invitation(text)
    }

    func profileText(enroll: (String) async throws -> String) async throws -> String {
        switch self {
        case .profile(let text): return text
        case .invitation(let uri): return try await enroll(uri)
        }
    }
}
