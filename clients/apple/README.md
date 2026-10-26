# Apple clients

SwiftUI apps for macOS 14+ and iOS 17+ share the C transport. AVFoundation scans QR invitations; profiles live in a shared device-only Keychain entry. Each platform embeds an NEPacketTunnelProvider extension. The provider authenticates before installing routes, delivers packets through `packetFlow`, and handles native transport closure.

For a first signed build on your Mac or iPhone, follow [the local step-by-step guide](../../docs/APPLE-LOCAL.md). It covers Xcode, native dependencies, team IDs, signing and first-run checks.

## Build prerequisites and current status

Both macOS and iOS Swift app/provider targets have been typechecked against installed Apple SDKs. The unsigned macOS app and embedded extension also build and link against the native C library. **They have not been signed or tested on physical devices.** The local macOS link check uses current Homebrew dynamic libraries, which target newer macOS versions; it is not a portable macOS 14 binary or an iOS dependency SDK.

`XPNNative.xcframework` is a required build input. The manually dispatched `.github/workflows/apple.yml` workflow builds pinned vcpkg dependency SDKs for the proper deployment targets, packages the framework, and attempts unsigned simulator/macOS builds. It has not been run here; its first successful remote run remains an outstanding validation gate. The temporary macOS-only framework used for the local link check is not a substitute for this complete SDK.

For **local macOS or CI builds**, supply vetted static OpenSSL (3.0+, 3.5+ for ML-KEM), libwebsockets (4.3+), libcurl (7.85+), and Jansson (2.13+) libraries for each slice. Each dependency must be built for that exact target, with matching generated headers, deployment target, and architecture. libwebsockets must enable client/server support and OpenSSL TLS; do not enable unnecessary compression/extensions. Build curl with HTTPS/OpenSSL and only system zlib dependencies (or include its other static dependencies in the same SDK directory). iOS socket use must be compatible with app extensions. Do not mix macOS and iOS libraries.

Set `XPN_APPLE_SDKS` to:

```text
sdk-root/
  ios-arm64/{include/,lib/*.a}
  simulator-arm64/{include/,lib/*.a}
  macos-arm64/{include/,lib/*.a}
  macos-x86_64/{include/,lib/*.a}
```

Each `lib` directory needs `libssl.a`, `libcrypto.a`, `libwebsockets.a`, `libcurl.a`, and `libjansson.a`. The packaging script merges those dependencies and their transitive static libraries into the native library and produces the XCFramework. The `apple-dependencies.sh` recipe obtains and cross-compiles these SDKs using a pinned vcpkg revision; it can run locally or in CI and reuses completed builds. You may instead supply your own vetted SDKs. Review the pinned ports and update dependencies as part of release maintenance. Third-party license notices are copied into application resources by the dependency recipe.

Run locally (or with explicit SDK paths in CI):

```sh
sh native/tools/apple-dependencies.sh
XPN_REPLACE_FRAMEWORK=1 sh native/tools/package-apple.sh
python3 native/tools/apple-project.py YOURTEAMID com.yourdomain.xpn
open clients/apple/XPN.xcodeproj
```

The project helper generates an ignored `project.local.yml` with your team, bundle IDs and shared Keychain group; replace the sample arguments with your own values. Enable Network Extensions and Keychain Sharing for the app and matching extension identifiers in the Apple Developer portal. Generate provisioning profiles with those entitlements. Keep signing credentials in Xcode/Keychain locally, or your signing secret store in CI.

The example macOS app uses an embedded packet-tunnel app extension and is intended for development/App Store provisioning. Developer ID distribution requires a system-extension packaging variant and the corresponding `packet-tunnel-provider-systemextension` entitlement; that packaging variant is not implemented here. Test the chosen distribution method on a clean device before shipping.

`Resources/cacert.pem` is curl's Mozilla root bundle, included because OpenSSL does not automatically use the Apple system trust store. Update it from <https://curl.se/docs/caextract.html> as part of releases; private-CA deployments must include the required trust root. Apps and extensions both bundle it. Never disable hostname/certificate validation to work around a missing CA.

## Device checks still required

- QR camera permissions, JSON import, one-use enrollment, Keychain sharing and extension startup.
- Full IPv4 tunneling with IPv6 capture/drop, DNS behavior, split routes and prevention of unauthorized route expansion by the server.
- Wi-Fi/cellular changes, device sleep, reconnect, revocation and key rotation.
- Packet throughput, memory use under backpressure, battery impact and App Store/Developer ID signing.

The native service closes sessions after one hour to require a fresh key exchange. These first clients report disconnection and require reconnecting; seamless network roaming and automatic reconnect are not implemented.
