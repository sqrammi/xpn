import SwiftUI
import NetworkExtension
import OSLog

@main struct XPNApp: App {
    @StateObject private var model = VPNModel()
    @AppStorage("xpn.privacyDisclosure.v1") private var hasSeenPrivacy = false
    @State private var showingPrivacy = false
    var body: some Scene {
        WindowGroup {
            ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("XPN").font(.largeTitle.bold())
                Text("A private way through.").foregroundStyle(.secondary)
                if model.loading { ProgressView("Loading saved connections…") }
                if let error = model.lastError {
                    Text(error).font(.callout).foregroundStyle(.red).textSelection(.enabled)
                }
                if !model.connections.isEmpty {
                    Picker("Server", selection: Binding(get: { model.selectedID }, set: { model.select($0) })) {
                        ForEach(model.connections) { connection in
                            Text("\(connection.name) — \(connection.endpoint)").tag(connection.id)
                        }
                    }.pickerStyle(.menu).disabled(model.busy)
                    HStack {
                        TextField("Connection name", text: $model.connectionName)
                        Button("Rename") { model.rename() }
                        Button("Remove…", role: .destructive) { model.removing = true }
                    }.disabled(model.busy)
                }
                Text("Add another server: paste an invitation link or profile JSON").font(.caption)
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
                Toggle("Use a custom split tunnel", isOn: $model.customSplit).disabled(model.busy)
                if model.customSplit { TextField("10.20.0.0/16, 192.168.50.0/24", text: $model.subnets).disabled(model.busy) }
                HStack {
                    Button("Connect") { model.connect() }.disabled(model.busy || model.connecting)
                    Button("Disconnect") { model.disconnect() }.disabled(model.busy)
                }
                Text(model.status).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
                Text("Each device needs its own invitation. Full tunnel carries Internet IPv4 and blocks Internet IPv6.").font(.caption)
                Button("Privacy and support") { showingPrivacy = true }
            }.disabled(!hasSeenPrivacy)
                .sheet(isPresented: Binding(get: { !hasSeenPrivacy || showingPrivacy }, set: { showingPrivacy = $0 })) {
                    PrivacyDisclosure { hasSeenPrivacy = true; showingPrivacy = false }
                }
                .task { await model.load() }.padding(28).frame(minWidth: 340, idealWidth: 520)
                .confirmationDialog("Remove this saved connection?", isPresented: $model.removing) {
                    Button("Remove connection", role: .destructive) { model.remove() }
                } message: { Text("This removes it from this device. It does not revoke the account on the server. Disconnect it first if it is active.") }
                .sheet(isPresented: $model.scanning) { QRScanner { model.invitation = $0; model.scanning = false; model.enroll() } }
                .fileImporter(isPresented: $model.importing, allowedContentTypes: [.json]) { result in
                    do {
                        let url = try result.get()
                        guard url.startAccessingSecurityScopedResource() else { throw ProfileStore.failure("Cannot read selected profile") }
                        defer { url.stopAccessingSecurityScopedResource() }
                        let text = try String(contentsOf: url, encoding: .utf8)
                        guard text.utf8.count <= 8192 else { throw ProfileStore.failure("Profile too large") }
                        model.importFile(text)
                    } catch { model.status = error.localizedDescription }
                }
            }
        }
    }
}

@MainActor final class VPNModel: ObservableObject {
    @Published var invitation = ""
    @Published var status = "Scan a QR, paste an invitation link or profile JSON, or import a JSON file."
    @Published var scanning = false
    @Published var importing = false
    @Published var busy = true
    @Published var loading = true
    @Published var connecting = false
    @Published var lastError: String?
    @Published var customSplit = false { didSet { persistPreferences() } }
    @Published var subnets = "" { didSet { persistPreferences() } }
    @Published var innerEncryption = true { didSet { persistPreferences() } }
    @Published var requirePQ = false { didSet { persistPreferences() } }
    @Published var requiresHybrid = false
    @Published var connections: [SavedConnection] = []
    @Published var selectedID = ""
    @Published var connectionName = ""
    @Published var removing = false
    private let work = BlockingWork()
    private let logger = Logger(subsystem: "com.jeffhansen.xpn", category: "AppStartup")
    private var didLoad = false
    private var pendingAttempt = false
    private var intentionalStop = false
    private var attemptID = UUID()
    private var catalog = SavedConnections()
    private var loadingPreferences = false
    private var manager: NETunnelProviderManager?
    private var observer: NSObjectProtocol?
    init() {
        // No disk, Keychain or native-library work before SwiftUI's first frame.
        observer = NotificationCenter.default.addObserver(forName: .NEVPNStatusDidChange, object: nil, queue: .main) { [weak self] notification in
            guard let connection = notification.object as? NEVPNConnection else { return }
            Task { @MainActor in
                guard let self, connection === self.manager?.connection else { return }
                self.updateStatus()
            }
        }
    }
    func load() async {
        guard !didLoad else { return }
        didLoad = true
        let began = Date()
        logger.info("Screen appeared; loading saved connections")
        defer { busy = false; loading = false }
        do {
            apply(try await work.run { try ProfileStore.connections() })
            logger.info("Keychain loaded after \(Date().timeIntervalSince(began), privacy: .public) seconds")
            let managers = try await NETunnelProviderManager.loadAllFromPreferences()
            let owned = managers.filter { ($0.protocolConfiguration as? NETunnelProviderProtocol)?.providerBundleIdentifier == Bundle.main.bundleIdentifier! + ".tunnel" }
            self.manager = owned.first { Self.active($0) } ?? owned.first {
                ($0.protocolConfiguration as? NETunnelProviderProtocol)?.providerConfiguration?["connectionID"] as? String == selectedID
            } ?? owned.first
            if manager?.connection.status == .connecting || manager?.connection.status == .reasserting { pendingAttempt = true }
            updateStatus()
            if manager?.connection.status == .disconnected { fetchConnectionError(fallback: false) }
            logger.info("Startup ready after \(Date().timeIntervalSince(began), privacy: .public) seconds")
        } catch { report(error) }
    }
    private func report(_ error: Error) {
        let detail = error as NSError
        lastError = "\(detail.localizedDescription) (\(detail.domain), \(detail.code))"
        status = "Operation failed. You can try again."
        // Never log profiles, invitations, or error userInfo dictionaries.
        logger.error("Operation failed: \(detail.domain, privacy: .public) code \(detail.code, privacy: .public)")
    }
    func importFile(_ text: String) {
        guard !busy else { return }
        busy = true
        Task {
            defer { busy = false }
            do { try await importProfile(text) } catch { report(error) }
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
                    try await self.work.run {
                        try NativeRuntime.prepare()
                        var error = [CChar](repeating: 0, count: 256)
                        guard let output = uri.withCString({ xpn_enroll($0, &error, error.count) }) else {
                            throw ProfileStore.failure(String(cString: error))
                        }
                        defer { xpn_free(output) }
                        return String(cString: output)
                    }
                }
                try await importProfile(text)
                if case .invitation = input { status = "Device enrolled. Ready to connect." }
            } catch { report(error) }
            busy = false
        }
    }
    private func apply(_ updated: SavedConnections) {
        loadingPreferences = true
        defer { loadingPreferences = false }
        catalog = updated
        connections = updated.connections
        selectedID = updated.selectedID ?? updated.connections.first?.id ?? ""
        let entry = connections.first { $0.id == selectedID }
        connectionName = entry?.name ?? ""
        requiresHybrid = entry?.requiresHybrid ?? false
        innerEncryption = requiresHybrid || (entry?.innerEncryption ?? true)
        requirePQ = requiresHybrid || (entry?.requirePQ ?? false)
        customSplit = entry?.customSplit ?? false
        subnets = entry?.subnets ?? ""
    }
    private func persistPreferences() {
        guard !loadingPreferences, let index = catalog.connections.firstIndex(where: { $0.id == selectedID }) else { return }
        var updated = catalog
        updated.connections[index].innerEncryption = innerEncryption
        updated.connections[index].requirePQ = requirePQ
        updated.connections[index].customSplit = customSplit
        updated.connections[index].subnets = subnets
        catalog = updated
        let snapshot = updated
        work.submit { [weak self] in
            do { try ProfileStore.saveConnections(snapshot) }
            catch { Task { @MainActor in self?.report(error) } }
        }
    }
    func select(_ id: String) {
        guard !busy, catalog.connections.contains(where: { $0.id == id }) else { return }
        var updated = catalog; updated.selectedID = id
        saveSelection(updated)
    }
    func rename() {
        guard !busy, let index = catalog.connections.firstIndex(where: { $0.id == selectedID }) else { return }
        let name = connectionName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, name.count <= 80 else { status = "Enter a name of 1–80 characters."; return }
        var updated = catalog; updated.connections[index].name = name
        saveSelection(updated)
    }
    private func saveSelection(_ updated: SavedConnections) {
        busy = true
        Task {
            defer { busy = false }
            do {
                try await work.run { try ProfileStore.saveConnections(updated) }
                apply(updated)
            } catch { report(error) }
        }
    }
    func remove() {
        guard !busy else { return }
        busy = true
        let id = selectedID
        Task {
            defer { busy = false }
            do {
                let managers = try await NETunnelProviderManager.loadAllFromPreferences()
                let matching = managers.filter {
                    guard let config = $0.protocolConfiguration as? NETunnelProviderProtocol,
                          config.providerBundleIdentifier == Bundle.main.bundleIdentifier! + ".tunnel" else { return false }
                    return config.providerConfiguration?["connectionID"] as? String == id
                        || config.providerConfiguration?["connectionID"] == nil
                }
                guard !matching.contains(where: { Self.active($0) }) else {
                    throw ProfileStore.failure("Disconnect this connection before removing it.")
                }
                for manager in matching { try await manager.removeFromPreferences() }
                var updated = catalog; updated.remove(id)
                let snapshot = updated
                try await work.run { try ProfileStore.saveConnections(snapshot) }; apply(updated)
                updateStatus()
            } catch { report(error) }
        }
    }
    private static func active(_ manager: NETunnelProviderManager) -> Bool {
        manager.connection.status != .disconnected && manager.connection.status != .invalid
    }
    private func updateStatus() {
        let id = (manager?.protocolConfiguration as? NETunnelProviderProtocol)?.providerConfiguration?["connectionID"] as? String
        let name = catalog.connections.first { $0.id == id }?.name ?? "XPN"
        switch manager?.connection.status {
        case .connected:
            pendingAttempt = false; connecting = false; lastError = nil
            status = "Connected to " + name
        case .connecting, .reasserting:
            connecting = true
            status = "Connecting to " + name + "…"
        case .disconnecting:
            connecting = true
            status = "Disconnecting…"
        default:
            connecting = false
            status = connections.isEmpty ? "Add a connection to get started." : "Disconnected"
            if pendingAttempt && !intentionalStop {
                pendingAttempt = false
                fetchConnectionError(fallback: true)
            }
        }
    }
    private func fetchConnectionError(fallback: Bool) {
        guard let connection = manager?.connection else { return }
        let identity = ObjectIdentifier(connection)
        let attempt = attemptID
        connection.fetchLastDisconnectError { [weak self] error in
            Task { @MainActor in
                guard let self, self.attemptID == attempt, let current = self.manager?.connection,
                      ObjectIdentifier(current) == identity,
                      current.status == .disconnected || current.status == .invalid else { return }
                if let error { self.report(error) }
                else if fallback { self.report(ProfileStore.failure("The tunnel stopped before connecting. Try Connect again; if it repeats, check the device's XPN Connection logs.")) }
            }
        }
    }
    func importProfile(_ text: String) async throws {
        let updated = try await work.run {
            guard text.utf8.count <= 8192, !text.contains("\0"), text.withCString({ xpn_validate_profile($0) }) == 0 else {
                throw ProfileStore.failure("Invalid XPN profile")
            }
            // Load/migrate before adding so an existing single profile is preserved.
            var updated = try ProfileStore.connections(allowLegacyMigration: true)
            try updated.importProfile(text)
            try ProfileStore.saveConnections(updated)
            return updated
        }
        apply(updated)
        invitation = ""
        lastError = nil
        status = "Connection saved. Ready to connect."
    }
    func connect() {
        guard !busy, !connecting else { return }
        busy = true
        lastError = nil
        attemptID = UUID()
        pendingAttempt = false
        Task {
            do {
                apply(try await work.run { try ProfileStore.connections(allowLegacyMigration: true) })
                guard let entry = catalog.connections.first(where: { $0.id == selectedID }) else {
                    throw ProfileStore.failure("Add a connection first.")
                }
                let text = entry.profile
                guard text.withCString({ xpn_validate_profile($0) }) == 0,
                      var profile = try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] else { throw ProfileStore.failure("Invalid XPN profile") }

                if customSplit {
                    let routes = subnets.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
                    guard !routes.isEmpty else { throw ProfileStore.failure("Enter at least one IPv4 subnet") }
                    profile["fullTunnel"] = false; profile["routes"] = routes
                }
                let managers = try await NETunnelProviderManager.loadAllFromPreferences()
                let bundle = Bundle.main.bundleIdentifier! + ".tunnel"
                let owned = managers.filter { ($0.protocolConfiguration as? NETunnelProviderProtocol)?.providerBundleIdentifier == bundle }
                let manager = owned.first {
                    ($0.protocolConfiguration as? NETunnelProviderProtocol)?.providerConfiguration?["connectionID"] as? String == entry.id
                } ?? owned.first {
                    ($0.protocolConfiguration as? NETunnelProviderProtocol)?.providerConfiguration?["connectionID"] == nil
                } ?? NETunnelProviderManager()
                let active = owned.filter { Self.active($0) }
                if !active.isEmpty {
                    status = "Disconnecting before switching…"
                    intentionalStop = true
                    for previous in active { previous.connection.stopVPNTunnel() }
                    for _ in 0..<100 {
                        if !active.contains(where: { Self.active($0) }) { break }
                        try await Task.sleep(nanoseconds: 100_000_000)
                    }
                    guard !active.contains(where: { Self.active($0) }) else {
                        throw ProfileStore.failure("The current tunnel is still disconnecting. Try again shortly.")
                    }
                }
                self.manager = manager
                status = "Resolving VPN server…"
                let endpoint = profile["endpoint"] as! String
                let serverAddress = try await Task.detached { try EndpointResolver.resolve(endpoint) }.value
                let configuration = NETunnelProviderProtocol()
                configuration.providerBundleIdentifier = bundle
                configuration.serverAddress = serverAddress
                configuration.providerConfiguration = ["connectionID": entry.id, "fullTunnel": profile["fullTunnel"]!, "routes": profile["routes"]!, "resolvedServerAddress": serverAddress,
                    "innerEncryption": innerEncryption, "requirePQ": requirePQ]
                configuration.includeAllNetworks = profile["fullTunnel"] as? Bool ?? false
                // LAN access is always available, including in full-tunnel mode.
                configuration.excludeLocalNetworks = true
                // Saving requests permission to modify system VPN settings.
                // An ordinary reconnect must reuse the already approved entry.
                if !manager.isEnabled || manager.localizedDescription != "XPN — " + entry.name
                    || !TunnelPreferences.matches(manager.protocolConfiguration, configuration) {
                    manager.protocolConfiguration = configuration
                    manager.localizedDescription = "XPN — " + entry.name
                    manager.isEnabled = true
                    try await manager.saveToPreferences()
                    try await manager.loadFromPreferences()
                }
                self.manager = manager
                intentionalStop = false
                pendingAttempt = true
                connecting = true
                try manager.connection.startVPNTunnel()
                status = "Connecting…"
            } catch { pendingAttempt = false; connecting = false; report(error) }
            busy = false
        }
    }
    func disconnect() {
        intentionalStop = true; pendingAttempt = false; attemptID = UUID()
        manager?.connection.stopVPNTunnel()
    }
}
