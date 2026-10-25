# XPN

TLS-only VPN implementation with a Node administration service, a **C/OpenSSL/libwebsockets** packet service, Linux TUN client, and SwiftUI macOS/iOS Network Extension client sources. Administration and VPN traffic share an nginx HTTPS virtual host, including deployment under a URL prefix. There is no Rust or Go implementation.

**Status:** initial implementation, not a validated production release. After local C builds were explicitly authorized, the C library passed sanitizer tests and real nginx/WSS integration tests in both PSK and ML-KEM hybrid modes. Seven Node tests pass. The unsigned macOS app/provider build and link, and both iOS Swift targets typecheck. No Linux TUN/routing or signed Apple device test has run. The full portable Apple dependency SDK workflow still needs a successful CI run. See [Apple integration requirements](clients/apple/README.md), [validation results](docs/VALIDATION.md), and [protocol/security boundaries](docs/PROTOCOL.md).

## Included

- Per-device user creation, automatic 256-bit keys, full/split IPv4 policies, DNS selection, revocation and key rotation.
- One-use, 15-minute encrypted QR enrollment; optional SMTP delivery of the QR image.
- TLS 1.3 PSK mutual authentication and ChaCha20-Poly1305 inside WSS, independent of nginx's TLS termination. Fast PSK mode is the default; optional PSK + ML-KEM requires OpenSSL 3.5+.
- Bounded native packet queues, source/policy validation, revocation polling and Linux routing/NAT deployment files.
- Linux camera scanning with `zbarcam`, transactional route setup, full-mode DNS setup and IPv6 leak prevention.
- macOS/iOS camera scanning, JSON import, shared Keychain credentials, full/split route configuration and packet tunnel provider sources.

The nginx WebSocket transport requires native userspace processing; this implementation does not claim OpenVPN DCO compatibility or kernel crypto offload. PSK protection depends on trusted QR/key delivery. The fast mode already uses the requested lightweight cipher. ML-KEM changes handshake work rather than steady-state packet encryption.

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

Ubuntu 24.04's OpenSSL supports the default fast PSK mode. Hybrid mode needs a vetted OpenSSL 3.5+ build and corresponding libwebsockets build, on server and clients. The Apple packaging script is also CI-only.

## Deploy on Ubuntu / AWS

Review and adapt the included configurations to the existing host before enabling services. This section contains deployment instructions; no AWS resources have been created or changed.

1. Install Node 24.13.1+, nginx, `iproute2`, `nftables`, and the native runtime dependencies. Install the tested release `xpnd` binary at `/usr/local/bin/xpnd`. Place this source tree at `/opt/xpn` and run `npm ci --omit=dev --ignore-scripts` there.
2. Create the local service identity with `sudo useradd --system --home /var/lib/xpn --shell /usr/sbin/nologin xpn`. Keep application source owned by your deployment account/root, not writable by `xpn`.
3. Copy `deploy/xpn.env.example` to `/etc/xpn.env`, mode **0600**, owned by root. Set `PUBLIC_URL` to the final HTTPS origin and prefix. Generate separate values with `openssl rand -hex 32` for `MASTER_KEY` and `ADMIN_TOKEN`. Configure your SMTP URL/from address if desired; the backend requires TLS. Do not commit secrets.
4. Copy the three `deploy/xpn-*.service` files to `/etc/systemd/system/`. Mark `/opt/xpn/deploy/network.sh` executable. Review `deploy/network.sh` for the actual outbound interface and existing firewall. It creates `xpn0`, enables IPv4 forwarding and manages only its own nftables table; it does not flush your other rules. Additional existing FORWARD-drop policies must also allow the VPN traffic.
5. Adapt `deploy/nginx.conf` with your hostname/certificate. Put its `map` and rate zones in nginx's `http` context and merge the server/locations with your existing virtual host. Ensure `PUBLIC_URL`, nginx's prefix, and `xpn-native.service`'s path agree. Keep ports 3000/3001 and the control socket private. Test configuration using `sudo nginx -t` before reloading.
6. Enable with `sudo systemctl daemon-reload`, then `sudo systemctl enable --now xpn-network xpn-control xpn-native`, and reload nginx. Check `journalctl -u xpn-control -u xpn-native`. A systemd restart of the control service can disconnect active sessions as a fail-closed measure.
7. Allow inbound TCP 443 in the instance security group; keep SSH restricted. No UDP or backend ports need public access. This NAT design does not require advertising client routes in the VPC. If you replace NAT with VPC routing, configure route tables and EC2 source/destination checks accordingly. Keep instance metadata inaccessible to VPN clients (the supplied policy denies link-local access).

Open `https://your-host/xpn/`, unlock using your admin token, create one identity per physical device, and scan its QR. **Email QR** sends only when explicitly selected in the UI; no live email has been sent during implementation. **New QR** replaces the invitation; **Rotate key** replaces the credential and disconnects old sessions; **Revoke** disables the identity.

## Linux client

Install the remote-built native executable, `python3`, `iproute2`, `nftables`, `systemd-resolved` and, for camera scanning, `zbar-tools`.

```sh
python3 clients/linux/xpn.py enroll ./my-device.json --scan
sudo python3 clients/linux/xpn.py connect ./my-device.json
```

Pasting an invitation without camera support is available by omitting `--scan`. A JSON profile downloaded from `/join` can be used directly; protect its file permissions with `chmod 600`. The C `xpnd enroll` command also exists, but passing secret invitations as shell arguments can expose them in history/process listings.

The launcher installs only its own interface/routes/firewall table and restores them on a normal exit or handled signal. Full mode uses IPv4 default halves, DNS through `systemd-resolved`, and an output firewall that permits the tunnel, loopback and the HTTPS endpoint. It blocks IPv6. Split mode keeps other traffic and DNS local; configure the allowed subnets when creating the device in the console. An abrupt kill or machine crash can leave temporary client routes/firewall state; inspect/remove the process-specific `xpn<PID>` interface and `inet xpn_<PID>` nftables table during recovery. IPv6 endpoints and automatic reconnect/roaming are not supported by this launcher.

## Apple clients

See [clients/apple/README.md](clients/apple/README.md) for the signing team, bundle IDs, Keychain group, native XCFramework inputs and XcodeGen project. Supply your Apple team and SMTP credentials through your own signing/secret configuration; they do not need to be pasted into chat.

## Validate the throughput target

After native CI and functional tests pass, use a separate permitted VPC host as an iperf3 endpoint (the VPN server's own tunnel-host address is deliberately blocked):

```sh
# Separate VPC test host:
iperf3 -s
# Connected VPN client, using that host's permitted address:
iperf3 -c 10.20.1.10 -P 4 -t 30
iperf3 -c 10.20.1.10 -P 4 -t 30 -R
```

The local native/WSS/nginx loopback test measured approximately **877 Mbps per direction** in PSK mode and **891 Mbps per direction** in hybrid mode during simultaneous synthetic packet round trips. These measurements exclude TUN, kernel routing, WAN conditions and physical devices; they are not an AWS capacity result.

Measure single-stream and parallel throughput, simultaneous clients, CPU for nginx and xpnd, latency/loss and mobile battery use. Repeat on a lossy path to measure TCP-over-TCP behavior. Target acceptance is at least 200 Mbps in both directions on your chosen EC2 instance and supported clients, with measured headroom; AWS/device acceptance has **not** been established. Multi-core sharding, automatic reconnect, production administration SSO, native dependency supply-chain review and an independent protocol/implementation security audit remain future work.
