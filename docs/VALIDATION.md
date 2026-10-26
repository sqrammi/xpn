# Validation record

Date: 2026-10-25. Hosts: Apple Silicon macOS development machine and alta.jeffhansen.com (Ubuntu 26.04.1 Resolute, x86-64).

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

The Linux executable checks identities/capabilities and locks down privilege acquisition before initialization. The native unit uses a separate `xpn-packet` account, with group-only control socket access and no database/environment-file access. The Linux tests and connected TUN checks passed on Alta as recorded above. Production systemd installation remains pending; use `docs/PRIVILEGE-SEPARATION.md` for deployment verification.

No live SMTP email, PPA upload or GitHub workflow dispatch was performed in this validation session.
