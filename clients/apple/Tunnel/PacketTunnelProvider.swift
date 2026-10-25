import Foundation
import NetworkExtension

final class PacketTunnelProvider: NEPacketTunnelProvider {
    private var native: OpaquePointer?
    private let service = DispatchQueue(label: "xpn.native", qos: .userInitiated)
    private let lock = NSLock()
    private var completion: ((Error?) -> Void)?
    private var profile: [String: Any] = [:]
    private var stopRequested = false
    private var stopping: Bool {
        get { lock.lock(); defer { lock.unlock() }; return stopRequested }
        set { lock.lock(); stopRequested = newValue; lock.unlock() }
    }

    override func startTunnel(options: [String: NSObject]?, completionHandler: @escaping (Error?) -> Void) {
        completion = completionHandler
        stopping = false
        do {
            let stored = try ProfileStore.load()
            guard stored.withCString({ xpn_validate_profile($0) }) == 0,
                  let decoded = try JSONSerialization.jsonObject(with: Data(stored.utf8)) as? [String: Any] else { throw ProfileStore.failure("Invalid XPN profile") }
            profile = decoded
            let configuration = (protocolConfiguration as? NETunnelProviderProtocol)?.providerConfiguration ?? [:]
            if let full = configuration["fullTunnel"] { profile["fullTunnel"] = full }
            if let routes = configuration["routes"] { profile["routes"] = routes }
            let text = String(data: try JSONSerialization.data(withJSONObject: profile), encoding: .utf8)!
            if let path = Bundle.main.path(forResource: "cacert", ofType: "pem") { _ = path.withCString { xpn_set_ca_file($0) } }
            _ = xpn_global_init()
            var callbacks = xpn_callbacks()
            callbacks.opaque = Unmanaged.passUnretained(self).toOpaque()
            callbacks.packet = { opaque, bytes, size in
                guard let opaque, let bytes else { return }
                let owner = Unmanaged<PacketTunnelProvider>.fromOpaque(opaque).takeUnretainedValue()
                owner.packetFlow.writePackets([Data(bytes: bytes, count: size)], withProtocols: [NSNumber(value: AF_INET)])
            }
            callbacks.state = { opaque, ready, _ in
                guard let opaque else { return }
                let owner = Unmanaged<PacketTunnelProvider>.fromOpaque(opaque).takeUnretainedValue()
                DispatchQueue.main.async {
                    if ready != 0 { owner.configureNetwork() }
                    else if !owner.stopping { owner.fail(ProfileStore.failure("Tunnel closed. Reconnect to establish fresh session keys.")) }
                }
            }
            guard let instance = text.withCString({ xpn_client_new($0, callbacks) }) else { throw ProfileStore.failure("Invalid profile, unsupported crypto mode, or missing native dependencies") }
            lock.lock(); native = instance; lock.unlock()
            service.async { [self] in
                let result = xpn_run(instance)
                lock.lock(); native = nil; lock.unlock()
                xpn_destroy(instance)
                if result != 0 { DispatchQueue.main.async { [self] in if !stopping { fail(ProfileStore.failure("Native transport failed")) } } }
            }
        } catch { fail(error) }
    }
    private func configureNetwork() {
        guard !stopping else { return }
        do {
            let full = profile["fullTunnel"] as? Bool ?? false
            let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: "10.77.0.1")
            settings.mtu = 1400
            let ipv4 = NEIPv4Settings(addresses: [profile["address"] as! String], subnetMasks: ["255.255.255.255"])
            ipv4.includedRoutes = full ? [.default()] : try (profile["routes"] as? [String] ?? []).map { route in
                let fields = route.split(separator: "/")
                guard fields.count == 2, let bits = Int(fields[1]), (0...32).contains(bits) else { throw ProfileStore.failure("Invalid IPv4 subnet") }
                let mask: UInt32 = bits == 0 ? 0 : UInt32.max << (32 - bits)
                let octets = (0..<4).map { String((mask >> (24 - $0 * 8)) & 255) }.joined(separator: ".")
                return NEIPv4Route(destinationAddress: String(fields[0]), subnetMask: octets)
            }
            settings.ipv4Settings = ipv4
            if full {
                // Route IPv6 into this IPv4-only provider and discard it, preventing bypass.
                let ipv6 = NEIPv6Settings(addresses: ["fd77::2"], networkPrefixLengths: [128])
                ipv6.includedRoutes = [.default()]; settings.ipv6Settings = ipv6
                let dns = NEDNSSettings(servers: profile["dns"] as? [String] ?? ["1.1.1.1"])
                dns.matchDomains = [""]; settings.dnsSettings = dns
            }
            setTunnelNetworkSettings(settings) { [self] error in
                DispatchQueue.main.async {
                    guard !self.stopping else { return }
                    if let error { self.fail(error); return }
                    let handler = self.completion; self.completion = nil; handler?(nil); self.readPackets()
                }
            }
        } catch { fail(error) }
    }
    private func readPackets() {
        guard !stopping else { return }
        packetFlow.readPackets { [weak self] packets, protocols in
            guard let self, !self.stopping else { return }
            self.lock.lock()
            if let native = self.native {
                for (packet, family) in zip(packets, protocols) where family.int32Value == AF_INET {
                    packet.withUnsafeBytes { buffer in _ = xpn_send(native, buffer.bindMemory(to: UInt8.self).baseAddress, buffer.count) }
                }
            }
            self.lock.unlock(); self.readPackets()
        }
    }
    private func fail(_ error: Error) {
        stopping = true
        let handler = completion; completion = nil
        lock.lock(); if let native { xpn_stop(native) }; lock.unlock()
        if let handler { handler(error) } else { cancelTunnelWithError(error) }
    }
    override func stopTunnel(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) {
        stopping = true
        lock.lock(); if let native { xpn_stop(native) }; lock.unlock()
        service.async { completionHandler() }
    }
}
