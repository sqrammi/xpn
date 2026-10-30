# XPN 0.1.2 release and Alta deployment

Requested destination: `ppa:sqrammi/xpn`, Noble and Resolute. Builds use
`little-guy-root` and `seven-root`; signing stays on `ren`. No C is built on the
Mac. This release includes the current checkout, notably live, persistent
WireGuard-to-XPN gateway policy controls and their restricted root broker.

## Source and build jobs

Versions: `0.1.2-0ubuntu1~noble1` and `0.1.2-0ubuntu1~resolute1`.
Source epoch: `1793311814`. The final all-devices upstream archives have SHA-256
`60b1815dc38e4a5d7faf431705d8eef280f68e28642f47e2d06f19fbff1d4c28`.

- Local preparation/evidence: `build/ppa-release-0.1.2-20261029/`.
- Each build host: `/root/xpn-release-0.1.2-20261029/SERIES/`.
- Transfer archive: `/root/xpn-release-0.1.2-20261029-SERIES-all-devices-input.tar.gz`.
- Transient jobs: `xpn-release-012-all-20261029-SERIES.service`.
- Jobs retain logs, package artifacts and a `status` file. They refuse to install
  over an active XPN server on a build host. They install both test packages and
  exercise the packaged entry points after building.
- Packet tests use private namespaces. The client service smoke test uses a
  temporary `xpn-client-releasecheck-012-20261029` instance. The new gateway
  service smoke test derives the installed service restrictions, adds a private
  network namespace, and uses separate `xpn-gateway-releasecheck` runtime/state
  directories and a temporary `/run/systemd/system` unit. Traps remove test
  services, profiles, state and unit files; logs/journals remain as evidence.

Local Python checks completed: 61 tests, 60 passed and one Linux-only skip.
Both definitive remote jobs reached `VALIDATED`: native CTest, all 61 Python
tests, 13 Node tests, lintian, real-TUN gateway and reconnect checks, outer-only
transport, standby failover, wrong-pin rejection and both installed-service
smoke tests passed. Resolute also passed hybrid ML-KEM. Test services were cleaned
up and the four server services are inactive on the build hosts.

Two earlier attempts are retained as `SERIES-attempt1` and `SERIES-attempt2`.
Their failures were confined to the new test fixture: nft syntax needed newlines,
and Noble prevented a capability-restricted process from reading PID 1 network
namespace metadata. The corrected fixture obtains the host namespace identifier
before starting the restricted service; no service privileges were expanded.

Validated artifact checksums and both exact upstream archives were verified
locally. Final source sets at `ren:~/xpn-release-0.1.2-20261029/release/`
were signed with `A70890AEB9BAF73E3CFE3DC26D0FC16CDE281EDE`; the signed
DSC/buildinfo/changes files and source hashes were verified before successful
dput uploads for both series. Earlier individual-only artifacts were retained
separately and were never uploaded. Local signed manifests and upload logs:
`build/ppa-release-0.1.2-20261029/signed-upload-evidence.tar.gz`.

## Publication verified — October 30, 01:08 UTC

Both Launchpad builds succeeded and both source versions are Published:
- [Noble build 33886109](https://launchpad.net/~sqrammi/+archive/ubuntu/xpn/+build/33886109)
- [Resolute build 33886110](https://launchpad.net/~sqrammi/+archive/ubuntu/xpn/+build/33886110)

Verified both public InRelease signatures against archive key
`949B0345EB78B33A0D69BBFB99E60713747180A6`, the SHA-256/size of each package
index, and the SHA-256/size of all four downloaded amd64 debs. Both xpn-client
and xpn-server are available as `0.1.2-0ubuntu1~noble1` and
`0.1.2-0ubuntu1~resolute1`. Evidence, signatures, indexes and downloaded packages:
`build/ppa-release-0.1.2-20261029/apt-verification/`; exact manifest:
`apt-verification/verified.json` under that directory.

Earlier checks through 00:53 UTC saw successful builds and Published sources
but binary indexes still offering 0.1.1. Build logs confirmed the correct 0.1.2
debs were produced; no duplicate upload or rebuild was performed. Logs are in
`build/ppa-release-0.1.2-20261029/launchpad-logs/`.

The publication monitor completed and was deleted. No live VPN host or
connection was modified during publication verification. With this PPA already
configured, stop a foreground client before installing its boot service:

```sh
sudo apt update
sudo apt install xpn-client
sudo xpn-client-setup ./xpn-profile.json --name alta
```

This PPA release includes the persistent client and randomized retry/backoff.
The later client-to-client ping change is only in the separately staged local
`+peerping1` packages; it is not in this initial PPA release. Do not downgrade a
local peerping1 installation to the PPA version. See
[peer-ping deployment](PEER-PING-2026-10-29.md).

## Alta

Before deployment, Alta used the installer-managed checkout
`/root/repo/xpn`, with units under `/etc/systemd/system`. Preserve its admin token,
master key, database, backend ports, nginx URL and host TCP ports `85,443,5201`.
Migration to the validated server package was authorized by the release request.
The following sections record the completed migration and final update.

WireGuard changes are recorded separately in
[the Alta–Route10 setup record](WIREGUARD-ALTA-2026-10-29.md). That interface can
be tested independently of XPN forwarding; no XPN services were restarted when
bringing it up.

## Initial Alta migration completed

Installed the validated Resolute server package (initial individual-device policy
build, SHA-256 `041f655abf8116194da5c47692916a38c871f0b5f111dea66619efc290af1836`).
No other package was installed, upgraded or removed. Private migration backups,
script, package, logs and verification manifest are under
`/var/backups/xpn-release-0.1.2-20261029/`. Installer report:
`/var/backups/xpn/20261029T223601137913Z/changes.md`.

Removed the managed checkout overrides for xpn-network/control/native, adopted
package vendor units, added xpn-native.service.d/xpn.conf and
xpn-network.service.d/xpn.conf, retargeted their boot links, enabled the new
xpn-gateway service, and updated /etc/xpn/install.json. Recreated xpn0 and the
XPN nftables table with the existing 85,443,5201 host ports. Reused the existing
xpn account/database/runtime directory; added the gateway runtime/state
directories. The source checkout and its binaries remain available for rollback.
Nginx configuration and WireGuard were unchanged.

Verified all four XPN services and WireGuard active, both network-facing
services still running as xpn, retained admin/master keys and transport/SMTP
settings unchanged, all four device records (including the revoked record)
unchanged, SQLite quick_check successful, authenticated users/gateway APIs
responsive, and the HTTPS page containing the new panel. Gateway forwarding
remained disabled pending the user-selected policy.

Added /etc/apt/keyrings/xpn-ppa.gpg and /etc/apt/sources.list.d/xpn-ppa.list
(root-owned, 0644), verifying archive key
949B0345EB78B33A0D69BBFB99E60713747180A6. Refreshed only that PPA index. The PPA
still offers 0.1.0 at this point; Alta uses the directly installed validated deb.
APT will use the configured PPA for future published upgrades.

## Final all-devices deployment completed

Installed the final validated `xpn-server 0.1.2-0ubuntu1~resolute1` package,
SHA-256 `935704a78a5cd99c64b5024bcd6bf017fd7b97a8b875e22637f5d9c38f950896`.
Private pre-update state, package, script, log and verification records are under
`/var/backups/xpn-release-0.1.2-20261029/all-devices/`; its status is `DEPLOYED_ALL`.
The final installer report is
`/var/backups/xpn/20261029T224658008144Z/changes.md`. Local non-secret copy:
`build/ppa-release-0.1.2-20261029/alta-all-installer-changes.md`.

All four XPN services and WireGuard are active. The environment file and device
records were verified unchanged. No client profiles, keys or invitations changed.
The final update reused the installed package units and refreshed the network,
services and installation fingerprints; nginx and WireGuard config were unchanged.

Applied the server-wide policy through the authenticated admin API:
`enabled=true`, interface `wg0`, sources `172.9.0.0/16`, `allDevices=true`,
manual targets empty, TCP ports `22,5201`, UDP ports empty, ping enabled.
It covers current and future client addresses `10.77.0.2–10.77.0.254`.
Policy persistence is only `/var/lib/xpn-gateway/policy.json`; changing it updates
firewall rules without reconnecting clients. Replies are allowed, while new
XPN-to-home connections remain blocked. This permits the listed services, not
unrestricted forwarding of every protocol/port.

Home-to-server pings through WireGuard passed. Draper700 (`10.77.0.5`) did not
respond before or after deployment; end-to-end access to that live client is not
verified. A read-only check of SSH alias `draper7` reached `draper600`, which had
no loaded xpn-client unit, native xpnd process or XPN/TUN interface. No Draper
configuration or service was changed. Isolated real-TUN client forwarding and
live allow/deny transitions passed on both build hosts.
