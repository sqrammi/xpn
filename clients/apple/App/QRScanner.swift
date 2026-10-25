import SwiftUI
import AVFoundation

final class Scanner: NSObject, ObservableObject, AVCaptureMetadataOutputObjectsDelegate {
    let session = AVCaptureSession()
    @Published var message = "Point the camera at your XPN invitation"
    var receive: ((String) -> Void)?
    private let queue = DispatchQueue(label: "xpn.camera")
    private var wanted = false
    func start() {
        queue.async { self.wanted = true }
        AVCaptureDevice.requestAccess(for: .video) { [weak self] allowed in
            guard let self else { return }
            guard allowed else { DispatchQueue.main.async { self.message = "Camera access is disabled. Enable it in Settings, or paste the invitation." }; return }
            self.queue.async {
                guard self.wanted else { return }
                do {
                    guard let device = AVCaptureDevice.default(for: .video) else { throw ProfileStore.failure("No camera available") }
                    let input = try AVCaptureDeviceInput(device: device)
                    let output = AVCaptureMetadataOutput()
                    self.session.beginConfiguration()
                    self.session.inputs.forEach { self.session.removeInput($0) }
                    self.session.outputs.forEach { self.session.removeOutput($0) }
                    guard self.session.canAddInput(input), self.session.canAddOutput(output) else { self.session.commitConfiguration(); throw ProfileStore.failure("Cannot start camera") }
                    self.session.addInput(input); self.session.addOutput(output)
                    self.session.commitConfiguration()
                    output.setMetadataObjectsDelegate(self, queue: .main)
                    guard output.availableMetadataObjectTypes.contains(.qr) else { throw ProfileStore.failure("Camera does not support QR detection") }
                    output.metadataObjectTypes = [.qr]; self.session.startRunning()
                } catch { DispatchQueue.main.async { self.message = error.localizedDescription } }
            }
        }
    }
    func stop() { queue.async { self.wanted = false; self.session.stopRunning() } }
    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard let value = (metadataObjects.first as? AVMetadataMachineReadableCodeObject)?.stringValue,
              value.hasPrefix("https://"), value.contains("/join#") else { return }
        let callback = receive; receive = nil; stop(); callback?(value)
    }
}
struct QRScanner: View {
    @StateObject private var scanner = Scanner()
    @Environment(\.dismiss) private var dismiss
    var receive: (String) -> Void
    var body: some View {
        VStack {
            CameraPreview(session: scanner.session).frame(minWidth: 300, minHeight: 300)
            Text(scanner.message).padding()
            Button("Cancel") { dismiss() }.padding()
        }.onAppear { scanner.receive = receive; scanner.start() }.onDisappear { scanner.stop() }
    }
}
#if os(iOS)
import UIKit
struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession
    func makeUIView(context: Context) -> Preview { let view = Preview(); view.preview.session = session; view.preview.videoGravity = .resizeAspectFill; return view }
    func updateUIView(_ view: Preview, context: Context) {}
    final class Preview: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var preview: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    }
}
#else
import AppKit
struct CameraPreview: NSViewRepresentable {
    let session: AVCaptureSession
    func makeNSView(context: Context) -> NSView {
        let view = NSView(); view.wantsLayer = true
        let preview = AVCaptureVideoPreviewLayer(session: session); preview.videoGravity = .resizeAspectFill; preview.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]
        view.layer?.addSublayer(preview); return view
    }
    func updateNSView(_ view: NSView, context: Context) { view.layer?.sublayers?.first?.frame = view.bounds }
}
#endif
