# XPN protocol v1

## Transport

```text
Native client                          Ubuntu server
TUN / Network Extension               kernel TUN -> routing -> NAT
   |                                      |
C / OpenSSL TLS 1.3 (external PSK) <-> C / OpenSSL TLS 1.3 (external PSK)
   |                                      |
WebSocket binary frames <-- nginx --> WebSocket binary frames (loopback)
   |
Outer TLS 1.3 on TCP 443
```

There is no UDP listener. nginx routes `/xpn/vpn` to C on loopback port 3001 and `/xpn/` to Node on loopback port 3000. Prefixes are configurable consistently in Node's `PUBLIC_URL`, nginx locations, and the native server path. `Sec-WebSocket-Protocol` is `xpn-v1`. WebSocket compression is disabled; OpenSSL TLS bytes are opaque payloads, with no dependency on WebSocket message boundaries. nginx terminates the outer TLS connection, but not the inner TLS session.

The server rejects browser Origins on the tunnel endpoint; the administration UI does not carry packets. Enrollment HTTPS always uses normal CA and hostname verification. VPN WSS uses either normal verification (profile v1) or mandatory exact SHA-256 leaf certificate pins (profile v2). A pinned profile may independently override TLS SNI while preserving the endpoint's DNS/TCP destination and HTTP Host. Pinned mode enforces certificate validity dates and proof of private-key possession but replaces CA/name trust; it never falls back after a pin mismatch. Custom SNI without a pin is rejected. See [configuration and rotation](PINNING.md). Inner TLS uses PSK-only authentication and has no certificate fallback. The wire protocol remains v1 for either profile version.

## Cryptography

Every device receives an independent random 32-byte PSK. OpenSSL implements **TLS 1.3 external PSK** with its session callbacks, not an application-specific cipher/nonce protocol. Cipher suite: `TLS_CHACHA20_POLY1305_SHA256` only. Key exchange in fast `psk` mode: X25519 with PSK-DHE. Optional `hybrid` mode: X25519MLKEM768 with the same PSK and data cipher; this requires OpenSSL 3.5+ on both peers and fails closed if unavailable or not negotiated. The server enforces the profile's mode after the handshake. Neither mode sends data before Finished authenticates the PSK on both sides. Connections require a negotiated group and external PSK acceptance. Session tickets, 0-RTT, certificate fallback, TLS <1.3, and PSK-only/no-DHE key exchange are disabled.

A uniformly random 256-bit PSK supplies symmetric authentication and protection against recorded-traffic decryption even if a future quantum adversary can break X25519. This depends on keeping that PSK secret and on the usual TLS/AEAD assumptions; it is not a security certification. **Fast mode does not provide post-quantum forward secrecy after later PSK compromise:** an adversary who obtains the PSK and can break recorded X25519 exchanges could recover old sessions. Hybrid mode adds ML-KEM for that threat model. ChaCha20-Poly1305 is already used in both modes, so there is no weaker cipher switch needed to obtain the requested lightweight fast path. ML-KEM affects connection setup rather than the per-packet cipher cost.

TLS traffic keys update after approximately 1 GiB sent and every 20 seconds for idle keepalive. TLS KeyUpdate is not a new DH/KEM exchange and cannot repair compromised PSKs. Sessions close after one hour; reconnect performs a new handshake. Use **Rotate key** to replace a device's PSK and issue a new invitation; this invalidates old enrollment and disconnects the old device on the next credential check. Rotate on device loss, suspected disclosure, or reassignment; a 30-day manual rotation schedule is a reasonable starting operating policy. **New QR** alone replaces the invitation, not the device PSK.

## Enrollment and storage

Admin authentication is a high-entropy bearer token held only in the page's JavaScript memory. API authorization does not use cookies. Cross-origin requests are rejected. Deploy the admin console behind your existing access-control layer if you require SSO/MFA. The console supports a single administrator token in this version.

Creating a user/device allocates an address from `10.77.0.2`–`10.77.0.254`, creates its PSK, and stores the PSK encrypted with AES-256-GCM under the deployment's master key. The SQLite DB stores policies and audit events. Keep DB/WAL files and the master key protected separately; backup recovery requires the master key. The native process obtains an active credential snapshot through a protected Unix socket. The control socket belongs to `xpn:xpn` with mode `0660` inside a `0710` directory. Both services run as `xpn`, so these permissions isolate credentials from other host users, not from the packet process. The native systemd unit additionally masks the database/environment paths, but the shared UID is not an isolation boundary between Node and C. Loopback admin access alone cannot retrieve native secrets without the admin token and a valid invitation.

An invitation is `https://host/xpn/join#token=<random-32-bytes>&key=<random-32-bytes>`. The wrapping key is held in the fragment, encoded into the QR, and never sent to the enrollment HTTP endpoint. Node stores only the token hash and an AES-256-GCM encrypted profile. Enrollment atomically consumes the token and returns ciphertext; the client decrypts locally, validates its structure, and saves its PSK. Tokens expire after 15 minutes, are single-use, and are invalidated on revocation, key rotation, or issuing another invitation. Redeeming through the browser downloads a private JSON credential file rather than a native installation.

QR delivery must be trusted. Email sends the full bootstrap secret and is only as secure as SMTP and the recipient's mailbox; it does not automatically make email delivery post-quantum secure. Prefer an out-of-band camera scan for a strong bootstrap threat model. A quantum attacker able to alter the web admin application's delivered JavaScript or recover a bearer admin token is outside the inner tunnel's guarantee; use a trusted administration channel and PQ-capable outer TLS infrastructure when required. The inner PSK cannot protect a compromised endpoint or trusted administrator.

## Packets and resource bounds

Inside TLS, each packet is prefixed by a two-byte unsigned network-order length. Length must be 20–1400 bytes and match the IPv4 total length. IPv4 options are rejected, including source-routing options. IPv6 is not transported in v1; full clients capture/drop or firewall IPv6, whereas split mode leaves nonselected traffic on the local network. Split mode leaves system DNS unchanged; choose an explicit DNS policy before adding private DNS requirements.

The server checks source address against the authenticated device's /32 and destination against the server-managed full/split policy. It rejects tunnel subnet/host access, link-local metadata, loopback, multicast, and zero-net destinations. The deployment firewall additionally blocks traffic to the VPN host, peer-to-peer traffic, and unsolicited inbound traffic. Devices cannot expand their access by editing the local profile. Denied packets close the session. User identities currently correspond to one device each, with one concurrent authenticated session per identity.

Queues: 512 packets per instance and 128 KiB TLS output/input per connection. Slow peers cause packet drops rather than unbounded queue growth. Native callbacks and TLS state run on one libwebsockets event thread. The Linux TUN reader is a separate thread, and credential refresh is a background thread; crypto and packet processing never run in Node. The server admits at most 128 concurrent connections (including pending handshakes); pending authentication expires after 10 seconds. Up to 253 identities may be provisioned. Credential snapshots refresh roughly once a second, with a one-second request timeout; revocation is checked on one-second connection timers. Snapshot errors clear credentials and close sessions rather than retaining stale permissions.

## Performance boundaries

This is a native userspace data plane. It is **not OpenVPN DCO**, does not provide kernel encryption offload, and cannot inherit OpenVPN's kernel protocol. Linux kernel TUN, TCP/IP, routing and NAT remain in the kernel. WebSocket, inner TLS, and packet framing run in C/OpenSSL; nginx also handles the outer TLS layer. Apple packet tunnels use Network Extension rather than an installable iOS kernel driver.

TCP-over-TCP head-of-line blocking remains possible on lossy paths. The inner and outer TLS layers add work. Local synthetic packet round trips through the native service and nginx measured about 877 Mbps per direction (PSK) and 891 Mbps (hybrid), but no AWS/TUN/device throughput result has been measured. This version has neither multi-queue TUN/sharded event loops nor zero-copy offload. Benchmark on your actual instance/clients before making a capacity commitment. A kernel driver cannot transparently remove those constraints from nginx HTTP WebSocket proxying.

## References

- [nginx WebSocket proxying](https://nginx.org/en/docs/http/websocket.html)
- [TLS 1.3](https://www.rfc-editor.org/rfc/rfc8446.html)
- [External PSK usage guidance](https://www.rfc-editor.org/rfc/rfc9257.html)
- [OpenSSL external PSK callbacks](https://docs.openssl.org/3.0/man3/SSL_CTX_set_psk_client_callback/)
- [libwebsockets threading and writable callbacks](https://github.com/warmcat/libwebsockets/blob/main/READMEs/README.coding.md)
- [Apple Network Extensions entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.networking.networkextension)

## Server privileges

The root network helper exits after configuring TUN/routing. Node runs as `xpn`, and all native connection handlers run as `xpn` before authentication. The Linux server executable rejects privileged launches and sets `no_new_privs` before library initialization or threads. Connections share one process and its credential cache; this is not per-client memory isolation. See [privilege separation](PRIVILEGE-SEPARATION.md) for installation, migration and checks.
