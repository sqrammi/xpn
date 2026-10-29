# XPN

TLS-only VPN implementation with a Node administration service, a **C/OpenSSL/libwebsockets** packet service, Linux TUN client, and SwiftUI macOS/iOS Network Extension client sources. Administration and VPN traffic share an nginx HTTPS virtual host, including deployment under a URL prefix. There is no Rust or Go implementation.

**Status:** development implementation. Linux real-TUN/NAT tests and a signed live macOS connection to Alta pass. Optional inner encryption has native/authentication/transport coverage; iOS device validation and production security review remain outstanding. See [validation results](docs/VALIDATION.md) and [protocol/security boundaries](docs/PROTOCOL.md).

## Included

- Per-device user creation, automatic 256-bit keys, full/split IPv4 policies, DNS selection, revocation and key rotation.
- One-use, 15-minute encrypted QR enrollment; optional SMTP delivery of the QR image.
- Exact SHA-256 certificate pinning with independent TLS SNI on all native clients; configure new or existing devices in the console. See [pinning, custom SNI and certificate rotation](docs/PINNING.md).
- New client sources use one active and one authenticated standby TCP/TLS stream, with measured-latency failover and 15-second TCP keepalive defaults. See [v3 behavior and limits](docs/PROTOCOL.md#activestandby-connections-v3).
- Outer TLS is always on. Client checkboxes independently select extra end-to-end ChaCha20-Poly1305 packet encryption and required hybrid ML-KEM key exchange. Device PSK authentication remains mandatory in single-layer mode; extra encryption stays on by default. PQ requires compatible OpenSSL 3.5+ clients, server and nginx, without fallback.
- Bounded native packet queues, source/policy validation, revocation polling and Linux routing/NAT deployment files.
- Root-only network setup exits before serving clients; one unprivileged `xpn` account for Node and packet services, with privileged native server launches rejected. See [privilege separation](docs/PRIVILEGE-SEPARATION.md).
- Linux camera scanning with `zbarcam`, transactional route setup, full-mode DNS setup and IPv6 leak prevention.
- macOS/iOS camera scanning, JSON import, shared Keychain credentials, full/split route configuration and packet tunnel provider sources.

The nginx WebSocket transport requires native userspace processing; this implementation does not claim OpenVPN DCO compatibility or kernel crypto offload. PSK protection depends on trusted QR/key delivery. The fast mode already uses the requested lightweight cipher. ML-KEM changes handshake work rather than steady-state packet encryption.

## Build and test locally first

- [Deploy from source on alta.jeffhansen.com using its existing nginx certificate](docs/ALTA-DEPLOYMENT.md)
- [Actual Alta host changes: installed packages, files, accounts, tests and cleanup](docs/ALTA-HOST-CHANGES.md)
- [macOS and iOS: Xcode setup, native framework, signing and first run](docs/APPLE-LOCAL.md)
- [Ubuntu Noble/Resolute: separate client/server packages, local deployment and testing, then PPA preparation](docs/LOCAL-TESTING.md)

Ubuntu amd64 client/server packages have been built and tested on Noble and Resolute. See [PPA installation and migration](docs/UBUNTU-PPA.md) and the [release record](docs/PPA-RELEASE-2026-10-27.md). The server requires Node 24.13.1+; XPN is MIT licensed, with dependency notices included.

## Run the Node checks

Requires Node 24.13.1+.

```sh
npm ci --ignore-scripts
npm test
npm run check
```

The test suite uses ephemeral loopback listeners, in-memory SQLite databases and a stub SMTP transport. It never emails anyone. `node:sqlite` currently emits an experimental warning.

## Build native code on remote Linux CI

The workflow in `.github/workflows/checks.yml` installs Ubuntu development dependencies, builds C with AddressSanitizer/UndefinedBehaviorSanitizer, runs the in-memory TLS/packet tests, and exercises encrypted enrollment, WSS packet exchange and revocation through nginx. Push to your own GitHub repository to run it. No workflow has been dispatched by this task; macOS builds/tests were run locally instead.

For a **remote Ubuntu build host**, the equivalent release commands are:

```sh
sudo apt-get update
sudo apt-get install -y cmake ninja-build libssl-dev libwebsockets-dev libjansson-dev libcurl4-openssl-dev
cmake -S native -B /tmp/xpn-release -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/xpn-release
ctest --test-dir /tmp/xpn-release --output-on-failure
sudo cmake --install /tmp/xpn-release
```

Ubuntu 24.04's OpenSSL supports the default fast PSK mode. Hybrid mode needs a vetted OpenSSL 3.5+ build and corresponding libwebsockets build, on server and clients. Local Apple dependency/framework builds are supported; see the step-by-step guide below.

## Deploy on Ubuntu / AWS

With nginx HTTPS already configured, run from your source checkout:

```sh
sudo python3 deploy/install-server.py --url https://your-host/xpn
sudo python3 deploy/install-server.py --show-admin-token
```

The installer builds in place, generates independent admin/database secrets, creates the single `xpn` service account, writes the systemd units and nginx integration, validates configuration, and starts/enables the services. It uses your existing certificate and keeps backend ports on loopback. Reruns preserve credentials, skip unchanged files/builds/services, and repair only what needs updating. Each run prints a root-only `changes.md` report listing the exact paths/actions, with configuration backups and a detailed command log. Use `--plan` for a read-only preview or `--nginx-site /path/to/site` if site selection is ambiguous. See [server installation](docs/ALTA-DEPLOYMENT.md) for options, failure recovery and the Alta command.

Open `https://your-host/xpn/`, unlock using your admin token, create one identity per physical device, and scan its QR. **Email QR** sends only when explicitly selected in the UI; no live email has been sent during implementation. **New QR** replaces the invitation; **Rotate key** replaces the credential and disconnects old sessions; **Revoke** disables the identity.

The console also provides optional [home-to-XPN gateway access](docs/GATEWAY.md) through an existing WireGuard tunnel. Select allowed home subnets, destination devices and ports, then apply immediately without restarting VPN connections. It is disabled by default and persists across reboot. This feature requires server version 0.1.2 or newer.

## Linux client

Install the remote-built native executable, `python3`, `iproute2`, `nftables`, `systemd-resolved` and, for camera scanning, `zbar-tools`.

```sh
python3 clients/linux/xpn.py enroll ./my-device.json --scan
sudo python3 clients/linux/xpn.py connect ./my-device.json
```

Pasting an invitation without camera support is available by omitting `--scan`. A JSON profile downloaded from `/join` can be used directly; protect its file permissions with `chmod 600`. The C `xpnd enroll` command also exists, but passing secret invitations as shell arguments can expose them in history/process listings.

The launcher installs only its own interface/routes/firewall table and restores them on a normal exit or handled signal. Full mode uses IPv4 default halves, DNS through `systemd-resolved`, and an output firewall that permits the tunnel, loopback and the HTTPS endpoint. It blocks IPv6. Split mode keeps other traffic and DNS local; configure the allowed subnets when creating the device in the console. An abrupt kill or machine crash can leave temporary client routes/firewall state; inspect/remove the process-specific `xpn<PID>` interface and `inet xpn_<PID>` nftables table during recovery. `xpn connect` retries failures indefinitely with randomized exponential backoff; `--no-retry` makes one attempt. For boot startup and installation with the current PPA, use the [Linux client service setup](docs/LINUX-CLIENT-SERVICE.md). IPv6 endpoints and roaming are not supported by this launcher.

## Apple clients

See [clients/apple/README.md](clients/apple/README.md) for the signing team, bundle IDs, Keychain group, native XCFramework inputs and XcodeGen project. Supply your Apple team and SMTP credentials through your own signing/secret configuration; they do not need to be pasted into chat.

## Validate the throughput target

After native CI and functional tests pass, use a separate permitted VPC host as an iperf3 endpoint (this measures forwarding/NAT as well as tunnel transport):

```sh
# Separate VPC test host:
iperf3 -s
# Connected VPN client, using that host's permitted address:
iperf3 -c 10.20.1.10 -P 4 -t 30
iperf3 -c 10.20.1.10 -P 4 -t 30 -R
```

The local native/WSS/nginx loopback test measured approximately **877 Mbps per direction** in PSK mode and **891 Mbps per direction** in hybrid mode during simultaneous synthetic packet round trips. These measurements exclude TUN, kernel routing, WAN conditions and physical devices; they are not an AWS capacity result.

Measure single-stream and parallel throughput, simultaneous clients, CPU for nginx and xpnd, latency/loss and mobile battery use. Repeat on a lossy path to measure TCP-over-TCP behavior. Target acceptance is at least 200 Mbps in both directions on your chosen EC2 instance and supported clients, with measured headroom; AWS/device acceptance has **not** been established. Multi-core sharding, mobile automatic reconnect, production administration SSO, native dependency supply-chain review and an independent protocol/implementation security audit remain future work.
