import Foundation

/// Keep synchronous Keychain and native setup work off the UI executor.
/// One queue preserves the ordering of profile writes and subsequent reads.
final class BlockingWork: @unchecked Sendable {
    private let queue = DispatchQueue(label: "xpn.profile-work", qos: .userInitiated)

    func submit(_ operation: @escaping @Sendable () -> Void) {
        queue.async(execute: operation)
    }
    func run<T: Sendable>(_ operation: @escaping @Sendable () throws -> T) async throws -> T {
        try await withCheckedThrowingContinuation { continuation in
            submit { continuation.resume(with: Result { try operation() }) }
        }
    }
}
