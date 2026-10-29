# Validation record

Date: 2026-10-25. Hosts: Apple Silicon macOS development machine and alta.jeffhansen.com (Ubuntu 26.04.1 Resolute, x86-64).

## October 29 follow-up: retries belong to the Linux client

The implementation below was revised after the user's clarification: retry
ownership now lives in `clients/linux/xpn.py`, the Linux `xpn connect` command.
The service helper generates a unit that executes that client directly and has
no runtime supervisor. It rejects installed launchers that do not support retries.
Interactive and service connections use the same indefinite jittered backoff;
`--no-retry` allows a single attempt. Native C packet processing is unchanged.

Eighteen focused client/setup tests passed, covering backoff cap/stable reset,
retries after DNS/native failure (including exit zero), terminal native messages,
partial-line authentication timeout, cleanup ordering, fatal cleanup failure,
SIGTERM during connection/cleanup, no-retry, malformed configuration and service
setup/rollback/compatibility. The combined packaging suite ran 48 tests: 47 passed
and one Linux-only test was skipped. Tests use real harmless child processes with
mocked network commands; no C build or local VPN route change occurred.

The real-TUN CI test now invokes the client directly without a supervisor. This
revision has **not** been exercised against real TUN/systemd: SSH to Alta timed
out before any remote change. Earlier remote passes below cover the prior helper
implementation, not this refactor. No installed client, production service or PPA
was updated. Local test output: `build/client-service-tests/client-retry-python-tests.log`.
Updated installation instructions are in [the Linux guide](LINUX-CLIENT-SERVICE.md).

## October 29: boot-started Linux client and retry supervisor

Eleven client-service regressions passed: jitter growth/cap/reset, setup/no-op
reruns, private profile permissions, update backup and rollback, no-start,
unmanaged/symlink refusal, systemd quoting/restrictions, retry after exit zero,
terminal native-message handling and cancellation of a live child. The combined
packaging suite ran 41 tests: 40 passed and the Linux-only socket test was skipped
on macOS. No C project was built.

On Alta, used the existing native executable with temporary source/fixture files
in a private mount/network namespace. Split/full real-TUN transfers, NAT,
host-port isolation, custom SNI/pinning and non-root server thread checks passed.
The new supervisor test authenticated, recovered after a complete test-server
outage, transferred another 1 MiB and stopped without leaving its TUN/firewall
state. Testing exposed an older native event loop that can remain alive after
printing its terminal reconnect message; the supervisor now terminates the
launcher gracefully at that message before retrying.

The generated unit passed `systemd-analyze verify` (unrelated existing host-unit
warnings only). A transient unit with the same filesystem/capability restrictions
and an additional private network namespace launched native code, retried a
refused connection and stopped cleanly. Its first test directory under `/run`
was unsuitable because Alta mounts it noexec; the successful test used a temporary
directory under `/var/lib`. Both runtime directories were removed. Production XPN
services were not restarted or reconfigured. Local Python test logs are in
`build/client-service-tests/`; remote test logs remain in
`/root/xpn-client-service-tests-20261029/`. Subsequent SSH connections timed out,
so the final remote-log download and independent cleanup audit were unavailable;
the test's exit trap completed and its journal recorded a successful stop.

No real host reboot, full-tunnel DNS under the service sandbox, overnight retry
soak, Noble runtime, or new PPA binary build/publication was performed. The helper
is available as a standalone script compatible with the existing PPA launcher;
the package entry point is prepared for a subsequent release. See
[Linux service instructions](LINUX-CLIENT-SERVICE.md).

## October 27: Ubuntu PPA packaging

Noble amd64 packages built and installed on little-guy-root; Resolute amd64 packages built and installed on seven-root. Native CTest, Node tests, syntax checks and installed systemd unit validation passed on both. Namespace-isolated TUN tests passed full/split routing, NAT, host port filtering, custom SNI and certificate pinning with inner encryption enabled/disabled. Standby delay failover and wrong-pin rejection passed; Resolute hybrid ML-KEM transport passed. Final binary packages have no lintian findings. Source lintian's narrow false positives/generated-source paths are documented in the source overrides; upstream preferred sources are included.

Thirty installer regressions pass locally, with the Linux socket test skipped on macOS. Coverage includes explicit checkout-to-package migration, unchanged credentials, boot-link retargeting and no-op reruns. All native builds ran on the designated Ubuntu hosts. Signing/publication and Alta migration evidence is in [the release record](PPA-RELEASE-2026-10-27.md).

## October 26: iOS distribution candidate

Signed Release archive `1.0.0 (4)` succeeded, linking the existing native XCFramework without rebuilding C. Verified matching app/extension build numbers, display names, both privacy manifests and deep code signatures. Apple accepted the upload and processed it to Ready to Test after the encryption questionnaire (standard algorithms beyond Apple OS; no France distribution for this beta, confirmed by the publisher). The archive includes the generated lock/X icon and first-use privacy disclosure linking to the specified Alta policy. Simulator UI testing was unavailable because this Mac has no installed simulator devices/runtimes; this release's first-use disclosure still needs a device smoke test.

Release-helper Python syntax checks passed. See [distribution instructions and operational record](APPLE-DISTRIBUTION.md) for archive/upload commands and App Store Connect changes. This does not resolve the LAN/throughput findings below or constitute public App Store approval.

## October 26: iOS blank launch and first-connection diagnostics

The user installed the iOS build, successfully enrolled by QR, and reported about ten seconds of black launch UI. The first VPN attempt transitioned from Connecting to Disconnected; a subsequent attempt after reopening worked. No original device trace or error was available, so the exact cause of that failed connection is unconfirmed.

Inspection found synchronous Keychain access and curl initialization in the main-actor model initializer, before SwiftUI could render. Initialization now only attaches a status observer. The view starts asynchronous profile loading with a visible progress indicator, using a serial background queue for Keychain work. Native networking initializes lazily once per process on a worker. The extension also prepares the native client on its service queue and checks cancellation before starting the transport. Its native failure message is preserved. The app obtains the system's last-disconnect error, retains it in a separate error label, ignores notifications from other VPN entries and prevents duplicate Connect attempts during transition. Startup timings and error domain/code are logged without profiles, invitations or keys.

The background-work regression passed (UI executor remains responsive during blocked work, writes/read ordering, thrown errors and recovery), along with saved-connection and Keychain migration tests. Signed physical-device iOS and macOS Debug builds passed against the existing XCFramework; deep signature verification passed. No C project was built. The framework now includes iOS device/simulator slices built separately before this investigation.

Installed the update over the existing `com.jeffhansen.xpn.ios` app on the paired iPhone without uninstalling or clearing its data, then successfully launched it with `devicectl`. The 25-second console attachment timed out while waiting for the app to terminate; it did not supply startup timing output. The user subsequently confirmed that the app opens quickly and that Connect succeeded on the first attempt with the update. This is a successful device retest; exact launch latency was not measured, and the original first-attempt failure remains unattributed. Logs: `build/apple-ios-startup-build.log`, `build/apple-ios-startup-install.log`, `build/apple-ios-startup-launch.log`, and `build/apple-startup-macos-build.log`. Alta was inspected read-only; no server deployment/configuration changes were made.

## October 26: saved Apple client connections

Added a Keychain-backed saved connection collection and shared Mac/iOS server picker, names and removal. The extension loads the exact connection ID bound to its system VPN entry; it never substitutes the UI selection. Switching waits for existing XPN tunnels to disconnect before DNS resolution and startup. Each server/device retains its encryption and split-route preferences, with unchanged system entries reused.

Swift tests passed for distinct endpoints sharing a device ID, key rotation without losing preferences or affecting another entry, collection serialization/selection/removal, isolated Keychain accounts and app-only legacy migration. VPN preference tests also verify that changing the connection ID requires a configuration update. Added the collection test to Apple CI; that workflow has not been run remotely.

The signed macOS Debug app built against the existing native framework, and `codesign --verify --deep --strict` passed. No C project was rebuilt or server changed. Log: `build/apple-saved-connections-build.log`. Reopened the app and verified that the existing Alta profile appeared in the Server menu automatically, with its previous encryption selections preserved and rename/remove controls visible. No credentials were printed or exported. A live switch between two different servers has not been exercised; only Alta is enrolled here. Shared iOS source is updated, but no iOS build/device test was performed.

## October 26: installer restart-port regression and live iperf

Reproduced Linux `EADDRINUSE` from the installer's bare bind probe after accepted connections close. The updated probe uses `SO_REUSEADDR` and a real listen check: recently closed connections no longer block installation, while a competing live listener still fails. Twenty-seven installer/network tests passed on Alta; locally, 26 passed and the Linux socket test was skipped. Coverage includes a host-port-only update restarting network/native services while preserving control and credentials. Five native CTests passed during the live install; no local C build was performed.

Installation on Alta succeeded with host TCP ports `85,443,5201`. Live nftables and systemd configuration agree; repeating the installer without the port argument retained that selection and made no changes. See [host changes](ALTA-HOST-CHANGES.md) for exact actions and reports.

The connected Mac reached `10.77.0.1:5201` through `utun10`: `iperf3 -c 10.77.0.1 -t 3 --connect-timeout 3000` completed with 11.3 Mbps received, 12.9 Mbps sent and 1,158 sender retransmissions. Both VPN streams were established. This resolves the TCP connection failure; the high retransmissions and throughput remain unresolved and do not meet the 200 Mbps target.

During that connected session, a subsequent LAN check to `172.9.0.2` returned 0/3 ping replies. The always-enabled Apple LAN policy below has therefore **not yet demonstrated working LAN access** in this setup; further diagnosis is required.

## October 26: Mac LAN access during full tunnel

Read-only route inspection while XPN was disconnected confirmed `172.9.0.0/16` directly attached to `en0`, with default gateway `172.9.0.1`. Code inspection found full mode set `includeAllNetworks = true` without setting `excludeLocalNetworks`; the macOS SDK documents the latter default as false (iOS defaults true). This explains why the policy can capture LAN traffic despite ordinary connected routes; the exact earlier successful/failed sessions were not reproduced.

Initially added a per-device LAN checkbox; the user then requested unconditional LAN access. Removed the checkbox and stored-preference reads/writes, and now always set `excludeLocalNetworks = true`, ignoring any previously saved false value. It explicitly selects the operating system's local-network exception; no blanket private-subnet exclusions, hard-coded user subnet, or server firewall changes are involved. Preference regressions passed: an old full-tunnel configuration without LAN access requires a save, enabling the exception resolves the difference, and an unchanged reconnect remains a no-op. The signed Mac Debug build and `codesign --verify --deep --strict` passed; logs: `build/apple-lan-access-build.log` and the subsequent always-enabled rebuild `build/apple-lan-always-build.log`. The preference regression and signature verification also passed after removing the checkbox. The user identified `172.9.0.2`; while XPN was disconnected it returned 3/3 ping replies at approximately 4 ms via `en0`. A connected ping still awaits user reconnection. This is a Swift-only client change; no C compilation or Alta changes are required. iOS source shares the setting but has not been rebuilt.

## October 26: authenticated active/standby transport

Five native CTests passed on Alta, then under AddressSanitizer/UndefinedBehaviorSanitizer. Tests read actual TCP socket options (enabled, idle 15 seconds, interval 15 seconds, three probes), verify 500 ms/freshness/cooldown selection, exercise v3 PSK mode binding and authenticated activation, and ensure wrong-key or foreign-pair replacement attempts do not evict the active peer. The v2 packet-boundary regression remains covered.

Real nginx plus a TCP relay injected 700 ms downstream delay into the active stream in all four inner-encryption/PQ combinations. Assertions verified two initially warm connections, acknowledged failover, closure of the old primary, replenishment to two connections, subsequent IP packet exchange and revocation. A sanitizer-built test also passed abrupt-primary-close recovery and wrong-pin rejection. These are functional fault-injection tests; synthetic performance through the deliberately impaired relay/Debug or sanitizer builds is not a production throughput benchmark. Real split/full Linux TUN/NAT tests passed with v3 and inner packet encryption disabled, including server tunnel/WAN reachability, host-port filtering and non-root connected threads. Twenty-five installer/network Python regressions passed locally. GitHub workflow changes have not been pushed or run remotely.

Alta's compatible runtime was installed while no VPN clients were connected. Services/readiness and a no-op installer rerun passed; see [host changes](ALTA-HOST-CHANGES.md) for the exact paths/actions. The existing shared nginx listener was preserved; client/native socket timers enforce the 15-second default, and the VPN proxy location enables upstream socket keepalive.

With explicit user authorization, rebuilt the universal macOS C framework and signed ARM Debug app, including the pending framing correction and Swift Keychain fix. Signature verification passed. Four native tests linked against that exact framework passed on this Mac (core, encryption options, standby/socket settings, certificate validation). Logs: `build/apple-standby-native.log`, `build/apple-standby-build.log`, and `build/apple-test-{core,options,standby,certificate}.log`. Previous framework: `clients/apple/Frameworks/XPNNative.previous-20261026154304-36370.xcframework`. The earlier instruction to keep additional encryption enabled pending the framing rebuild is now superseded. A live paired Mac connection and prompt-free repeated reconnect still await user confirmation; iOS was not rebuilt.

## October 26: repeated macOS Keychain password prompt

Read-only `securityd` logs confirmed repeated legacy Keychain prompts for `XPN-macOS-Tunnel.appex` reading `XPN.profile`, followed by one-time Allow approvals. The recorded ACL named only the containing app. This confirms the reported password prompt came from the extension's profile read; the separate unconditional VPN preference save was also removed.

Added shared Data Protection Keychain storage and app-only legacy migration on Connect. The extension cannot trigger legacy prompts. Mocked Security API regressions passed for migration preserving the exact bytes, three subsequent reads without legacy access, key replacement, cancelled migration, write failure, and no legacy fallback on authentication/entitlement/interaction errors. These tests use synthetic credentials and do not read or modify the user's Keychain. VPN preference comparison tests passed for fresh/property-list-restored equivalent objects and detection of endpoint, routing, provider and encryption changes.

The Swift-only signed Mac Debug build succeeded using the existing native XCFramework. `codesign --verify --deep --strict` passed; app and extension both have `PHZ3789J83.com.jeffhansen.xpn.shared`. Build log: `build/apple-keychain-build.log`; diagnostic log: `build/apple-password-diagnostic.log`. No C was compiled, no live Keychain item was accessed by these development tools, and no server changes occurred. Actual migration and two consecutive prompt-free VPN connections still require the user to reopen and test the app. The separate native framing correction remains pending a Mac C rebuild as noted below; keep additional encryption enabled meanwhile. iOS was not rebuilt.

## October 26: client-selectable packet encryption

The v2 transport passed all four combinations of optional inner ChaCha20-Poly1305 and required ML-KEM on Alta with OpenSSL 3.5.5. Tests covered custom SNI, matching certificate pins, numeric dialing, packet exchange and active revocation. Single-layer wrong-pin and trusted-certificate/wrong-pin cases were rejected. Requiring PQ against an outer nginx endpoint restricted to X25519 was rejected before WebSocket upgrade. A separate live nginx handshake observed TLS 1.3 with X25519MLKEM768; no nginx configuration change was needed.

Four CTests passed in Release and with AddressSanitizer/UndefinedBehaviorSanitizer. New coverage verifies authenticated mode selection, minimum server policy, exact plaintext packet output only when selected, byte-fragmented records, malformed headers, pre-authentication injection and source spoof rejection. Final review found and fixed output batching that could insert a TLS keepalive inside a partial raw record; a regression now sends a key update between partial queue drains and verifies all 1,000 packets arrive at record boundaries. The corrected transport also passed a real-nginx single-layer/PQ connection across a 25-second keepalive interval, plus a legacy v1 compatibility test.

The real-TUN namespace suite passed split/full routing, NAT, server gateway/WAN access, host-port filtering and non-root connected threads with inner packet encryption disabled. The four-combination loopback measurements were roughly 87–142 Mbps per direction on Alta; these short measurements do not demonstrate a reliable speedup or meet the 200 Mbps target on this host. There is no WAN throughput result for these options.

The shared Apple interface has TLS locked on, plus independently selectable extra encryption and required PQ; a hybrid server policy locks both optional controls on. Linux exposes equivalent flags. Existing profiles default to extra encryption. The initial signed Mac Debug app with checkboxes was built successfully and its signature verified. The subsequent raw-record batching fix is validated and installed on Alta, but the Mac native framework/app still needs rebuilding with that correction; awaiting an exception to the latest no-local-C-build instruction. Until rebuilt, keep extra encryption enabled in the Mac app. iOS has not been rebuilt or device-tested for these changes. See the host record for installation details; a live Mac session with the new options remains to be verified.

## October 26: live Mac timing and server-host access

Before the fix, mDNSResponder recorded the tunnel process starting A/AAAA queries at 13:26:08.185 Denver; the native connection resumed at 13:26:38.189. Authentication/network setup followed in under a second. Endpoint resolution outside the tunnel measured 0.004–0.010 seconds. Apple now resolves before full-tunnel activation and supplies a numeric dial address to C while retaining the original Host, TLS hostname verification, SNI and certificate pins. Its network settings use the actual endpoint IP rather than `10.77.0.1`. This removes the observed startup DNS stall; no cryptography was weakened.

User live reconnect: macOS start request **13:42:23.238**, provider start **13:42:23.644**, native transport ready **13:42:26.218**, authenticated **13:42:26.416**, network configured/connected **13:42:26.665**. Thus about **3.4 seconds overall**, **0.2 seconds for network authentication**, and **0.25 seconds to apply network settings**. The remaining startup time is native initialization. Logs: `build/apple-dns-fix-live-timing.log` (read with `log show --info`).

The repaired firewall and native gateway policy passed real split/full namespace tests covering server tunnel/WAN addresses, allowed/blocked host ports, ping, NAT and zero-capability server threads. Three native CTests, 25 Python installer/network tests, Swift numeric IPv4/IPv6 resolver tests, and all six transport/pinning cases with pre-resolved addresses passed. The signed Mac app/native framework rebuilt with the user's explicit local C-build exception and signature verification passed. iOS was not rebuilt.

Live connected Mac checks succeeded: gateway ping (2/2), normal public-host HTTPS 200, gateway-directed HTTPS with the proper hostname/certificate 200, and SSH with server-observed peer `10.77.0.3`. The deployment now allows only host TCP 85/443 and rate-limited ping on Alta. See [the host record](ALTA-HOST-CHANGES.md) for exact changes and backups. IPv6 transport, roaming and Internet throughput are not validated by these checks.

## October 26: pasted JSON client fix

The Apple textbox previously passed downloaded profile JSON to `xpn_enroll`, which rejects anything not beginning with an HTTPS invitation URL before making a request. The shared Mac/iOS input handler now distinguishes pasted profiles from invitation links, validates profiles through the native validator, and saves them to Keychain. The action is labeled **Add connection**. JSON file import has the user-selected read-only sandbox entitlement.

Swift regression tests passed for profile import without an enrollment request, trimmed invitation redemption exactly once, malformed JSON, unsupported input, oversized input and embedded NUL rejection. The signed macOS Debug app rebuilt successfully with the existing native XCFramework (no C compilation); its app/extension signatures verified. Log: `build/apple-json-import-build.log`. A real user-profile Keychain import and VPN connection have not been performed as part of this fix; the iOS app has not been rebuilt.

Read-only checks found Alta control/native services active and the HTTPS join page returning 200. No server configuration, device credentials, invitation state or source files on Alta were changed during this diagnosis.

## October 26: in-place, single-account validation

Automated installer: 23 Python installer/network tests passed locally and on Alta. They cover unchanged reruns (no file/build/service mutations), targeted nginx-file repair, dependency-aware restarts, no-op health-check failures, nginx readiness retries, permission-only corrections, rollback, preview, secret preservation and config generation. Systemd/nginx configuration validation passed on Alta.

The live installer now completed on Alta. Its first immediate post-reload HTTPS check returned 404 and triggered configuration rollback; adding bounded readiness retries resolved the nginx worker transition. The successful run started/enabled all services, and an XPN-only HTTPS guard was applied with just an nginx reload. A subsequent real no-op run left 512 files' contents/timestamps/inodes/modes, service identities, interface ifindex and nftables rules unchanged. Public console returned 200, unauthenticated admin API 401, and plain-HTTP XPN console/WebSocket paths 404. Both daemons run as UID 996/GID 998 with zero effective capabilities and no-new-privileges. No additional APT packages/accounts were needed. See [host changes](ALTA-HOST-CHANGES.md) for every run/report and the retained credentials/database. Live Mac/iOS tunnel use and Internet throughput remain untested.

CI follow-up: GitHub Actions run `40329489049` at `4d46eb2` passed the Node job but failed the native TUN fixture startup. The fixture is tracked in that commit. Reproduced the same Node `MODULE_NOT_FOUND` on Alta when the unprivileged service account cannot traverse the checkout's private parent directory. The CI step now uses the read-only mount wrapper. The harness explicitly checks fixture readability and detects early child exits; local readiness checks and Alta's inaccessible-path negative case plus wrapped real TUN transfers passed. The updated workflow has not yet been pushed or rerun on GitHub.

Builds/tests now run in `/root/repo/xpn`, with Node under `build/tools` and fresh native outputs under `build/native`. Both Node and C use `xpn`. Ten backend tests, three native CTests, explicit privilege/root-refusal tests, all six nginx pinning cases, hybrid/custom-SNI, five network lifecycle tests and the real split/full TUN/NAT harness passed. Connected native threads have no capabilities and cannot gain privileges. Synthetic loopback transport measured approximately 82–86 Mbps per direction in this run.

The previous `/opt/xpn-test` workspace was archived under `build/host-migration-2026-10-26` and removed; the unused `xpn-packet` account/group was removed. Private read-only checkout access was tested with a temporary systemd unit, without loosening `/root` permissions. That migration validation did not deploy persistent services or change live nginx; the subsequent installer deployment is recorded above. See [host changes](ALTA-HOST-CHANGES.md) for the exact operational record. Earlier entries below retain the historical two-account test results.

## Alta and portable Mac build follow-up

- Alta: release `xpnd` compiled with GCC 15.2, OpenSSL 3.5.5, libwebsockets 4.3.5, Jansson 2.14 and curl 8.18.0. All three native CTests passed. Explicit root/saved-root/root-group/retained-capability rejection and clean privilege inheritance passed, including the unprivileged `xpn-packet` invocation and production CLI root refusal.
- Ten backend tests and JavaScript syntax checks passed with a private Node 24.22.1 runtime. System Node 22 was preserved.
- All six nginx transport cases passed as `xpn-packet`: legacy CA trust, custom SNI, wrong pin, trusted certificate with wrong pin, pin rotation and pin-only. Custom-SNI hybrid crypto also passed. The synthetic loopback benchmark measured 83.3–99.3 Mbps per direction on Alta; **200 Mbps has not been demonstrated on this host**.
- The new `native/tests/tun-integration.py` passed on Alta: production C server, separate unprivileged Node/packet accounts, matching pin with unrelated certificate hostname and custom SNI, real TUN interfaces, split/full routes, nftables NAT, and byte-for-byte 1 MiB HTTP transfers. Every connected server thread had the packet UID, zero capability masks and no-new-privileges. All network changes were confined to disposable namespaces.
- Mac: both static dependency SDKs and the universal native XCFramework were built successfully with OpenSSL 3.6.5, libwebsockets 4.5.8, curl 8.23.0 and Jansson 2.15.1. Fixed explicit macOS architecture selection and separated manifest install roots to prevent one architecture pruning another.
- Native tests linked against that exact framework passed on Apple Silicon, including custom-SNI nginx PSK/hybrid tests (799.5/780.7 Mbps per direction respectively). The unsigned app and packet tunnel extension compiled and linked successfully in both the ARM Debug and universal ARM/Intel Release builds. This is compilation/transport evidence, not an operating-system VPN activation test.
- Signing follow-up: all four targets now select Soundvision Technologies LLC team PHZ3789J83 in the ignored local overlay. After device registration and local Keychain authorization, the macOS Debug build succeeded. `codesign --verify --deep --strict` passed; both app and extension contain the Packet Tunnel entitlement and matching `PHZ3789J83.com.jeffhansen.xpn.shared` Keychain group. The signed client launched successfully and displayed its enrollment screen. A live macOS tunnel remains untested: no persistent XPN server has been started on Alta. No iOS device run was performed.
- Build/test files are under `build/` locally and `/opt/xpn-test/` remotely. Alta's original checkout and live nginx routes were preserved. Build dependencies and `xpn`/`xpn-packet` accounts were installed; persistent XPN services were not. `systemd-analyze verify` found the expected absent production executable paths, so production unit startup remains untested.

## Passed locally

- Ten Node tests: unique keys, encrypted storage/enrollment, invitation replacement/expiry/single use, revocation, key rotation, route/mode validation, API authorization/origins, URL prefixes, QR email construction via a stub, production startup, private Unix socket permissions and DB permissions, plus SNI/pin validation, defaults, v2 profile enrollment and existing-device trust updates.
- JavaScript syntax checks, Python launcher compilation, shell syntax checks; npm audit reported zero vulnerabilities.
- Native C library compilation with warnings as errors, AddressSanitizer and UndefinedBehaviorSanitizer; in-memory mutual TLS-PSK handshake, wrong-key rejection, framing, source spoofing rejection and split-route enforcement.
- Certificate unit tests: exact leaf matching, replacement certificates using the same key, old/new rotation pins, expired and future certificates, malformed SNI/pins and profile-version downgrade rejection.
- Real nginx pinning cases: custom SNI `app.jeffhansen.com` selects an untrusted self-signed certificate for `certificate.example.invalid`, while HTTP Host remains `localhost`; matching pins succeed, wrong pins fail before HTTP upgrade even with otherwise trusted certificates, the second rotation pin succeeds, and pinned/default-SNI and legacy CA verification work.
- Custom SNI plus matching pin also passes with the inner ML-KEM hybrid handshake. Browser smoke test with a temporary in-memory database verifies missing-pin rejection, saving existing-device trust, fresh QR generation and persisted editor values.
- Real nginx integration in fast PSK and ML-KEM hybrid modes: trusted HTTPS enrollment, Node-to-C encrypted profile interoperability, WSS upgrade under `/xpn/vpn`, inner TLS mutual authentication, IPv4 packet round trips, credential refresh and active-session revocation.
- An idle hybrid connection remained usable after 25 seconds with nginx's proxy read timeout set to 23 seconds, exercising TLS KeyUpdate keepalives.
- Swift app/provider typechecking for macOS and iOS simulator, XcodeGen generation, and unsigned macOS app/provider linking against the C library and locally installed dependencies.

Native test libraries: OpenSSL 4.0.3, libwebsockets 5.0.0, Jansson 2.15.1; nginx 1.31.8. These are locally installed versions. Ubuntu CI intentionally covers the distribution's older supported APIs as well, but that workflow has not run yet.

## Local performance observation

Release C code, 10,000 synthetic IPv4 packets of 1,400 bytes, a window of 32 outstanding round trips, simultaneous forward/reverse traffic, inner TLS plus outer WSS through nginx:

| Mode | IP bytes per direction / elapsed time |
| --- | ---: |
| 256-bit PSK + X25519 + ChaCha20-Poly1305 | 876.8 Mbps |
| 256-bit PSK + X25519MLKEM768 + ChaCha20-Poly1305 | 891.2 Mbps |

This is a software transport baseline on loopback. It excludes TUN reads/writes, kernel packet forwarding/NAT, real TCP/UDP application behavior, WAN latency/loss, concurrent users and mobile power constraints. The difference between these two short measurements is not evidence of a steady-state performance advantage for either handshake mode. It does show that the implemented transport can exceed 200 Mbps in this local synthetic workload. AWS/device acceptance remains unmeasured.

Reproduce on a machine with native build dependencies, Node dependencies, nginx and OpenSSL installed:

```sh
cmake -S native -B /tmp/xpn-build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/xpn-build
ctest --test-dir /tmp/xpn-build --output-on-failure
node server/native-integration.mjs /tmp/xpn-build/test_transport
XPN_TEST_PINNING=sni node server/native-integration.mjs /tmp/xpn-build/test_transport
XPN_TEST_MODE=hybrid XPN_TEST_IDLE_SECONDS=25 node server/native-integration.mjs /tmp/xpn-build/test_transport
```

The hybrid command requires OpenSSL 3.5+. `OPENSSL_BIN` and `NGINX_BIN` can select non-default binary paths. On macOS, ensure CMake's `OPENSSL_ROOT_DIR` matches the OpenSSL major version used by libwebsockets; mixing different libssl major versions in one process is unsupported.

## Not validated yet

- Production systemd deployment, host firewall integration and real WAN/AWS networking. Ubuntu `xpnd`, TUN and NAT are covered by the isolated Alta tests above.
- Static iOS device/simulator XCFramework slices, iOS signing/provisioning, running the macOS/iOS packet tunnel, and camera/shared-Keychain behavior during enrollment. Mac signing and application launch passed as recorded above.
- macOS 14 runtime compatibility of a properly cross-built release. The local link check used development libraries targeting newer macOS releases and emitted deployment-target warnings.
- End-to-end DNS and IPv6 leak tests, WAN throughput, multiple simultaneous clients, one-hour reconnect behavior, mobile sleep/roaming and failover.
- Independent security review and fuzzing of the complete deployment. Sanitizers and functional tests are useful evidence, not a security audit.

## Local build and packaging helpers

- Local XcodeGen overlay generated successfully with all four expected bundle identifiers, team setting, automatic signing and shared Keychain group. The subsequent signed Mac build used the user's Soundvision team as recorded above.
- Noble and Resolute source preparation completed with locked npm downloads and install scripts disabled. Their upstream `.orig.tar.xz` archives had identical hashes; per-series Debian metadata differed as intended. Private state, Git metadata and Apple SDK artifacts were excluded.
- Five mocked network lifecycle tests passed: starting replaces only the XPN table, stopping removes only the XPN table/interface, repeated stop is harmless, unknown commands change nothing, and new TUN interfaces belong to `xpn-packet`. No host networking was altered.
- Shell/Python syntax and Debian rules dry-run checks passed. These do not validate a Linux `.deb` build or installation. Signed device runs, iOS dependency builds, Debian package builds and a PPA upload remain unperformed.

## Server privilege separation follow-up

The Linux executable checks identities/capabilities and locks down privilege acquisition before initialization. The native unit now shares the unprivileged `xpn` account with Node. It retains capability restrictions and masked database/environment paths; the shared UID does not isolate Node from the packet process. The Linux tests and connected TUN checks passed on Alta as recorded above. Production systemd installation remains pending; use `docs/PRIVILEGE-SEPARATION.md` for deployment verification.

No live SMTP email, PPA upload or GitHub workflow dispatch was performed in this validation session.
