# Home network access to XPN devices

The server console can allow selected traffic from an existing WireGuard link into selected XPN devices. The policy is disabled by default. **Save & apply now** replaces the gateway firewall rules immediately and saves the policy for reboot, without restarting XPN or disconnecting its clients.

This feature is in the source checkout after the 0.1.1 release; it is not included in the already-uploaded 0.1.1 PPA packages. Install an updated server release and rerun `xpn-server-setup` with your existing installation options, or run the updated checkout installer. That initial upgrade installs a service and new firewall chains and can restart the VPN. Subsequent web policy changes do not restart it.

## Before enabling

- Configure the Route10-to-server WireGuard tunnel separately. Use a dedicated interface such as `wg0`, not the server's default outbound interface. XPN does not create WireGuard keys, peers or routes.
- On Route10, route the selected XPN addresses (or `10.77.0.0/24`) through the server peer and allow the intended LAN traffic. On the remote server, the home WireGuard peer's `AllowedIPs` and routing must cover the home source subnets. Do not overlap them with the XPN subnet.
- Each selected XPN device must already route `10.77.0.1` through XPN. Full-tunnel profiles do this. For split profiles, include `10.77.0.1/32` when enrolling/importing the profile. A server firewall update cannot add routes to a client's installed profile. The web API checks the server's saved device policy, but cannot verify the profile currently imported on a client.
- The service on the destination device must listen on its XPN address (or all appropriate interfaces), and the device firewall must allow its port from `10.77.0.1`.
- Other server firewall chains, cloud security rules and Route10 rules still apply. An accept in XPN's table cannot override a drop in another nftables base chain.

## Web console

Sign in with the existing admin token and open **Home network access to XPN devices**:

1. Select **Enable home-to-XPN forwarding**.
2. Enter the existing WireGuard interface, for example `wg0`.
3. Enter the allowed home source CIDRs, for example `172.9.0.0/16`.
4. Enter the individual destination XPN addresses, for example `10.77.0.2, 10.77.0.3`. The device list shows each address. Only active enrolled devices are accepted.
5. Select the TCP/UDP destination ports and whether ping is allowed. For SSH and HTTPS, use TCP `22,443`.
6. Click **Save & apply now**. Success shows that the policy is applied and saved. A stale-edit error requires **Refresh policy** before saving again.

To close access, clear the enable checkbox and save. Subsequent forwarded packets, including packets on existing connections, are blocked. The VPN tunnels remain connected. The saved addresses/ports remain available for re-enabling.

## Traffic behavior

Allowed traffic follows `home LAN → WireGuard → server → xpn0 → selected device`. The server source-NATs it to `10.77.0.1`, so the client returns traffic through its existing gateway route. The client sees the XPN server as the source, rather than the original home IP.

Only selected source CIDRs, destination addresses, protocols and ports are allowed. Return traffic is stateful. XPN devices cannot initiate connections toward home through the configured gateway interface. Client-to-client isolation and restrictions on services hosted by the server remain separate; `--host-tcp-ports` controls the server itself, not forwarding to devices. This feature supports IPv4.

Changing an interface/address or NAT policy may interrupt affected application connections. It does not flush conntrack, so after changing NAT-related settings an application might need to open a new connection. Unrelated VPN sessions continue running.

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

An unavailable helper produces an explicit console error; it does not silently claim the policy was saved. The console reports the broker's last applied policy; external manual firewall edits are not monitored. An existing interface of the wrong type, or a WireGuard interface used by the main default route, is rejected when enabling/saving. Keep it dedicated after enabling as well.
