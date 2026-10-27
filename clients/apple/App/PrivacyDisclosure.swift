import SwiftUI

struct PrivacyDisclosure: View {
    var continueAction: () -> Void
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Your data and your VPN").font(.title.bold())
                Text("XPN saves server profiles and device keys in this device’s Keychain. QR camera images are processed on this device; the invitation is sent to its enrollment server to obtain your connection profile.")
                Text("When connected, your chosen VPN server receives your device identifier and public IP address and handles the traffic routed through it. The server operator controls its accounts and logs. Internet services still receive the traffic you send to them; use servers you trust.")
                Text("The XPN client includes no advertising or analytics SDK. Connection diagnostics stay in Apple’s system logs unless you share them. TestFlight feedback and crash reporting are handled separately by Apple.")
                Link("Privacy Policy", destination: URL(string: "https://www.alta.inc/privacy-policy")!)
                Link("Support", destination: URL(string: "https://www.alta.inc/contact-us")!)
                Button("Continue", action: continueAction).buttonStyle(.borderedProminent)
            }.padding(28).frame(maxWidth: 560, alignment: .leading)
        }.interactiveDismissDisabled()
    }
}
