import Foundation

enum TestFailure: Error { case expected }
final class WorkState: @unchecked Sendable {
    // Accessed only on BlockingWork's serial queue.
    var value = 0
}
@main struct BlockingWorkTests {
    @MainActor static func main() async throws {
        let work = BlockingWork()
        let state = WorkState()
        let entered = DispatchSemaphore(value: 0)
        let release = DispatchSemaphore(value: 0)
        work.submit {
            precondition(!Thread.isMainThread)
            entered.signal()
            precondition(release.wait(timeout: .now() + 5) == .success)
            state.value = 1
        }
        let began = await withCheckedContinuation { continuation in
            DispatchQueue.global().async {
                continuation.resume(returning: entered.wait(timeout: .now() + 5) == .success)
            }
        }
        precondition(began)
        // The UI executor can continue while synchronous initialization is
        // blocked. Queueing another write must not run ahead of the first.
        work.submit { state.value += 1 }
        release.signal()
        let value = try await work.run { state.value }
        precondition(value == 2)
        do {
            let _: Int = try await work.run { throw TestFailure.expected }
            fatalError("Expected failure")
        } catch TestFailure.expected {}
        let next = try await work.run { state.value + 1 }
        precondition(next == 3)
        print("Background work tests passed: responsive UI executor, ordered writes/reads, error propagation and recovery.")
    }
}
