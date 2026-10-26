# XPN protocols v1, v2 and v3

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

There is no UDP listener. nginx routes `/xpn/vpn` to C on loopback port 3001 and `/xpn/` to Node on loopback port 3000. Prefixes are configurable consistently in Node's `PUBLIC_URL`, nginx locations, and the native server path. Legacy clients use `Sec-WebSocket-Protocol: xpn-v1`; clients selecting encryption options use `xpn-v2`. WebSocket compression is disabled. V1 carries opaque inner TLS bytes; v2 multiplexes inner TLS and optional raw IP records as described below. Neither depends on WebSocket message boundaries. nginx terminates the outer TLS connection, but not the inner TLS session.

The server rejects browser Origins on the tunnel endpoint; the administration UI does not carry packets. Enrollment HTTPS always uses normal CA and hostname verification. VPN WSS uses either normal verification (profile v1) or mandatory exact SHA-256 leaf certificate pins (profile v2). A pinned profile may independently override TLS SNI while preserving the endpoint's DNS/TCP destination and HTTP Host. Pinned mode enforces certificate validity dates and proof of private-key possession but replaces CA/name trust; it never falls back after a pin mismatch. Custom SNI without a pin is rejected. See [configuration and rotation](PINNING.md). Inner TLS uses PSK-only authentication and has no certificate fallback. Profile format versions are independent of the selected wire protocol.

## Client-selectable encryption (v2)

Outer TLS is mandatory; there is no cleartext Internet transport. Apple clients expose three checkboxes:

| Control | Behavior |
| --- | --- |
| TLS encryption (always on) | Checked and locked; v2 requires TLS 1.3 to nginx. |
| Additional encryption (ChaCha20-Poly1305) | Checked by default. Encrypts packet data again, end to end between native client and native server. Unchecking removes this per-packet encryption pass. |
| Require post-quantum key exchange (ML-KEM) | Requires `X25519MLKEM768` in both outer TLS and the PSK authentication channel. Connection fails if unavailable; no classical fallback. |

Selections are stored locally per device and take effect on reconnect. A server profile with `mode: hybrid` requires both optional controls and refuses client downgrades. A `psk` profile allows the client to select either packet-encryption mode and optionally require PQ. Existing profiles retain extra encryption by default; no credentials are reissued by toggling these controls. Legacy clients keep using v1 and their provisioned mode. New option-aware clients require the updated server; they do not silently retry a different mode against an old server.

Even with inner packet encryption disabled, an OpenSSL TLS 1.3 external-PSK handshake mutually authenticates the device and native server. The short control channel remains encrypted, including keepalive/key-update messages. **Only packet data bypasses that inner TLS layer.** It is encrypted once by outer TLS. nginx can see those decrypted IP packets, and the loopback hop to the native server carries them without encryption. Keep this backend bound to loopback on the nginx host. Certificate pinning, custom SNI, expiry checks, source/routing policy, revocation and connection limits still apply.

In single-layer mode, confidentiality depends on outer TLS. Requiring ML-KEM provides hybrid post-quantum key agreement; it does not convert RSA/ECDSA certificate signatures into post-quantum signatures. It also does not keep packet contents secret from nginx. Keep additional encryption enabled for end-to-end PSK confidentiality independent of nginx's certificate/key-exchange trust. The 256-bit PSK authenticates single-layer sessions but is not mixed into their **outer** data-encryption keys.

V2 selects WebSocket subprotocol `xpn-v2`. A record is one type byte and a two-byte big-endian payload length. Type 0 carries 1–16384 bytes of inner TLS records; type 1 carries one 20–1400-byte IPv4 packet. Records may span/coalesce WebSocket callbacks; a bounded incremental parser handles fragmentation. Type 1 is rejected before authentication or when inner packet encryption is selected. Type 0 cannot carry application packet data in single-layer mode. Raw output and TLS output share the per-peer output bound, and TLS control records are flushed first. Raw output batches end at record boundaries so a later TLS keepalive cannot interrupt a packet record.

The external PSK identity is `UUID|e`, `UUID|h`, `UUID|t` or `UUID|q`: extra encryption, extra encryption plus required PQ, TLS-only data, or TLS-only data plus required PQ. TLS's PSK binder and Finished transcript authenticate that choice. V1 uses the unchanged 36-byte UUID identity, and identities from one wire version are rejected in the other. Credential snapshots remain the original server policy, separate from each connection's selected mode, so revocation checks cannot accidentally discard or override that policy. No application data is accepted before PSK Finished succeeds.

Linux equivalents: `--inner-encryption off` selects single-layer data, `--inner-encryption on` selects extra encryption, and `--require-pq` requires hybrid key exchange. Omitting these flags retains the provisioned legacy mode. Raw `xpnd client` uses `--outer-only`, `--inner-encryption`, and `--require-pq`.

The sections below describe the retained inner TLS and v1 packet format. In v2, the same inner TLS protects authentication and, only when selected, packet data.

## Active/standby connections (v3)

New Apple and Linux client sources enable two WSS/TLS connections per VPN: one active lane carrying IP packets and one authenticated standby carrying health probes. nginx maintains a corresponding loopback upstream TCP connection for each. Enrollment/API requests are separate, temporary connections. Initial connection starts lane 0 and warms lane 1 after activation. During recovery there can temporarily be fewer than two usable lanes; the client replenishes the spare with bounded retry delays. The public C API enables this with `xpn_client_set_standby(instance, 1)`. Linux `--single-stream` explicitly selects the older one-stream behavior; there is no silent version fallback.

Each lane independently verifies the same certificate pins/SNI and selected TLS/PSK/PQ requirements. V3 extends the authenticated external-PSK identity to `UUID|mode|pair|slot|generation`: a random 128-bit pair ID rendered as 32 lowercase hex characters, slot `0` or `1`, and a nonzero 64-bit generation rendered as 16 hex digits. Exact identity length is 90 bytes. The PSK binder and Finished authenticate every field. A different pair using the same device identity cannot evict a live tunnel. A newer generation can replace its own slot only after authentication; a failed handshake cannot evict it. Both slots must select identical encryption policies. Admission is checked again after Finished to handle concurrent handshakes.

V3 retains v2 outer record framing. Inside inner TLS, a length of 9 identifies a control record (one-byte type and eight-byte big-endian value); packet lengths remain 20–1400. Types 1/2 are probe/reply with an echoed monotonic timestamp. Types 3/4 request/acknowledge activation with an increasing epoch. Controls stay inside inner TLS even when packet data uses only outer TLS. Old or unsolicited activation acknowledgments are rejected. Only the server's acknowledged active lane forwards packets in either direction; late packets from an inactive lane are discarded. The old client connection closes after the replacement's activation acknowledgment, then its slot is refilled. Application TCP connections keep their tunnel IP and NAT state, but queued packets on the old stream can be lost and require TCP retransmission; UDP has no replay guarantee.

Client health probes run about once per second on both lanes, with a 100 ms maintenance timer. Switch when the active lane's measured RTT or outstanding probe reaches **500 ms**, provided the standby responded within 1.5 seconds, has RTT below 500 ms, and is over 100 ms faster. A five-second cooldown after a replacement prevents rapid oscillation; initial activation does not impose that cooldown. A connection closure can trigger immediate promotion without waiting for a latency sample. Activation acknowledgments time out after two seconds, nonresponding probes retire a lane after five seconds, and a ten-second total outage ends the tunnel. Detection time includes probe cadence and scheduling, so this is not a promise of recovery within 500 ms of every network fault. If both paths are slow, do not switch solely because the active lane exceeds the threshold. Both TCP streams usually share the same Internet path: this mitigates a stream-specific stall, not general path congestion.

Resolve the endpoint once before installing tunnel routes and reuse that numeric dial address for replacements; preserve hostname verification, HTTP Host, SNI and pins. This avoids making recovery depend on DNS through the stalled tunnel. No split/full routing policy changes are needed for a lane switch. Revocation still applies to both authenticated lanes and new handshake attempts. The 128-connection server admission bound includes standby and pending connections, reducing capacity to fewer than 64 fully paired devices when allowing recovery headroom. The nginx per-source limit is 16 connections (eight pairs before recovery headroom).

Native sockets explicitly enable `SO_KEEPALIVE`, a **15-second idle timeout**, a **15-second probe interval**, and three unanswered probes; application TLS KeyUpdates also run every 15 seconds. TCP keepalive probes are for idle/dead TCP detection, not subsecond RTT measurement; regular application traffic/probes can prevent the idle timer from firing. The standalone nginx template sets `listen ... so_keepalive=15s:15s:3`; the XPN location enables `proxy_socket_keepalive`. An existing shared nginx listener is not rewritten by the installer: its server-side TCP timer settings remain the host's settings, while XPN client sockets enforce the 15-second values. [nginx documents these separate socket controls](https://nginx.org/en/docs/http/ngx_http_core_module.html#listen).

## Cryptography

Every device receives an independent random 32-byte PSK. OpenSSL implements **TLS 1.3 external PSK** with its session callbacks, not an application-specific cipher/nonce protocol. Cipher suite: `TLS_CHACHA20_POLY1305_SHA256` only. Key exchange in fast `psk` mode: X25519 with PSK-DHE. Optional `hybrid` mode: X25519MLKEM768 with the same PSK and data cipher; this requires OpenSSL 3.5+ on both peers and fails closed if unavailable or not negotiated. The server enforces the profile's mode after the handshake. Neither mode sends data before Finished authenticates the PSK on both sides. Connections require a negotiated group and external PSK acceptance. Session tickets, 0-RTT, certificate fallback, TLS <1.3, and PSK-only/no-DHE key exchange are disabled.

A uniformly random 256-bit PSK supplies symmetric authentication and protection against recorded-traffic decryption even if a future quantum adversary can break X25519. This depends on keeping that PSK secret and on the usual TLS/AEAD assumptions; it is not a security certification. **Fast mode does not provide post-quantum forward secrecy after later PSK compromise:** an adversary who obtains the PSK and can break recorded X25519 exchanges could recover old sessions. Hybrid mode adds ML-KEM for that threat model. ChaCha20-Poly1305 is already used in both modes, so there is no weaker cipher switch needed to obtain the requested lightweight fast path. ML-KEM affects connection setup rather than the per-packet cipher cost.

TLS traffic keys update after approximately 1 GiB sent and every 15 seconds for idle keepalive. TLS KeyUpdate is not a new DH/KEM exchange and cannot repair compromised PSKs. Sessions close after one hour; reconnect performs a new handshake. Use **Rotate key** to replace a device's PSK and issue a new invitation; this invalidates old enrollment and disconnects the old device on the next credential check. Rotate on device loss, suspected disclosure, or reassignment; a 30-day manual rotation schedule is a reasonable starting operating policy. **New QR** alone replaces the invitation, not the device PSK.

## Enrollment and storage

Admin authentication is a high-entropy bearer token held only in the page's JavaScript memory. API authorization does not use cookies. Cross-origin requests are rejected. Deploy the admin console behind your existing access-control layer if you require SSO/MFA. The console supports a single administrator token in this version.

Creating a user/device allocates an address from `10.77.0.2`–`10.77.0.254`, creates its PSK, and stores the PSK encrypted with AES-256-GCM under the deployment's master key. The SQLite DB stores policies and audit events. Keep DB/WAL files and the master key protected separately; backup recovery requires the master key. The native process obtains an active credential snapshot through a protected Unix socket. The control socket belongs to `xpn:xpn` with mode `0660` inside a `0710` directory. Both services run as `xpn`, so these permissions isolate credentials from other host users, not from the packet process. The native systemd unit additionally masks the database/environment paths, but the shared UID is not an isolation boundary between Node and C. Loopback admin access alone cannot retrieve native secrets without the admin token and a valid invitation.

An invitation is `https://host/xpn/join#token=<random-32-bytes>&key=<random-32-bytes>`. The wrapping key is held in the fragment, encoded into the QR, and never sent to the enrollment HTTP endpoint. Node stores only the token hash and an AES-256-GCM encrypted profile. Enrollment atomically consumes the token and returns ciphertext; the client decrypts locally, validates its structure, and saves its PSK. Tokens expire after 15 minutes, are single-use, and are invalidated on revocation, key rotation, or issuing another invitation. Redeeming through the browser downloads a private JSON credential file rather than a native installation.

QR delivery must be trusted. Email sends the full bootstrap secret and is only as secure as SMTP and the recipient's mailbox; it does not automatically make email delivery post-quantum secure. Prefer an out-of-band camera scan for a strong bootstrap threat model. A quantum attacker able to alter the web admin application's delivered JavaScript or recover a bearer admin token is outside the inner tunnel's guarantee; use a trusted administration channel and PQ-capable outer TLS infrastructure when required. The inner PSK cannot protect a compromised endpoint or trusted administrator.

## Packets and resource bounds

Inside TLS, each packet is prefixed by a two-byte unsigned network-order length. Length must be 20–1400 bytes and match the IPv4 total length. IPv4 options are rejected, including source-routing options. IPv6 is not transported in v1; full clients capture/drop or firewall IPv6, whereas split mode leaves nonselected traffic on the local network. Split mode leaves system DNS unchanged; choose an explicit DNS policy before adding private DNS requirements. Apple clients always enable local network access, explicitly setting `excludeLocalNetworks` so directly connected LAN traffic bypasses full-tunnel capture; this also permits system-recognized local IPv6 traffic. Internet IPv6 remains blocked. This exception is unconditional; there is no user toggle. Linux full mode currently retains its stricter local output firewall.

The server checks source address against the authenticated device's /32 and destination against the server-managed full/split policy. It rejects other VPN client addresses, link-local metadata, loopback, multicast, and zero-net destinations. The gateway `10.77.0.1` is reachable when the device routing policy permits it. The deployment firewall permits rate-limited gateway/server ping and selected host TCP ports (22 and 443 by default; installer `--host-tcp-ports` customizes this), and blocks other host traffic, peer-to-peer forwarding and unsolicited inbound traffic. Devices cannot expand their access by editing the local profile. Denied packets close the session. User identities currently correspond to one device each, with one logical tunnel per identity (one v1/v2 lane or the paired v3 lanes).

Queues: 512 packets per instance and 128 KiB TLS output/input per connection. Slow peers cause packet drops rather than unbounded queue growth. Native callbacks and TLS state run on one libwebsockets event thread. The Linux TUN reader is a separate thread, and credential refresh is a background thread; crypto and packet processing never run in Node. The server admits at most 128 concurrent connections (including pending handshakes); pending authentication expires after 10 seconds. Up to 253 identities may be provisioned. Credential snapshots refresh roughly once a second, with a one-second request timeout; revocation is checked on one-second connection timers. Snapshot errors clear credentials and close sessions rather than retaining stale permissions.

## Performance boundaries

This is a native userspace data plane. It is **not OpenVPN DCO**, does not provide kernel encryption offload, and cannot inherit OpenVPN's kernel protocol. Linux kernel TUN, TCP/IP, routing and NAT remain in the kernel. WebSocket, inner TLS, and packet framing run in C/OpenSSL; nginx also handles the outer TLS layer. Apple packet tunnels use Network Extension rather than an installable iOS kernel driver.

TCP-over-TCP head-of-line blocking remains possible on lossy paths. Outer TLS and optional inner packet encryption add work. Local synthetic packet round trips through the native service and nginx measured about 877 Mbps per direction (PSK) and 891 Mbps (hybrid), but no AWS/TUN/device throughput result has been measured. This version has neither multi-queue TUN/sharded event loops nor zero-copy offload. Benchmark on your actual instance/clients before making a capacity commitment. A kernel driver cannot transparently remove those constraints from nginx HTTP WebSocket proxying.

## References

- [nginx WebSocket proxying](https://nginx.org/en/docs/http/websocket.html)
- [TLS 1.3](https://www.rfc-editor.org/rfc/rfc8446.html)
- [External PSK usage guidance](https://www.rfc-editor.org/rfc/rfc9257.html)
- [OpenSSL external PSK callbacks](https://docs.openssl.org/3.0/man3/SSL_CTX_set_psk_client_callback/)
- [libwebsockets threading and writable callbacks](https://github.com/warmcat/libwebsockets/blob/main/READMEs/README.coding.md)
- [Apple Network Extensions entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.networking.networkextension)

## Server privileges

The root network helper exits after configuring TUN/routing. Node runs as `xpn`, and all native connection handlers run as `xpn` before authentication. The Linux server executable rejects privileged launches and sets `no_new_privs` before library initialization or threads. Connections share one process and its credential cache; this is not per-client memory isolation. See [privilege separation](PRIVILEGE-SEPARATION.md) for installation, migration and checks.
