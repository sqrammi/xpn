# Incoming traffic to XPN devices

**Allow incoming traffic to XPN devices** is a server-wide switch. It is stored
only on the server, never in device profiles. **Save & apply now** changes the
policy live and persists it for reboot, without reconnecting VPN clients.
Incoming traffic is disabled by default.

The general firewall mode and new labels are working-tree changes after 0.1.3;
they are not in that published package. The earlier scoped WireGuard mode was
introduced in 0.1.2. Existing saved policies are interpreted as restricted mode
on upgrade, preserving their existing access instead of silently broadening it.

## Filtering modes

- **Use server firewall · all sources and services:** allow routed incoming
  IPv4 traffic from any non-XPN interface to all XPN client addresses `.2` through
  `.254`, including future enrollments. No source subnet, WireGuard interface,
  protocol or port list is required. Your independent iptables/nftables rules
  decide what traffic may pass. An XPN accept does not override a drop in another
  base chain. Rules must filter forwarded traffic, not only server INPUT traffic.
- **Also restrict by WireGuard interface, sources and services:** retain the
  earlier optional restrictions. Choose a dedicated existing WireGuard interface,
  allowed source CIDRs, all devices or selected addresses, TCP/UDP ports and ping.
  The interface must not carry the server's default route. XPN does not create
  WireGuard keys, peers or routes.

The switch controls incoming connections. It does not authorize clients to
initiate new connections through non-WAN interfaces. Replies to permitted incoming
connections are stateful. Client-to-client ping remains separately controlled;
other peer protocols remain blocked. Server-host service access is also separate
and uses `--host-tcp-ports`.

## Routing and replies

Traffic must already be routed to the server and its XPN subnet. In a Route10
S2S setup, route `10.77.0.0/24` to the server peer and configure the server peer's
AllowedIPs/return routes for the original sources. The incoming interface can
be WireGuard, another tunnel or another routed interface in server-firewall mode.

XPN source-NATs forwarded incoming traffic to `10.77.0.1`, so replies traverse
the client's tunnel. Client profiles must include `10.77.0.1/32` or a covering
route such as `10.77.0.0/24`, or use full-tunnel mode. Destination services and
client host firewalls must allow the intended traffic from `10.77.0.1`.
Independent server FORWARD rules see the original source before this SNAT.

A profile with `fullTunnel: true` routes all IPv4 traffic, regardless of entries
in `routes`. For subnet-only access, use `fullTunnel: false` and the selected
routes. The updated creation form defaults to selected subnets; the subnet field is disabled and grayed out in full mode, and enabled/required
in selected-subnets mode. Switching back preserves the previously entered subnets. The API rejects contradictory full-tunnel-plus-subnets
input. Already-imported profiles require an explicit client-side update;
a server-side firewall or policy change cannot rewrite them.

Keep Route10 masquerading off if server firewall rules need to match the original
LAN sources. With external filtering, a source-subnet list inside XPN is optional.

## Applying and disabling

Select the incoming checkbox, choose a filtering mode, then **Save & apply now**.
A stale-edit error requires **Refresh policy**. Disabling blocks incoming sessions
immediately while preserving outbound VPN connections and their replies. Changing
NAT-related settings can require applications to reconnect; conntrack is not
flushed. Other firewall tables and cloud firewall rules remain in effect.

## Privileges, persistence and troubleshooting

Node and the native packet service still run as the existing non-root `xpn` account. A separate `xpn-gateway.service` runs a small Python broker as root with only `CAP_NET_ADMIN` in its capability bounding set. It has no TCP listener, cannot accept arbitrary commands or file paths, validates every policy, and only replaces the two dedicated gateway chains in `inet xpn` through a single nftables transaction.

The broker's Unix socket is `/run/xpn-gateway/control.sock` (root:xpn, `0660`); it additionally checks the connecting UID. Because Node and the packet daemon share `xpn`, either process can reach this restricted policy API. This is not isolation between those two processes. Policies are stored root-only at `/var/lib/xpn-gateway/policy.json` (`0600` in a `0700` directory). Restarting `xpn-network` also restarts the broker to restore the saved policy after the table is recreated. Use the managed services instead of invoking `network.sh` directly on a running installation.

The authenticated admin API is `GET /xpn/api/gateway` and `POST /xpn/api/gateway` (adjust `/xpn` to your installation prefix). GET returns `revision`, `policy` and `applied`; POST takes the returned revision and complete policy. It has the same admin-token, origin and rate checks as other administrative endpoints. Concurrent stale writes fail with HTTP 409. A failed firewall transaction leaves the previous rules and saved revision intact.

Read-only diagnostics:

```sh
sudo systemctl status xpn-gateway --no-pager
sudo journalctl -u xpn-gateway -n 50 --no-pager
sudo nft list chain inet xpn gateway_forward
sudo nft list chain inet xpn gateway_nat
ip -4 route get 172.9.0.2
```

An unavailable helper produces an explicit console error; it does not silently claim the policy was saved. The console reports the broker's last applied policy; external manual firewall edits are not monitored. In restricted mode, a non-WireGuard interface or a WireGuard interface carrying the server default route is rejected. Server-firewall mode does not require WireGuard.

## Client-to-client ping

**Allow XPN clients to ping each other** is a separate, server-wide switch. It
allows ICMP echo requests and stateful replies between client addresses `.2`
through `.254`, without enabling other client-to-client protocols. It works
independently of the incoming-traffic switch and applies live without reconnecting.
No device profile setting is added. Clients still need a full-tunnel route or a
split route covering the peer address, usually `10.77.0.0/24`.

Both server and clients need the native peer-ping update: earlier binaries reject
peer-destined packets before they reach the server firewall, including replies.
The initial `0.1.2-0ubuntu1~SERIES1` PPA release does not contain this later change.
The first local Resolute validation/deployment package is
`0.1.2-0ubuntu1~resolute1+peerping1`.

Keep Route10 S2S masquerading off when the allowed sources are home subnets.
Otherwise its source becomes the Route10 tunnel IP and will not match those
subnets. Alta already source-NATs permitted home traffic to `10.77.0.1` for client
replies, while retaining the home route on WireGuard. Pinging the server itself
is governed by host input rules, independently of device forwarding.
