# XPN Ubuntu PPA release — October 27, 2026

## Destination and source

- Public PPA: https://launchpad.net/~sqrammi/+archive/ubuntu/xpn (`ppa:sqrammi/xpn`). Created with the owner's explicit activation/terms approval.
- Owner selected MIT for XPN; bundled dependencies retain their own licenses/notices.
- Packages: `xpn-client` and `xpn-server`, amd64. Versions `0.1.0-0ubuntu1~noble1` and `0.1.0-0ubuntu1~resolute1`.
- Source signing on ren: `A70890AEB9BAF73E3CFE3DC26D0FC16CDE281EDE`. No private key was copied.
- PPA archive signing key (different from upload key): `949B0345EB78B33A0D69BBFB99E60713747180A6`.
- Both original source tarballs SHA-256: `3f1dbf7d54639b9978528c7f75ce2192ca1d85567c91bffe0a29e67713761dbf`.
- Final remote sources/artifacts: `little-guy-root:/root/xpn-release-20261027/release-noble/` and `seven-root:/root/xpn-release-20261027/release-resolute/`. Signing inputs: `ren:~/xpn-release-20261027/release/{noble,resolute}/`.

## Build-host changes

On both designated hosts:

1. Recorded installed package versions and disk space under `/root/xpn-release-20261027/`.
2. Refreshed APT indexes and installed missing build/test prerequisites (debhelper, CMake/Ninja, native headers, devscripts/lintian, nginx, nftables and supporting tools). Exact package transactions are in `apt-install.log`; no unrelated upgrade command was run.
3. Added `/etc/apt/keyrings/xpn-nodesource.gpg` and `/etc/apt/sources.list.d/xpn-nodesource.list`, scoped with `signed-by`. Verified NodeSource key fingerprint `6F71F525282841EEDAF851B42F59B5F99B1BE0B4`. Installed `nodejs 24.22.1-1nodesource1`; neither host previously had Node installed. Logs: `node-apt-update.log`, `node-apt-install.log`.
4. Built native C only on the corresponding Ubuntu host. Installed both local test `.deb` packages; this created one `xpn` system account. No production XPN services were activated on those hosts. `zbar-tools` and client routing/runtime dependencies were installed by APT.
5. Used disposable network/mount namespaces for actual TUN/NAT tests. No host routes or host nftables configuration were changed by those tests.
6. On seven, stopped/disabled the nginx service newly auto-started by dependency installation; isolated tests launch their own nginx. Little-guy already had nginx installed/active, so its service was left alone.
7. Kept sources, test packages and logs for reproduction; no existing user checkout or other service configuration was overwritten.

## Validation

- Both series: native CTest suite passed; Node tests and syntax checks passed.
- Both series: installed command entry points and vendor systemd unit validation passed. Binary-package lintian reports no errors/warnings for final packages.
- Both series: split/full TUN, WAN forwarding/NAT, pinned custom SNI, host port isolation and non-root server-thread checks passed, with optional inner encryption both on/off.
- Both series: authenticated standby failover under injected delay and wrong-certificate rejection passed. Resolute hybrid ML-KEM transport passed; Noble uses PSK with its stock OpenSSL 3.0.
- Installer: 30 regression tests pass on Mac (one Linux-only socket test skipped), including checkout migration preserving secrets, retargeting startup links, and no-op reruns. No C compilation was performed on Mac.
- Noble's source lint checker misidentifies long readable HTML/JS lines and generated dependencies. Narrow documented overrides identify original readable files and bundled preferred sources. Pinned source/build recipes for Nodemailer and emoji-regex are in `vendor/sources`; the unused pngjs browser bundle is excluded. Resolute reports only the advisory `pkg-config` → `pkgconf` build-dependency warning.
- Earlier synthetic loopback rates are diagnostic only, not an end-to-end capacity claim. Existing WAN throughput and LAN-routing findings remain in VALIDATION.md.

## Publication and Alta migration

Both source uploads were signed interactively by the owner on ren, verified with GPG, and uploaded with dput at approximately 08:22 Denver. Launchpad accepted both sources at approximately 08:28 Denver. Independent amd64 builds: [Noble 33876376](https://launchpad.net/~sqrammi/+archive/ubuntu/xpn/+build/33876376), [Resolute 33876377](https://launchpad.net/~sqrammi/+archive/ubuntu/xpn/+build/33876377); Noble's downloaded build log reports `Status: successful` (finished 14:42:33 UTC); binary publication and Resolute build verification are pending. Alta remains on the checkout until published packages are verified. Its existing NodeSource Node 24 package already satisfies the runtime requirement; no new Node repository is needed there. Planned migration preserves ports 3300/3301, host TCP access 85/443/5201, nginx certificate/pins, `/etc/xpn.env`, and `/var/lib/xpn`.

See [package installation and rollback instructions](UBUNTU-PPA.md). Exact completed Alta actions will be appended here and in ALTA-HOST-CHANGES.md.

### Publication checkpoint — 15:15 UTC

Launchpad's browser showed both builds in `Uploading build`; Noble's downloaded log confirms a successful build. API responses were intermittently stale/timeouts, and both signed APT indexes still returned HTTP 403. No published-package installation has been attempted, and the release is not yet verified installable through APT.

- Both build hosts have `/root/xpn-release-20261027/install-published.sh` staged for installing the published packages and checking integrity, entry points, inactive default services and a real TUN connection. This script has not run.
- Alta has `/root/xpn-ppa-migrate-20261027.sh` staged, mode 0700. It has not run. It will take a fresh online-consistent database/configuration backup, install the PPA server, migrate managed units, check unchanged credentials/device records/nginx, verify non-root service identities, and run setup again to check idempotence. It restores checkout configuration on a migration failure.
- Read-only Alta verification: all three XPN services active; control/native still use `/etc/systemd/system` checkout units; `xpn-server` is not installed; no migration-start marker exists. No PPA repository/key was added there, and no production service restart or production account change occurred during this release preparation.
- Local operational scripts and public build evidence: `build/ppa-audit/`. These ignored files are working artifacts; durable installation/rollback instructions are in `UBUNTU-PPA.md`.

Resume only after Launchpad publishes both series: run the staged published-package tests on the corresponding hosts, then run Alta's staged migration independently of SSH with `systemd-run --unit=xpn-ppa-migrate-20261027 --collect /bin/bash /root/xpn-ppa-migrate-20261027.sh`. Inspect `/var/backups/xpn/ppa-migration-20261027/actions.log` and its `succeeded` marker, and append the completed actions here. Do not report Alta migrated until those checks pass.
