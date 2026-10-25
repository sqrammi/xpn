# Validation record

Date: 2026-10-25. Host: Apple Silicon macOS development machine.

## Passed locally

- Seven Node tests: unique keys, encrypted storage/enrollment, invitation replacement/expiry/single use, revocation, key rotation, route/mode validation, API authorization/origins, URL prefixes, QR email construction via a stub, production startup, private Unix socket permissions and DB permissions.
- JavaScript syntax checks, Python launcher compilation, shell syntax checks; npm audit reported zero vulnerabilities.
- Native C library compilation with warnings as errors, AddressSanitizer and UndefinedBehaviorSanitizer; in-memory mutual TLS-PSK handshake, wrong-key rejection, framing, source spoofing rejection and split-route enforcement.
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
XPN_TEST_MODE=hybrid XPN_TEST_IDLE_SECONDS=25 node server/native-integration.mjs /tmp/xpn-build/test_transport
```

The hybrid command requires OpenSSL 3.5+. `OPENSSL_BIN` and `NGINX_BIN` can select non-default binary paths. On macOS, ensure CMake's `OPENSSL_ROOT_DIR` matches the OpenSSL major version used by libwebsockets; mixing different libssl major versions in one process is unsupported.

## Not validated yet

- Ubuntu `xpnd` executable, real `/dev/net/tun`, nftables/NAT/systemd operation and AWS networking.
- Full portable/static Apple XCFramework build across iOS device/simulator and both macOS architectures; app signing, provisioning, extension entitlement activation and camera/Keychain behavior on physical devices.
- macOS 14 runtime compatibility of a properly cross-built release. The local link check used development libraries targeting newer macOS releases and emitted deployment-target warnings.
- End-to-end DNS and IPv6 leak tests, WAN throughput, multiple simultaneous clients, one-hour reconnect behavior, mobile sleep/roaming and failover.
- Independent security review and fuzzing of the complete deployment. Sanitizers and functional tests are useful evidence, not a security audit.

The Git repository was initialized locally. No remote repository, cloud deployment, live SMTP email or GitHub workflow dispatch was performed.
