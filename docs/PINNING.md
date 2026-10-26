# Certificate pinning and custom SNI

The Linux, macOS and iOS clients share the C transport. It can connect to one endpoint, send a different TLS SNI hostname, and authenticate the exact certificate you provisioned. The endpoint determines DNS resolution and HTTP Host; SNI changes only the TLS ClientHello. Apple clients resolve the endpoint before activating the full tunnel and pass its numeric address to the native connection. This changes only the TCP dial address: HTTP Host, unpinned hostname verification, custom SNI and pins remain based on the original profile. Reconnecting from the app refreshes that resolution. For example:

```json
{
  "version": 2,
  "endpoint": "wss://vpn.example.com/xpn/vpn",
  "sni": "app.jeffhansen.com",
  "certificatePins": ["<64 hexadecimal characters: SHA-256 of the leaf certificate DER>"]
}
```

These are fields in the complete private device profile, alongside its existing ID, key, address and routing settings. This fragment alone is not an importable credential. SNI must be a DNS hostname, without a scheme, port or wildcard; use ASCII/Punycode for internationalized names. The SNI name need not resolve on the client.

## Obtain and distribute the pin

Compute the fingerprint from a **trusted copy of the certificate nginx actually presents**, with the leaf first if this is a fullchain PEM:

```sh
node server/cert-pin.mjs /path/to/nginx/fullchain.pem
```

The tool prints the SHA-256 digest as 64 hex characters. It does not contact the server. Do not bootstrap trust by copying a certificate from an unauthenticated network connection; there is no automatic trust-on-first-use or silent pin replacement.

In the admin console, expand **Server certificate & SNI** while creating a user. Enter the fingerprint and, optionally, `app.jeffhansen.com`. The QR enrollment profile carries these values encrypted along with the device credential. For an existing user choose **Certificate / SNI**, save, then scan the newly issued QR or import its downloaded JSON on that device. This preserves its PSK, replaces outstanding invitations, and can disconnect the active session when the server refreshes the policy. Existing local profiles are not remotely rewritten.

To set defaults for newly created users, configure `/etc/xpn.env`:

```ini
VPN_SNI=app.jeffhansen.com
VPN_CERTIFICATE_PINS=<64-hex-fingerprint>
```

Separate multiple fingerprints with commas. In the creation form, blank fields inherit these defaults. Existing users keep their stored settings when defaults change. The per-user editor sets the fields explicitly; clearing both restores ordinary CA and endpoint-hostname verification.

The administrator API accepts `sni` and `certificatePins` on `POST /xpn/api/users` and on authenticated `POST /xpn/api/users/:id/transport`. The latter replaces both transport fields and returns a fresh invitation. Fingerprints can be plain 64-character hex or the colon-separated SHA-256 format emitted by OpenSSL; generated profiles always contain plain hex. Up to four distinct pins are supported.

## Verification and rotation

- A pinned connection accepts only a currently valid leaf certificate whose exact DER digest matches one of the configured pins. TLS still checks proof of possession of the private key.
- The pin replaces CA and hostname trust for the VPN WSS connection. A self-signed or differently named certificate is accepted only when its pin matches. A valid publicly trusted certificate with the wrong pin is rejected before the HTTP upgrade or VPN authentication.
- Expired and not-yet-valid certificates fail even if pinned. There is no fallback to CA verification after a pin mismatch, and TLS session caching is disabled to require certificate verification on each connection.
- Custom SNI requires a pin. Unpinned profiles continue using normal CA and endpoint-hostname checks.
- Pins cover the **whole leaf certificate**, not just its public key. Renewal changes the pin even when the private key stays the same. Before renewal, provision both old and new pins to clients; switch nginx to the new certificate; then remove the old pin and redistribute profiles. Unknown replacements fail closed.

Pinned profiles use **profile version 2** so older XPN clients reject them instead of ignoring security settings. Update the server and all client binaries before issuing these profiles; native builds now require libwebsockets 4.3+ for explicit TLS session-cache control. The inner PSK TLS protocol and `xpn-v1` WebSocket subprotocol are unchanged. Pinning does not replace the device PSK or add post-quantum protection to the outer certificate signature.

Enrollment and the web console still use normal HTTPS verification at `PUBLIC_URL`. Custom SNI and the provisioned pins take effect on the subsequent VPN connection. To bootstrap without reachable normally verified enrollment HTTPS, import a complete profile through a trusted out-of-band channel.

## nginx routing

Configure nginx for the TLS SNI and HTTP Host separately. HTTP virtual-host selection can change when the request Host arrives; overriding SNI does not rewrite Host. A single HTTP virtual host may list both names:

```nginx
server {
    listen 443 ssl;
    server_name vpn.example.com app.jeffhansen.com;
    ssl_certificate /etc/nginx/certs/vpn-fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/vpn-key.pem;
    # Include the /xpn/ and WebSocket locations from deploy/nginx.conf.
}
```

Here the certificate can be valid for `vpn.example.com` alone. A client connecting to that endpoint with SNI `app.jeffhansen.com` will accept it with the correct pin. With an nginx stream/SNI router, ensure the selected downstream TLS server presents that pinned certificate and its HTTP virtual host handles the original endpoint Host. Both names must route correctly according to your nginx setup; the client makes no DNS or routing changes for the custom SNI name.
