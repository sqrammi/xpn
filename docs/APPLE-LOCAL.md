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

The previous temporary `XPNNative.xcframework` in this checkout is **macOS-only and linked to Homebrew libraries**. It was a link test, not an iOS SDK or a distributable framework. The next step replaces it with target-specific static libraries.

## 2. Build the native dependencies and framework

For both Mac and iOS, run from the repository root:

```sh
sh native/tools/apple-dependencies.sh
XPN_REPLACE_FRAMEWORK=1 sh native/tools/package-apple.sh
```

The first command downloads a pinned vcpkg checkout and compiles OpenSSL, libwebsockets, curl, Jansson and their dependencies. It can take a substantial amount of time and disk space on the first run. It builds four targets: iOS device arm64, iOS simulator arm64, macOS arm64 and macOS x86_64. The simulator slice therefore targets Apple Silicon Macs. No `sudo` or `CI=true` is needed.

Build work is kept under `build/apple-deps`. Rerun the first command after an interrupted dependency build; completed ports are cached. The script rejects an existing vcpkg checkout at a different revision instead of resetting it. If changing the pinned revision, select a new work directory with `XPN_DEPENDENCY_WORK` and use its `sdk` folder as `XPN_APPLE_SDKS` for packaging.

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

If this first full SDK build fails, retain the vcpkg error output and its referenced build log. Do not substitute macOS Homebrew libraries for iOS libraries: platform, architecture and deployment target must match. This full static dependency build has not yet been validated here end to end.

## 3. Set your team and bundle identifiers

Find your ten-character Team ID in your Apple Developer membership details. Choose a unique reverse-DNS prefix you control, for example `com.jeffhansen.xpn`. Replace the sample values in this command:

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
4. Import a test device's JSON profile or scan its one-use QR. Your Mac needs a camera for scanning; JSON import works without one.
5. Start with a split route to a separate reachable test host. Connect and inspect Xcode's console. Exercise the acceptance checklist in [local testing](LOCAL-TESTING.md).

Use Xcode/Console to inspect the embedded extension when the app launches but the tunnel fails. An unsigned app can build successfully but cannot establish a usable Network Extension tunnel. A Keychain error usually needs checking the app and extension's actual signed groups/profiles, not granting broader filesystem permissions.

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
