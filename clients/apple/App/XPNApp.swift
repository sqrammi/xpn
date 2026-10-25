import SwiftUI
import NetworkExtension

@main struct XPNApp: App {
    @StateObject private var model = VPNModel()
    var body: some Scene {
        WindowGroup {
            VStack(alignment: .leading, spacing: 20) {
                Text("XPN").font(.largeTitle.bold())
                Text("A private way through.").foregroundStyle(.secondary)
                TextEditor(text: $model.invitation).frame(minHeight: 70, maxHeight: 110).border(.secondary.opacity(0.3))
                HStack {
                    Button("Scan QR") { model.scanning = true }
                    Button("Enroll invitation") { model.enroll() }.disabled(model.busy)
                    Button("Import JSON") { model.importing = true }
                }
                Toggle("Use a custom split tunnel", isOn: $model.customSplit)
                if model.customSplit { TextField("10.20.0.0/16, 192.168.50.0/24", text: $model.subnets) }
                HStack {
                    Button("Connect") { model.connect() }.disabled(model.busy)
                    Button("Disconnect") { model.disconnect() }
                }
                Text(model.status).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
                Text("Each device needs its own invitation. Full tunnel carries IPv4 and blocks IPv6.").font(.caption)
            }.padding(28).frame(minWidth: 340, idealWidth: 520)
                .sheet(isPresented: $model.scanning) { QRScanner { model.invitation = $0; model.scanning = false; model.enroll() } }
                .fileImporter(isPresented: $model.importing, allowedContentTypes: [.json]) { result in
                    do {
                        let url = try result.get()
                        guard url.startAccessingSecurityScopedResource() else { throw ProfileStore.failure("Cannot read selected profile") }
                        defer { url.stopAccessingSecurityScopedResource() }
                        let text = try String(contentsOf: url, encoding: .utf8)
                        guard text.utf8.count <= 8192 else { throw ProfileStore.failure("Profile too large") }
                        try ProfileStore.save(text); model.status = "Profile imported"
                    } catch { model.status = error.localizedDescription }
                }
        }
    }
}

@MainActor final class VPNModel: ObservableObject {
    @Published var invitation = ""
    @Published var status = "Scan a one-use invitation to get started."
    @Published var scanning = false
    @Published var importing = false
    @Published var busy = false
    @Published var customSplit = false
    @Published var subnets = ""
    private var manager: NETunnelProviderManager?
    private var observer: NSObjectProtocol?
    init() {
        if let path = Bundle.main.path(forResource: "cacert", ofType: "pem") { _ = path.withCString { xpn_set_ca_file($0) } }
        _ = xpn_global_init()
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
        let uri = invitation
        Task {
            do {
                let text = try await Task.detached {
                    var error = [CChar](repeating: 0, count: 256)
                    guard let output = uri.withCString({ xpn_enroll($0, &error, error.count) }) else {
                        throw ProfileStore.failure(String(cString: error))
                    }
                    defer { xpn_free(output) }
                    return String(cString: output)
                }.value
                try ProfileStore.save(text); invitation = ""; status = "Device enrolled. Ready to connect."
            } catch { status = error.localizedDescription }
            busy = false
        }
    }
    func connect() {
        guard !busy else { return }
        busy = true
        Task {
            do {
                let text = try ProfileStore.load()
                guard text.withCString({ xpn_validate_profile($0) }) == 0,
                      var profile = try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else { throw ProfileStore.failure("Invalid XPN profile") }
                if customSplit {
                    let routes = subnets.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
                    guard !routes.isEmpty else { throw ProfileStore.failure("Enter at least one IPv4 subnet") }
                    profile["fullTunnel"] = false; profile["routes"] = routes
                }
                // The extension applies per-connection routing overrides. The PSK stays in Keychain.
                let managers = try await NETunnelProviderManager.loadAllFromPreferences()
                let bundle = Bundle.main.bundleIdentifier! + ".tunnel"
                let manager = managers.first { ($0.protocolConfiguration as? NETunnelProviderProtocol)?.providerBundleIdentifier == bundle } ?? NETunnelProviderManager()
                let configuration = NETunnelProviderProtocol()
                configuration.providerBundleIdentifier = bundle
                configuration.serverAddress = URL(string: profile["endpoint"] as! String)?.host
                configuration.providerConfiguration = ["fullTunnel": profile["fullTunnel"]!, "routes": profile["routes"]!]
                configuration.includeAllNetworks = profile["fullTunnel"] as? Bool ?? false
                manager.protocolConfiguration = configuration
                manager.localizedDescription = "XPN"
                manager.isEnabled = true
                try await manager.saveToPreferences(); try await manager.loadFromPreferences()
                self.manager = manager
                try manager.connection.startVPNTunnel()
                status = "Connecting…"
            } catch { status = error.localizedDescription }
            busy = false
        }
    }
    func disconnect() { manager?.connection.stopVPNTunnel() }
}
