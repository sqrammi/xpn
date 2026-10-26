import Foundation

@main struct ConnectionInputTests {
    static func main() async throws {
        let profile = "{\"endpoint\":\"wss://vpn.example.com/xpn/vpn\"}"
        let parsed = try ConnectionInput.parse(" \n" + profile + "\n")
        precondition(parsed == .profile(profile))
        var requests = 0
        let resolved = try await parsed.profileText { _ in requests += 1; return "unexpected" }
        precondition(resolved == profile && requests == 0, "Pasted profiles must never redeem an invitation")
        let uri = "https://vpn.example.com/xpn/join#token=test&key=test"
        let invitation = try ConnectionInput.parse("\n" + uri + " ")
        precondition(invitation == .invitation(uri))
        let enrolled = try await invitation.profileText { received in
            requests += 1; precondition(received == uri); return profile
        }
        precondition(enrolled == profile && requests == 1)
        for invalid in ["", " \n ", "{bad JSON}", "[]", "http://vpn.example.com/xpn/join", "not a link", profile + "\0", String(repeating: "x", count: 8193)] {
            do { _ = try ConnectionInput.parse(invalid); fatalError("Invalid input accepted") }
            catch { precondition(!error.localizedDescription.isEmpty) }
        }
        print("Connection input tests passed: profiles bypass enrollment, links redeem once, invalid input rejected.")
    }
}
