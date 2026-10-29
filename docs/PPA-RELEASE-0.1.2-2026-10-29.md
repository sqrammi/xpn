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
- Transfer archive: `/root/xpn-release-0.1.2-20261029-SERIES-input.tar.gz`.
- Transient jobs: `xpn-release-012-20261029-SERIES.service`.
- Jobs retain logs, package artifacts and a `status` file. They refuse to install
  over an active XPN server on a build host. They install both test packages and
  exercise the packaged entry points after building.
- Packet tests use private namespaces. The client service smoke test uses a
  temporary `xpn-client-releasecheck-012-20261029` instance. The new gateway
  service smoke test derives the installed service restrictions, adds a private
  network namespace, and uses separate `xpn-gateway-releasecheck` runtime/state
  directories and a temporary `/run/systemd/system` unit. Traps remove test
  services, profiles, state and unit files; logs/journals remain as evidence.

Local Python checks completed: 60 tests, 59 passed and one Linux-only skip.
Both definitive remote jobs reached `VALIDATED`: native CTest, all 60 Python
tests, Node tests, lintian, real-TUN gateway and reconnect checks, outer-only
transport, standby failover, wrong-pin rejection and both installed-service
smoke tests passed. Resolute also passed hybrid ML-KEM. Test services were cleaned
up and the four server services are inactive on the build hosts.

Two earlier attempts are retained as `SERIES-attempt1` and `SERIES-attempt2`.
Their failures were confined to the new test fixture: nft syntax needed newlines,
and Noble prevented a capability-restricted process from reading PID 1 network
namespace metadata. The corrected fixture obtains the host namespace identifier
before starting the restricted service; no service privileges were expanded.

Validated artifact checksums and both exact upstream archives were verified
locally. Source sets and signing scripts are staged at
`ren:~/xpn-release-0.1.2-20261029/release/`. The signing agent required unlocking;
the user was asked to run its `sign.sh`. No upload has occurred yet. Do not treat
this record as evidence of PPA availability until signed indexes are verified.

## Alta

Before deployment, Alta still uses the installer-managed checkout
`/root/repo/xpn`, with units under `/etc/systemd/system`. Preserve its admin token,
master key, database, backend ports, nginx URL and host TCP ports `85,443,5201`.
Migration to the validated server package is authorized by the release request.
Deployment, verification and rollback records will be added here as completed.

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

The user then requested all connected XPN devices, including automatic coverage
of future enrollments. Added explicit allDevices policy/UI support and legacy
policy compatibility; narrowed its nft destination range to 10.77.0.2–254. This
requires updated source artifacts before the first 0.1.2 upload. Initial signed
artifacts have not been uploaded; their signatures will be replaced after the
new artifacts pass validation. New local tests: 61 Python tests (one Linux-only
skip), 13 Node tests and syntax checks passed. The final builds are running.
