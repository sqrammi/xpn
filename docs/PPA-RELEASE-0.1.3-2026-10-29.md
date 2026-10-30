# XPN 0.1.3 PPA release

Destination: `ppa:sqrammi/xpn`, Ubuntu Noble and Resolute, amd64 client and
server packages. This promotes the tested `+peerping1` changes into a normal
upstream release. Debian versions are `0.1.3-0ubuntu1~noble1` and
`0.1.3-0ubuntu1~resolute1`; both upgrade over the corresponding 0.1.2 packages,
including the temporary `+peerping1` build.

The server-wide **Allow XPN clients to ping each other** switch changes ICMP
echo forwarding live, independently of home gateway forwarding. It does not
change device profiles or enable other peer protocols. Both server and clients
need the updated native implementation. Existing boot-service setup and
randomized reconnect backoff remain included.

## Build and verification

- Noble build host: `little-guy-root`; Resolute: `seven-root`.
- Local artifacts: `build/ppa-release-0.1.3-20261029/`.
- Host workspace: `/root/xpn-release-0.1.3-20261029/SERIES/`.
- Transient build units: `xpn-release-013-20261029-SERIES.service`.
- Signing destination: `ren:~/xpn-release-0.1.3-20261029/release/`.
- Source epoch: `1793329526`.
- Identical upstream archive SHA-256 for both series:
  `b91da718563748d43bc9aa32101eec92c2009704d785aefabd08827f6fb93666`.

Builds install and test packages only on the designated build hosts. They run
native, Python and Node tests, lintian, real-TUN tests including two-client
peer ping default denial/live enable/live disable, reconnect and gateway tests,
TLS-only transport, standby failover, wrong-pin rejection and installed client
and gateway service smoke tests. Resolute also tests hybrid ML-KEM.
The smoke tests use isolated namespaces and clean up temporary services.
No C is built locally. No production Alta or Draper changes are part of this
release preparation.

## Validation complete; signed and uploaded

Both jobs reached `VALIDATED`. Each passed all five native CTests, 62 Python
tests and 13 Node tests, the integration and service checks listed above, and
binary/source lintian with no errors. Original source archives and all retrieved
artifact SHA-256 hashes were checked locally. Debian version comparison on
both build hosts confirmed this release upgrades the temporary peerping package.
Evidence: `validated/noble/` and `validated/resolute/` under the local artifact
root, including `SHA256SUMS`, build logs and smoke-test journals.

Both source sets were signed on ren with key
`A70890AEB9BAF73E3CFE3DC26D0FC16CDE281EDE`. The expected key, source archive
hashes and every signed DSC/buildinfo/changes manifest were verified before
successful dput uploads of both series to `ppa:sqrammi/xpn`.

Signed manifests and upload logs are retained locally in
`build/ppa-release-0.1.3-20261029/signed-upload-evidence.tar.gz` and the matching
extracted directory. Complete signed source sets remain on ren.

At October 30, 04:10 UTC, Launchpad accepted both source versions and both
amd64 builds succeeded:
- [Noble build 33886570](https://launchpad.net/~sqrammi/+archive/ubuntu/xpn/+build/33886570)
- [Resolute build 33886571](https://launchpad.net/~sqrammi/+archive/ubuntu/xpn/+build/33886571)

## Publication verified — October 30, 05:07 UTC

Both source records are Published and both amd64 builds succeeded. The public
APT indexes now offer `xpn-client` and `xpn-server` versions
`0.1.3-0ubuntu1~noble1` and `0.1.3-0ubuntu1~resolute1`.
Verified InRelease signatures with archive key
`949B0345EB78B33A0D69BBFB99E60713747180A6`, SHA-256/size of each index, and
SHA-256/size of all four downloaded packages. Evidence is retained under
`build/ppa-release-0.1.3-20261029/apt-verification/`, including `verified.json`,
InRelease files, signature logs, package indexes and debs.

The prior 04:51 UTC check was still pending; no duplicate upload was performed.
The publication monitor is complete. This verification did not modify Alta or
Draper or change live connections; both already run locally validated 0.1.3.

For other clients with the PPA configured:

```sh
sudo apt update
sudo apt install xpn-client
```

0.1.3 upgrades the temporary `+peerping1` packages. For clients without a boot
service, use an existing enrolled profile:

```sh
sudo xpn-client-setup ./xpn-profile.json --name alta
```

## Direct host upgrades (requested before PPA publication)

Alta now runs the validated local `xpn-server 0.1.3-0ubuntu1~resolute1` deb.
Operational report and root-only backups: `/var/backups/xpn-server-013/` on Alta;
read `changes.md` for every applied step. This directory retains `new.deb`,
`previous.deb`, SHA-256 manifests, the executed script, logs, previous version,
and a stopped-control-service backup of the database, environment, installer
state, gateway policy, systemd overrides, nginx configuration and WireGuard files.

The update stopped native/control services, installed the checksum-verified
package, started network/gateway/control/native services and reloaded systemd
unit definitions. Device records and all checked configuration files are
unchanged. The database integrity check passed. All four XPN services are active
and boot-enabled; WireGuard remains active. The public HTTPS console returns
200, and server-to-Draper ping to `10.77.0.5` passed 2/2.

Alta already had the PPA in `/etc/apt/sources.list.d/xpn-ppa.list`, scoped to
amd64/Resolute with `/etc/apt/keyrings/xpn-ppa.gpg`. Its fingerprint matches
`949B0345EB78B33A0D69BBFB99E60713747180A6`. The PPA index refresh succeeded;
it still offers 0.1.2 while the installed/candidate version is local 0.1.3.
No PPA configuration change was needed. The source checkout was not deleted.

Draper700 was upgraded by the user running the staged sudo script and then
verified remotely. Installed version: `xpn-client 0.1.3-0ubuntu1~resolute1`.
`xpn-client-alta.service` is enabled and active, with no pending systemd reload;
it started October 29 at 22:03:56 MDT. It uses the existing
`/etc/xpn/clients/alta.json`, with native reconnect backoff 10–300 seconds and a
120-second stable-connection reset threshold. Both active/standby lanes
successfully authenticated. Interface `xpn19163` has `10.77.0.5/32`.

Bidirectional pings passed 3/3 each: Draper to `10.77.0.1` (~22 ms), and Alta to
`10.77.0.5` (~23 ms). Alta still runs 0.1.3 with all four XPN services active.
The client upgrade report/backups are under
`/var/backups/xpn-client-013-20261030T040355/` on Draper; exact steps are in
`changes.md`. The script preserves the existing profile and unit, checks their
hashes, and restarts the existing service without re-enrollment. The staged
packages and script remain in `/home/draper/xpn-update-013/`. Boot enablement was
verified; no reboot was performed.
