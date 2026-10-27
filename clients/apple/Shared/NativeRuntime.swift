import Foundation
import OSLog

enum NativeRuntime {
    // Swift's lazy static initialization runs once per process, on the worker
    // that first needs networking; rendering the app does not initialize curl.
    private static let readiness: Result<Void, Error> = Result {
        let began = Date()
        if let path = Bundle.main.path(forResource: "cacert", ofType: "pem"),
           path.withCString({ xpn_set_ca_file($0) }) != 0 {
            throw ProfileStore.failure("Cannot initialize certificate trust")
        }
        guard xpn_global_init() == 0 else {
            throw ProfileStore.failure("Cannot initialize VPN networking")
        }
        Logger(subsystem: "com.jeffhansen.xpn", category: "NativeStartup")
            .info("Native networking initialized after \(Date().timeIntervalSince(began), privacy: .public) seconds")
    }
    static func prepare() throws { try readiness.get() }
}
