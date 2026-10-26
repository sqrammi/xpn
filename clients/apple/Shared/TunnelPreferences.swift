import Foundation
import NetworkExtension

enum TunnelPreferences {
    // Compare persisted values, not object identity: loadAllFromPreferences
    // returns a fresh protocol object on each connection attempt.
    static func matches(_ current: NEVPNProtocol?, _ desired: NETunnelProviderProtocol) -> Bool {
        guard let current = current as? NETunnelProviderProtocol else { return false }
        return current.providerBundleIdentifier == desired.providerBundleIdentifier
            && current.serverAddress == desired.serverAddress
            && current.includeAllNetworks == desired.includeAllNetworks
            && current.excludeLocalNetworks == desired.excludeLocalNetworks
            && NSDictionary(dictionary: current.providerConfiguration ?? [:])
                .isEqual(to: desired.providerConfiguration ?? [:])
    }
}
