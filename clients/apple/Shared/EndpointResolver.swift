import Foundation
import Darwin

enum EndpointResolver {
    // Resolve before enabling includeAllNetworks. A resolver query made while
    // bringing up that tunnel can wait for DNS traffic that the tunnel captures.
    static func resolve(_ endpoint: String) throws -> String {
        guard var host = URL(string: endpoint)?.host else { throw ProfileStore.failure("Invalid VPN endpoint") }
        if host.hasPrefix("["), host.hasSuffix("]") { host = String(host.dropFirst().dropLast()) }
        var hints = addrinfo()
        hints.ai_family = AF_UNSPEC
        hints.ai_socktype = SOCK_STREAM
        var result: UnsafeMutablePointer<addrinfo>?
        guard getaddrinfo(host, nil, &hints, &result) == 0, let first = result else {
            throw ProfileStore.failure("Cannot resolve the VPN server. Check your network and try again.")
        }
        defer { freeaddrinfo(first) }
        var addresses: [(Int32, String)] = []
        var current: UnsafeMutablePointer<addrinfo>? = first
        while let item = current {
            let entry = item.pointee
            if entry.ai_family == AF_INET || entry.ai_family == AF_INET6 {
                var buffer = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                if getnameinfo(entry.ai_addr, entry.ai_addrlen, &buffer, socklen_t(buffer.count), nil, 0, NI_NUMERICHOST) == 0 {
                    addresses.append((entry.ai_family, String(cString: buffer)))
                }
            }
            current = entry.ai_next
        }
        guard let address = addresses.first(where: { $0.0 == AF_INET }) ?? addresses.first else {
            throw ProfileStore.failure("VPN server has no reachable IP address")
        }
        return address.1
    }
}
