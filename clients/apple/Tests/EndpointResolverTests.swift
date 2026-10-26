import Foundation

// Only the error factory is needed; these tests never read a user's Keychain.
enum ProfileStore {
    static func failure(_ message: String) -> NSError {
        NSError(domain: "XPN", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}

@main struct EndpointResolverTests {
    static func main() throws {
        let ipv4 = try EndpointResolver.resolve("wss://127.0.0.1:8443/xpn/vpn")
        precondition(ipv4 == "127.0.0.1")
        let ipv6 = try EndpointResolver.resolve("wss://[::1]:8443/xpn/vpn")
        precondition(ipv6 == "::1")
        do { _ = try EndpointResolver.resolve("no endpoint"); fatalError("Invalid endpoint accepted") }
        catch { precondition(!error.localizedDescription.isEmpty) }
        print("Endpoint resolver tests passed: IPv4, IPv6 and invalid endpoint.")
    }
}
