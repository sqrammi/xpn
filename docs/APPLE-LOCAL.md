# Build and test the Apple clients locally

You need the full Xcode installation and its SDKs. You do **not** have to use the Xcode UI for compilation, but use it for the first signed run: account selection, provisioning, connected iPhone setup and debugging are much easier there. After that, `xcodebuild` can automate builds. No App Store upload is needed for development testing with your team.

The repo has two app schemes, `XPN-macOS` and `XPN-iOS`. Each embeds a packet tunnel extension. Both the app and its extension must be signed with the same Apple team and share the configured Keychain access group.

## 1. Prepare Xcode and build tools on your Mac

1. Install the full Xcode application from Apple, open it once, accept its license, and let it install requested components. Command Line Tools alone are insufficient. Install the iOS platform SDK if prompted.
2. In **Xcode → Settings → Accounts** (Apple Accounts in some versions), add your Apple Developer account and select your paid team.
3. In Terminal, select Xcode and check it:

   ```sh
   sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
   xcodebuild -version
   xcrun --sdk iphoneos --show-sdk-path
   ```

4. Install build tools using your existing Homebrew installation:

   ```sh
   brew install cmake ninja pkg-config xcodegen autoconf automake libtool
   cd /Users/ninkid/repo/xpn
   ```

The current `XPNNative.xcframework` in this checkout contains self-contained static libraries for both macOS architectures, rebuilt on 2026-10-26 with paired connections and the packet-framing correction. It does not yet contain iOS slices. Native tests, the universal unsigned Release build, and the signed ARM Debug app/extension build passed. The signed client launched successfully. The older Homebrew-linked framework was backed up by the packaging script.

## 2. Build the native dependencies and framework

For both Mac and iOS, run from the repository root:

```sh
sh native/tools/apple-dependencies.sh
XPN_REPLACE_FRAMEWORK=1 sh native/tools/package-apple.sh
```

The first command downloads a pinned vcpkg checkout and compiles OpenSSL, libwebsockets, curl, Jansson and their dependencies. It can take a substantial amount of time and disk space on the first run. It builds four targets: iOS device arm64, iOS simulator arm64, macOS arm64 and macOS x86_64. The simulator slice therefore targets Apple Silicon Macs. No `sudo` or `CI=true` is needed.

Build work is kept under `build/apple-deps`. Each architecture has its own manifest installation under `installs/`, so building a later architecture cannot prune an earlier SDK. Rerun the first command after an interrupted dependency build; completed ports are cached. The script rejects an existing vcpkg checkout at a different revision instead of resetting it. If changing the pinned revision, select a new work directory with `XPN_DEPENDENCY_WORK` and use its `sdk` folder as `XPN_APPLE_SDKS` for packaging.

The packaging command compiles XPN's C code for those targets and produces:

```text
clients/apple/Frameworks/XPNNative.xcframework
```

An existing framework is moved to `XPNNative.previous-<timestamp>-<pid>.xcframework` only after the replacement build succeeds. Keep the backup until the new build works.

For a quicker **Mac-only first pass**, use both commands with the same selector:

```sh
XPN_APPLE_TARGETS=macos sh native/tools/apple-dependencies.sh
XPN_APPLE_TARGETS=macos XPN_REPLACE_FRAMEWORK=1 sh native/tools/package-apple.sh
```

Then rerun the default pair to add iOS, reusing the dependency cache. A Mac-only framework cannot build the iOS scheme. `XPN_APPLE_TARGETS=ios` is also available, but replaces the output with an iOS-only framework; use the default `all` to retain both platforms.

If the full SDK build fails, retain the vcpkg error output and its referenced build log. Do not substitute macOS Homebrew libraries for iOS libraries: platform, architecture and deployment target must match. The static macOS dependency build is validated; iOS dependency builds remain unvalidated.

## 3. Set your team and bundle identifiers

Find your ten-character Team ID in your Apple Developer membership details. Choose a unique reverse-DNS prefix you control, for example `com.jeffhansen.xpn`. Replace the sample values in this command:

The initial signing attempt selected Personal Team `B9PJSFMM8M`, which cannot provision Network Extensions. The local overlay now uses the account's **Soundvision Technologies LLC** team, `PHZ3789J83`, for all four targets. Apple accepted the company team and provisioned this Mac and the macOS extension. Complete any macOS Keychain prompt for `codesign` locally using your login password; do not paste that password into a terminal command or chat. A successful unsigned build is still insufficient to run the VPN.

The signed Debug build is now at `build/xcode-macos/Build/Products/Debug/XPN-macOS.app`. Its signatures were verified and the app was launched. This is a development build for the registered Mac; it is not a notarized public download. A live full-tunnel Mac connection to Alta now passes gateway ping, HTTPS and SSH checks. The DNS startup fix reduced the measured connection from a 30-second resolver stall to about 3.4 seconds; see [validation](VALIDATION.md). iOS and broader routing/throughput acceptance checks remain.

```sh
python3 native/tools/apple-project.py YOURTEAMID com.jeffhansen.xpn
open clients/apple/XPN.xcodeproj
```

`YOURTEAMID` is a placeholder: replace it with your actual 10-character ID. The helper writes an ignored `clients/apple/project.local.yml` and runs XcodeGen. It leaves the tracked template unchanged, sets automatic signing, and creates these four bundle IDs:

| Target | Example bundle ID |
| --- | --- |
| XPN-macOS | com.jeffhansen.xpn.macos |
| XPN-macOS-Tunnel | com.jeffhansen.xpn.macos.tunnel |
| XPN-iOS | com.jeffhansen.xpn.ios |
| XPN-iOS-Tunnel | com.jeffhansen.xpn.ios.tunnel |

The shared Keychain suffix is `com.jeffhansen.xpn.shared`, prefixed at build time by `$(AppIdentifierPrefix)`. Do not replace that prefix with a guessed value: older accounts can have an App ID prefix different from the Team ID. This is **Keychain Sharing**, not an App Groups entitlement.

In Xcode's project editor, inspect **Signing & Capabilities** for all four targets:

1. Enable **Automatically manage signing** and select your team.
2. Confirm each bundle identifier matches the table for your chosen prefix.
3. Ensure **Network Extensions → Packet Tunnel** and **Keychain Sharing** are enabled. Keep the same shared Keychain group on app and extension targets.
4. For macOS, retain App Sandbox, outgoing network connections, and camera permission on the app. The tunnel has outgoing network permission too.
5. Resolve signing errors before running. Your team account may need an administrator to register the identifiers/enable capabilities. Do not remove the Network Extension entitlement to get a build to succeed.

Xcode can register App IDs and generate development provisioning profiles through automatic signing, subject to your team's permissions. [Apple's signing instructions](https://developer.apple.com/documentation/xcode/distributing-your-app-to-registered-devices) describe this flow.

Regenerate later with `xcodegen generate --spec clients/apple/project.local.yml`; running the plain tracked `project.yml` instead restores placeholders. Changes made only to the generated `.xcodeproj` can be lost on regeneration.

## 4. Build and run on this Mac

1. Select scheme **XPN-macOS** and destination **My Mac**. Select the app scheme, not `XPN-macOS-Tunnel`.
2. Choose **Product → Build** (⌘B). Fix dependency or signing errors first.
3. Choose **Product → Run** (⌘R). If macOS asks to allow the VPN configuration, approve it as part of this test.
4. Scan the one-use QR, paste an invitation link or profile JSON and click **Add connection**, or choose **Import JSON** and select `xpn-profile.json`. Downloading a profile from the web join page already redeems the invitation; import that profile instead of redeeming the same invitation again. Your Mac needs a camera for scanning; JSON import works without one.
5. Leave **TLS encryption** enabled (it is locked on). **Additional encryption** controls the inner ChaCha20-Poly1305 packet layer; **Require post-quantum key exchange** requires ML-KEM with no fallback. Changes apply on reconnect and are remembered per device. A server-required hybrid policy locks both protections on.
6. New builds automatically maintain one active and one authenticated standby connection. The server must support XPN v3; Alta has been updated. A healthy spare can take over when measured active latency exceeds 500 ms. TCP keepalives use 15-second defaults; see [protocol details](PROTOCOL.md#activestandby-connections-v3).
7. Start with a split route to a separate reachable test host. Connect and inspect Xcode's console. Exercise the acceptance checklist in [local testing](LOCAL-TESTING.md).

Use Xcode/Console to inspect the embedded extension when the app launches but the tunnel fails. An unsigned app can build successfully but cannot establish a usable Network Extension tunnel. A Keychain error usually needs checking the app and extension's actual signed groups/profiles, not granting broader filesystem permissions.

### Accessing devices on the local LAN

Local network access is always enabled on Mac and iPhone, including in full-tunnel mode. There is no checkbox or preference to disable it. Reopen the updated app and reconnect once to apply the policy to an existing VPN configuration; unchanged reconnects do not save it again. Earlier saved checkbox values are ignored.

The app explicitly sets Apple's `excludeLocalNetworks` property alongside `includeAllNetworks`, rather than relying on different macOS/iOS defaults. It does not hard-code RFC1918 ranges or bypass all private addresses: other networks reachable only through the VPN stay governed by the tunnel routes. A LAN address range can be locally connected even if it is not RFC1918 space; this Mac's `172.9.0.0/16` is one such example. Routed networks behind another LAN gateway may need separate route policy and are not promised by this directly connected LAN setting.

Previously, full mode set `includeAllNetworks` but never enabled the local-network exception. On macOS that exception defaults off, so traffic could be captured despite a more-specific LAN route. Current route inspection while disconnected showed `172.9.0.0/16` on `en0`, with gateway `172.9.0.1`. A successful disconnected ping alone does not validate behavior while the VPN policy is active; test the same host after reconnecting. Local IPv6 may also be excluded by the system's LAN exception; Internet IPv6 remains blocked by this IPv4-only tunnel.

See [Apple's routing guidance](https://developer.apple.com/documentation/networkextension/routing-your-vpn-network-traffic).

### Repeated password prompts

The October 26 Keychain fix changes profile storage to the Data Protection Keychain with the app/extension's shared access group. Earlier builds used the legacy login Keychain; its access list trusted only the main app, so every new tunnel process asked permission to read `XPN.profile`. System logs confirmed this on the affected Mac.

Quit and reopen the updated app, then Connect once. The containing app automatically copies an existing legacy profile to the shared protected store. A one-time migration prompt is possible; the old item is retained as a recovery copy. The tunnel never falls back to the legacy store. Subsequent connections should not request the Keychain password. New imports save directly to shared storage, with device-only accessibility after first unlock. No PSK is moved into preferences or plaintext files, and no credentials are rotated.

Unchanged connections also reuse the existing VPN configuration instead of calling `saveToPreferences` every time. macOS may still require its normal authorization when first adding a VPN or changing its endpoint/routing/encryption settings. This change does not disable system authorization or bypass a locked Keychain. If access fails, the app reports the Keychain status rather than repeatedly trying a legacy read.

[Apple's Keychain implementation guidance](https://developer.apple.com/documentation/technotes/tn3137-on-mac-keychains) explains the distinction between legacy access lists and Data Protection access groups.

This macOS target uses an **app extension**, appropriate for development testing and the App Store distribution path. Public direct-download **Developer ID** distribution needs the system-extension variant of packet tunnels, which this repo does not yet implement. [Apple's deployment table](https://developer.apple.com/documentation/technotes/tn3134-network-extension-provider-deployment) distinguishes those paths.

## 5. Build and run on an iPhone/iPad

1. Complete the full native framework build in step 2. The device slice is `ios-arm64`; a simulator build is not interchangeable.
2. Connect the unlocked iPhone/iPad by USB, trust the Mac when asked, and let Xcode pair it. Use **Window → Devices and Simulators** or **Device Hub**, depending on Xcode version.
3. Enable **Settings → Privacy & Security → Developer Mode** on the device if Xcode requests it. Restart and confirm on the device. The setting may appear only after pairing. [Apple's Developer Mode instructions](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device).
4. Select scheme **XPN-iOS**, and select the physical device as destination.
5. Check team/automatic signing on **both** iOS targets. Xcode may need to register the device with your team.
6. Press ⌘R. Unlock the device if Xcode asks. Allow the camera when scanning and allow adding the VPN configuration when connecting.
7. Create a **separate device identity** in the console for this iPhone. A consumed Mac invitation cannot enroll the phone, and sharing the same device credential causes concurrent-session conflicts.
8. Scan the QR, choose Connect, and test split traffic before full tunnel. The phone must be able to reach your HTTPS endpoint from its Wi-Fi network; it cannot normally reach a Mac's private VM NAT address directly. Use a reachable test server or an explicitly configured LAN/HTTPS proxy.

Use the simulator for UI/build checks. Acceptance requires a real device for the packet tunnel, camera, Keychain, Wi-Fi/cellular transitions and performance.

## 6. Command-line builds after signing is configured

These compile using the generated project. They do not install or run the result:

```sh
xcodebuild -project clients/apple/XPN.xcodeproj -scheme XPN-macOS \
  -destination 'platform=macOS' -configuration Debug \
  -derivedDataPath build/xcode-macos build

xcodebuild -project clients/apple/XPN.xcodeproj -scheme XPN-iOS \
  -destination 'generic/platform=iOS' -configuration Debug \
  -derivedDataPath build/xcode-ios build
```

If you want Xcode to contact your team for provisioning updates, add `-allowProvisioningUpdates` after configuring the account. Keep `CODE_SIGNING_ALLOWED=NO` only for compile/link checks; it is not a working VPN installation. For a first physical-device launch, return to ⌘R in Xcode. Archives/export/TestFlight/Developer ID release work come after local functional tests.

If the selected development Mac is not registered with the company team, add `-allowProvisioningDeviceRegistration` alongside `-allowProvisioningUpdates` to register it and include it in the development profile. The signing key may require local Keychain authorization even after provisioning succeeds.
