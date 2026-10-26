import SwiftUI
import NetworkExtension

@main struct XPNApp: App {
    @StateObject private var model = VPNModel()
    var body: some Scene {
        WindowGroup {
            VStack(alignment: .leading, spacing: 20) {
                Text("XPN").font(.largeTitle.bold())
                Text("A private way through.").foregroundStyle(.secondary)
                Text("Paste an invitation link or profile JSON").font(.caption)
                TextEditor(text: $model.invitation).frame(minHeight: 70, maxHeight: 110).border(.secondary.opacity(0.3))
                    .accessibilityLabel("Invitation link or profile JSON")
                HStack {
                    Button("Scan QR") { model.scanning = true }.disabled(model.busy)
                    Button("Add connection") { model.enroll() }.disabled(model.busy)
                    Button("Import JSON") { model.importing = true }.disabled(model.busy)
                }
                Toggle("TLS encryption (always on)", isOn: .constant(true)).disabled(true)
                Toggle("Additional encryption (ChaCha20-Poly1305)", isOn: $model.innerEncryption).disabled(model.requiresHybrid || model.busy)
                Toggle("Require post-quantum key exchange (ML-KEM)", isOn: $model.requirePQ).disabled(model.requiresHybrid || model.busy)
                Text("Encryption changes apply when you reconnect.").font(.caption).foregroundStyle(.secondary)
                if model.requiresHybrid {
                    Text("This device's server policy requires both additional encryption and ML-KEM.").font(.caption)
                } else if !model.innerEncryption {
                    Text("TLS protects packets as far as nginx. Device authentication remains required.").font(.caption)
                }
                Toggle("Use a custom split tunnel", isOn: $model.customSplit)
                if model.customSplit { TextField("10.20.0.0/16, 192.168.50.0/24", text: $model.subnets) }
                HStack {
                    Button("Connect") { model.connect() }.disabled(model.busy)
                    Button("Disconnect") { model.disconnect() }
                }
                Text(model.status).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
                Text("Each device needs its own invitation. Full tunnel carries Internet IPv4 and blocks Internet IPv6.").font(.caption)
            }.padding(28).frame(minWidth: 340, idealWidth: 520)
                .sheet(isPresented: $model.scanning) { QRScanner { model.invitation = $0; model.scanning = false; model.enroll() } }
                .fileImporter(isPresented: $model.importing, allowedContentTypes: [.json]) { result in
                    do {
                        let url = try result.get()
                        guard url.startAccessingSecurityScopedResource() else { throw ProfileStore.failure("Cannot read selected profile") }
                        defer { url.stopAccessingSecurityScopedResource() }
                        let text = try String(contentsOf: url, encoding: .utf8)
                        guard text.utf8.count <= 8192 else { throw ProfileStore.failure("Profile too large") }
                        try model.importProfile(text)
                    } catch { model.status = error.localizedDescription }
                }
        }
    }
}

@MainActor final class VPNModel: ObservableObject {
    @Published var invitation = ""
    @Published var status = "Scan a QR, paste an invitation link or profile JSON, or import a JSON file."
    @Published var scanning = false
    @Published var importing = false
    @Published var busy = false
    @Published var customSplit = false
    @Published var subnets = ""
    @Published var innerEncryption = true
    @Published var requirePQ = false
    @Published var requiresHybrid = false
    private var deviceID = ""
    private var manager: NETunnelProviderManager?
    private var observer: NSObjectProtocol?
    init() {
        if let path = Bundle.main.path(forResource: "cacert", ofType: "pem") { _ = path.withCString { xpn_set_ca_file($0) } }
        _ = xpn_global_init()
        if let text = try? ProfileStore.load() { loadEncryptionPreferences(text) }
        observer = NotificationCenter.default.addObserver(forName: .NEVPNStatusDidChange, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in
                guard let self, let state = self.manager?.connection.status else { return }
                switch state {
                case .connected: self.status = "Connected"
                case .connecting, .reasserting: self.status = "Connecting…"
                case .disconnecting: self.status = "Disconnecting…"
                default: self.status = "Disconnected"
                }
            }
        }
    }
    func enroll() {
        guard !busy else { return }
        busy = true
        let rawInput = invitation
        Task {
            do {
                let input = try ConnectionInput.parse(rawInput)
                let text = try await input.profileText { uri in
                    try await Task.detached {
                        var error = [CChar](repeating: 0, count: 256)
                        guard let output = uri.withCString({ xpn_enroll($0, &error, error.count) }) else {
                            throw ProfileStore.failure(String(cString: error))
                        }
                        defer { xpn_free(output) }
                        return String(cString: output)
                    }.value
                }
                try importProfile(text)
                if case .invitation = input { status = "Device enrolled. Ready to connect." }
            } catch { status = error.localizedDescription }
            busy = false
        }
    }
    func importProfile(_ text: String) throws {
        try ProfileStore.save(text)
        loadEncryptionPreferences(text)
        invitation = ""
        status = "Profile imported. Ready to connect."
    }
    private func loadEncryptionPreferences(_ text: String) {
        guard let profile = try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any],
              let id = profile["id"] as? String else { return }
        deviceID = id
        requiresHybrid = profile["mode"] as? String == "hybrid"
        innerEncryption = requiresHybrid || (UserDefaults.standard.object(forKey: "xpn.inner." + id) as? Bool ?? true)
        requirePQ = requiresHybrid || UserDefaults.standard.bool(forKey: "xpn.pq." + id)
    }
    func connect() {
        guard !busy else { return }
        busy = true
        Task {
            do {
                let text = try ProfileStore.load(allowLegacyMigration: true)
                guard text.withCString({ xpn_validate_profile($0) }) == 0,
                      var profile = try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else { throw ProfileStore.failure("Invalid XPN profile") }
                if deviceID != profile["id"] as? String { loadEncryptionPreferences(text) }
                if customSplit {
                    let routes = subnets.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
                    guard !routes.isEmpty else { throw ProfileStore.failure("Enter at least one IPv4 subnet") }
                    profile["fullTunnel"] = false; profile["routes"] = routes
                }
                // The extension applies per-connection routing overrides. The PSK stays in Keychain.
                status = "Resolving VPN server…"
                let endpoint = profile["endpoint"] as! String
                let serverAddress = try await Task.detached { try EndpointResolver.resolve(endpoint) }.value
                let managers = try await NETunnelProviderManager.loadAllFromPreferences()
                let bundle = Bundle.main.bundleIdentifier! + ".tunnel"
                let manager = managers.first { ($0.protocolConfiguration as? NETunnelProviderProtocol)?.providerBundleIdentifier == bundle } ?? NETunnelProviderManager()
                let configuration = NETunnelProviderProtocol()
                configuration.providerBundleIdentifier = bundle
                configuration.serverAddress = serverAddress
                configuration.providerConfiguration = ["fullTunnel": profile["fullTunnel"]!, "routes": profile["routes"]!, "resolvedServerAddress": serverAddress,
                    "innerEncryption": innerEncryption, "requirePQ": requirePQ]
                UserDefaults.standard.set(innerEncryption, forKey: "xpn.inner." + deviceID)
                UserDefaults.standard.set(requirePQ, forKey: "xpn.pq." + deviceID)
                configuration.includeAllNetworks = profile["fullTunnel"] as? Bool ?? false
                // LAN access is always available, including in full-tunnel mode.
                configuration.excludeLocalNetworks = true
                // Saving requests permission to modify system VPN settings.
                // An ordinary reconnect must reuse the already approved entry.
                if !manager.isEnabled || manager.localizedDescription != "XPN"
                    || !TunnelPreferences.matches(manager.protocolConfiguration, configuration) {
                    manager.protocolConfiguration = configuration
                    manager.localizedDescription = "XPN"
                    manager.isEnabled = true
                    try await manager.saveToPreferences()
                    try await manager.loadFromPreferences()
                }
                self.manager = manager
                try manager.connection.startVPNTunnel()
                status = "Connecting…"
            } catch { status = error.localizedDescription }
            busy = false
        }
    }
    func disconnect() { manager?.connection.stopVPNTunnel() }
}
