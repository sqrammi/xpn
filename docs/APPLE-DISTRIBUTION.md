# iOS distribution and TestFlight

XPN uses Soundvision Technologies LLC team `PHZ3789J83`. App Store Connect record: [XPN (6827353599)](https://appstoreconnect.apple.com/apps/6827353599/distribution). The app bundle is `com.jeffhansen.xpn.ios`; its embedded VPN extension is `com.jeffhansen.xpn.ios.tunnel`. SKU: `xpn-ios`.

## Repeatable release commands

The complete native XCFramework must already contain an iOS device slice. These helpers compile/archive Swift and link existing native libraries; they do not rebuild C dependencies.

```sh
cd /Users/ninkid/repo/xpn
python3 native/tools/apple-release.py archive --build 4
python3 native/tools/apple-release.py export --build 4   # Optional local distribution IPA
python3 native/tools/apple-release.py upload --build 4
```

Use a fresh increasing build number for each subsequent upload. The default marketing version is `1.0.0`; pass `--version` to change it. Export/upload verify the actual archive version and required privacy manifests. Xcode uses its signed-in account for automatic distribution signing and provisioning. Complete any signing-key prompt locally. Never put credentials in a command or this document.

By default, uploaded builds are **internal TestFlight only**, suitable for the initial beta. They cannot later be promoted to external TestFlight/App Store distribution. For a reviewed public-release candidate, archive a new build number and use `--external` when exporting/uploading it. This does not submit the app for review or release it publicly.

Archives live at `build/distribution/XPN-<version>-<build>.xcarchive`. Export options and outputs stay under `build/distribution/`. Both app and extension derive their version and build from the same build settings. The default App Store release setting is manual.

## Install without Developer Mode

Initial tester: `sqrammi@hotmail.com`, in the `XPN Internal` group. Automatic distribution is disabled so subsequent uploads must be explicitly added.

Build `1.0.0 (4)` is processed and marked **Testing** in `XPN Internal`. For future builds, wait for processing, resolve any encryption-compliance requirements, then add the build to that group. On the iPhone, install Apple's TestFlight, use the Apple Account associated with that tester, then install XPN from TestFlight. A TestFlight build does not require Developer Mode. Verify the TestFlight installation works before disabling Developer Mode; a directly installed Xcode development build still needs it. TestFlight builds expire after 90 days, so upload replacement builds during ongoing testing.

## Branding and app metadata

The generated lock icon has a curved X-shaped shackle. Source: `docs/branding/xpn-icon-original.png`. Prompt/tool provenance: `docs/branding/icon-prompt.txt`. Regenerate platform sizes with `python3 native/tools/apple-icons.py`; the checked-in app asset catalog includes opaque 1024px iOS artwork and Mac sizes. It is included only in the containing app, not the extension.

XPN uses the user-specified Alta privacy URL and the support URL verified from Alta Networks:

- Privacy: https://www.alta.inc/privacy-policy
- Support: https://www.alta.inc/contact-us

The app shows a first-use VPN data disclosure and provides persistent privacy/support links. The public policy's broader wording still needs the publisher's review for XPN and Apple's VPN-specific rules; reusing the URL does not transfer Alta Networks' review approval to XPN.

## Privacy and encryption declarations

The app manifest declares app-local preferences (`CA92.1`) and file metadata for app-bundle/container files (`C617.1`) and user-selected JSON files (`3B52.1`). The tunnel manifest declares its app-container file access. Release-binary inspection found file metadata APIs; unused libuv disk-space APIs present in Debug were stripped from Release. No tracking SDK or tracking domain is configured. The App Store privacy questionnaire is separate from these required-reason declarations: review the selected server's account/IP logging and operator practices before submitting collection answers. Do not copy another app's data-collection labels blindly.

XPN embeds OpenSSL, uses TLS, per-device PSK authentication, ChaCha20-Poly1305 and optional X25519/ML-KEM hybrid exchange. It is not an app that uses only Apple's operating-system HTTPS implementation. For build 4, App Store Connect was answered with standard algorithms implemented outside/in addition to Apple's OS, and no France distribution for this beta, as explicitly confirmed by the publisher. Apple cleared the build to Ready to Test without requesting a document. No other app's approval code was reused. `ITSAppUsesNonExemptEncryption` and an Apple documentation code remain unset in the project; review the questionnaire again for future encryption or distribution-scope changes. These beta answers do not establish worldwide public distribution compliance.

For public App Store/external TestFlight review, complete app privacy and age/content ratings, required contact details, screenshots, distribution territories/permits where applicable, and a working reviewer enrollment. Keep reviewer credentials out of Git and public screenshots. This beta still has unresolved LAN-access and throughput work recorded in `VALIDATION.md`; it has not undergone an independent security audit or comprehensive roaming/IPv6-leak testing. A successful archive/upload is not production acceptance.

## October 26 operational record

- Created XPN's iOS App Store Connect record in Soundvision Technologies LLC using limited app access (existing organization administrator access is unchanged).
- Saved draft description, subtitle, Utilities category, keywords, copyright, support URL, version and manual-release setting; set the company's privacy-policy URL. No public review/release was requested.
- Built signed Release archive `1.0.0 (2)` with the icon/disclosure/manifests. Apple's upload validator rejected it because the extension lacked `CFBundleDisplayName`. Added `XPN Tunnel` and prepared the replacement `1.0.0 (3)` archive/upload.
- Stopped build 3's upload when the publisher supplied the corrected Alta privacy URL. Built `1.0.0 (4)` with that URL; Apple accepted its upload (`EXPORT SUCCEEDED`). Both app and extension versions, bundled privacy manifests and deep code signatures were verified.
- Logs: `build/apple-testflight-archive.log`, `build/apple-testflight-upload.log`, `build/apple-testflight-archive-3.log`, `build/apple-testflight-upload-3.log`, `build/apple-testflight-archive-4.log`, `build/apple-testflight-upload-4.log`.
- Created `XPN Internal` with automatic distribution disabled and added only `sqrammi@hotmail.com`. After the standard-encryption/no-France questionnaire cleared, assigned build 4; Apple shows **Testing**. The group shows one tester/one build, with the tester **Invited** at 6:41 PM on October 26.
- Saved and verified `https://www.alta.inc/privacy-policy` in XPN's App Privacy metadata; this is also embedded in build 4.
- No server changes, C rebuild, Git commit/push, or changes to Alta Networks' existing app were performed for distribution preparation.

Sources: [Apple TestFlight overview](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/), [export compliance for beta builds](https://developer.apple.com/help/app-store-connect/test-a-beta-version/provide-export-compliance-information-for-beta-builds/), [App Review guidelines, including VPN apps](https://developer.apple.com/app-store/review/guidelines/), [required-reason API guidance](https://developer.apple.com/documentation/technotes/tn3183-adding-required-reason-api-entries-to-your-privacy-manifest).

## October 29 icon diagnosis

The running Mac app was still the October 25 Debug build under
`build/xcode-macos/Build/Products/Debug/XPN-macOS.app`. Its Info.plist had no
icon keys and its bundle had neither Assets.car nor AppIcon.icns. The shared
source catalog already contains the same artwork for both platforms.

Prepared a signed replacement at
`build/xcode-macos-icons/Build/Products/Debug/XPN-macOS.app`, linking the
existing native XCFramework (no C source compilation). The build succeeded;
deep/strict signature verification passed with system trust access. The bundle
contains AppIcon.icns, Assets.car and CFBundleIconName=AppIcon. Log:
`build/apple-macos-icons-build.log`. The running app/VPN was not stopped or
replaced; quit the old app and launch this replacement to use the new icon.

Read-only App Store Connect inspection confirmed build 4 is Testing and marked
Internal. Its lock/X icon renders correctly in the Add Build selector, but its
selection radio button is disabled. App Store version 1.0.0 remains Prepare for
Submission with no attached build, and the app header shows a placeholder.
The icon is present in the uploaded binary; the draft listing is separate from
the internal TestFlight build. A new standard App Store Connect upload (the
release helper's --external option) is needed to obtain an eligible build for
that version. Uploading/attaching it alone does not submit it for review or
publish the app. No new iOS upload or listing change was made during diagnosis.

Apple references: [app icons](https://developer.apple.com/help/app-store-connect/manage-app-information/add-an-app-icon),
[internal-only build restrictions](https://developer.apple.com/help/app-store-connect/test-a-beta-version/add-internal-testers).
