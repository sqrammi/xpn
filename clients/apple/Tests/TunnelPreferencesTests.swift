import Foundation
import NetworkExtension

@main struct TunnelPreferencesTests {
    static func configuration() -> NETunnelProviderProtocol {
        let result = NETunnelProviderProtocol()
        result.providerBundleIdentifier = "com.example.xpn.tunnel"
        result.serverAddress = "192.0.2.1"
        result.includeAllNetworks = true
        result.excludeLocalNetworks = true
        result.providerConfiguration = ["connectionID": "server-one", "resolvedServerAddress": "192.0.2.1",
            "fullTunnel": true, "routes": ["10.20.0.0/16"],
            "innerEncryption": true, "requirePQ": false]
        return result
    }
    static func main() {
        let desired = configuration()
        // Property-list round trips model objects returned by macOS, including
        // bridged NSNumber values instead of native Swift Bool values.
        let restored = configuration()
        let data = try! PropertyListSerialization.data(fromPropertyList: desired.providerConfiguration!, format: .binary, options: 0)
        restored.providerConfiguration = try! PropertyListSerialization.propertyList(from: data, options: [], format: nil) as? [String: Any]
        precondition(restored !== desired && TunnelPreferences.matches(restored, desired))
        precondition(!TunnelPreferences.matches(nil, desired))
        precondition(!TunnelPreferences.matches(NEVPNProtocolIKEv2(), desired))
        let mutations: [(NETunnelProviderProtocol) -> Void] = [
            { $0.providerBundleIdentifier = "another.tunnel" },
            { $0.serverAddress = "192.0.2.2" },
            { $0.includeAllNetworks = false },
            { $0.excludeLocalNetworks = false },
            { $0.providerConfiguration?["resolvedServerAddress"] = "192.0.2.2" },
            { $0.providerConfiguration?["fullTunnel"] = false },
            { $0.providerConfiguration?["connectionID"] = "server-two" },
            { $0.providerConfiguration?["routes"] = ["10.30.0.0/16"] },
            { $0.providerConfiguration?["innerEncryption"] = false },
            { $0.providerConfiguration?["requirePQ"] = true }
        ]
        for mutate in mutations {
            let changed = configuration(); mutate(changed)
            precondition(!TunnelPreferences.matches(changed, desired))
        }
        // An existing full-tunnel configuration without the LAN exception must
        // be saved once to apply the mandatory local-network exception.
        let previous = configuration(); previous.excludeLocalNetworks = false
        precondition(!TunnelPreferences.matches(previous, desired))
        previous.excludeLocalNetworks = true
        precondition(TunnelPreferences.matches(previous, desired))
        print("VPN preferences tests passed: unchanged reconnects reuse preferences; endpoint, LAN access, route and encryption changes require saving.")
    }
}
