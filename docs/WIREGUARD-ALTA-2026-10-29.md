# Alta–Route10 WireGuard setup, 2026-10-29

## Intended policy

Route10 sends only the remote XPN subnet `10.77.0.0/24` through this peer. Home
devices may initiate selected connections to XPN devices; XPN devices must not
initiate connections to any home VLAN. This requires stateful forwarding rules,
not just WireGuard AllowedIPs. The server needs home source subnets in its peer
AllowedIPs for authentication and return routing; that does not itself grant
permission to initiate traffic toward home.

## Endpoint settings

| Setting | Alta | Route10 |
| --- | --- | --- |
| Tunnel address | `192.168.98.1/32` | User selected `192.168.98.2/32` |
| Public key | `C7Qw2rvCgelYQzpj6zfn4yxjyXDL4foLLpSa09BXdkw=` | `GnTz39lO3ZNiqQ3CMlA+k/aMLUJiEnzDqCah74J+lHE=` |
| Public endpoint | `138.68.255.92:51820` (`alta.jeffhansen.com`) | Route10 initiates to Alta; endpoint learned from authenticated traffic |

Route10 remote subnets: `10.77.0.0/24`. Do not use `0.0.0.0/0`. The server peer
will need `192.168.98.2/32` and the actual allowed home source subnet(s), initially
`172.9.0.0/16` subject to confirmation. Other home VLANs are not included.
The user has already set a PSK on Route10. It must be entered on Alta through an
interactive terminal and must not be copied into chat or this repository.

## Host preparation performed

Read-only checks found no existing WireGuard CLI/interface/configuration, no
route for `192.168.98.0/24`, no UDP listener on 51820, and inactive UFW. Existing
nftables input rules did not block ordinary public UDP 51820 traffic. The
DigitalOcean cloud firewall has not been inspected or modified.

By the preparation step, `wireguard-tools` version `1.0.20250521-1ubuntu1` and
the root-only `/etc/wireguard` directory were already present. This preparation
did not install packages or create the directory. It generated
`/etc/wireguard/alta-route10.key` only if absent. The private key remained on Alta;
only its derived public key was returned. No WireGuard interface was started,
no routes/firewall rules were changed, and no XPN/nginx service was restarted.

Authoritative host audit: `/var/backups/xpn-wireguard-20261029/changes.txt`.
The key has mode 0600; the directory is root:root mode 0700.

## Pending

- Securely enter the existing Route10 PSK into `/etc/wireguard/route10.psk` with
  root ownership and mode 0600.
- Complete the server config and confirm the home source subnet(s).
- If a DigitalOcean cloud firewall applies to Alta's Droplet, allow inbound UDP
  51820 from the home's public WAN IPv4 address. Preserve existing SSH/HTTPS
  access. A dynamic WAN address requires updating that source rule when it changes.
- Start and verify the WireGuard handshake and gateway reachability.
- Complete validation/deployment of the new XPN gateway policy before expecting
  forwarding to `10.77.0.2` and other XPN devices. Existing XPN firewall rules
  still block that forwarding. The gateway feature is not in PPA 0.1.1.

## Continued deployment, October 29

The user supplied their existing `/etc/wireguard/alta-private.key`; its public
key is now the Alta key in the table above. The earlier `alta-route10.key` remains
untouched but is not used by `wg0`. The user saved the matching Route10 PSK to
`/etc/wireguard/route10.psk` and confirmed the DigitalOcean rule and Route10 profile
are ready. Both selected key files were validated as 32-byte keys, root-owned,
without group/other permissions. No secret was printed or copied off Alta.

Created `/etc/wireguard/wg0.conf` (root-owned, mode 0600) using those existing
secrets and the Route10 public key. Configured Alta address `192.168.98.1/32`, UDP
listen port 51820, and peer AllowedIPs `192.168.98.2/32, 172.9.0.0/16`. Enabled and
started `wg-quick@wg0`, creating its boot symlink, `wg0`, and the two specific
routes. The default route, existing firewall rules and XPN/nginx services were
unchanged. Host audit actions were appended to the same `changes.txt`.

The service is active and the tunnel completed a handshake. Route10 uses
interface `wgfcwBSn` with its own UDP listener on 59065; the existing WireGuard
server interface `wg` remains on 51820. Thus its current Use Own binding does
not share the existing listener. Its endpoint resolved to Alta IPv6
`[2604:a880:2:d0::10f9:1001]:51820`. No router configuration was changed by the
assistant; checks were read-only SSH operations.

Three pings from Route10 source `172.9.0.1` to `10.77.0.1` succeeded at about
25 ms. Three pings from the Mac through `en0` and Route10 also succeeded at about
28 ms. The DigitalOcean Droplet page confirmed attached firewall `ssh` permits
UDP 51820 from all IPv4/IPv6 and permits outbound UDP. Those existing cloud rules
were inspected but not changed. XPN-device forwarding still requires its gateway
policy and a connected destination device; Alta could not ping Draper700
`10.77.0.5` before the 0.1.2 deployment.
