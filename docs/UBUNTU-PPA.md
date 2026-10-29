# Ubuntu packages: Noble and Resolute

PPA: `ppa:sqrammi/xpn` (https://launchpad.net/~sqrammi/+archive/ubuntu/xpn).
Packages: `xpn-client` and `xpn-server`. Both may be installed together. The server
runs its Node and packet processes as the single unprivileged account `xpn`;
only network configuration runs as root. Packages do not open ports/start the VPN
until setup is explicitly run. Existing data is retained on upgrade/removal.

## Install

```sh
sudo apt-get install software-properties-common ca-certificates curl gnupg
sudo add-apt-repository ppa:sqrammi/xpn
sudo apt-get update
sudo apt-get install xpn-client
```

Server only: XPN requires Node.js >=24.13.1. Noble's Node 18 and Resolute's Node 22
are insufficient. Install NodeSource's Node 24 package before `xpn-server`.
The following adds a separately signed repository; it may replace an existing
system Node.js installation. Inspect `apt-get -s install nodejs` first if other
applications use Node on this machine.

```sh
curl -fsSLo /tmp/nodesource.asc https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key
gpg --show-keys --with-fingerprint /tmp/nodesource.asc
# Verify against NodeSource's official repository instructions.
sudo install -d -m755 /etc/apt/keyrings
gpg --dearmor --output /tmp/nodesource.gpg /tmp/nodesource.asc
sudo install -m644 /tmp/nodesource.gpg /etc/apt/keyrings/nodesource.gpg
printf '%s\n' 'deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_24.x nodistro main' | sudo tee /etc/apt/sources.list.d/nodesource.list
sudo apt-get update
sudo apt-get install nodejs xpn-server
sudo xpn-server-setup --url https://vpn.example.com/xpn
```

Use an existing nginx HTTPS site and certificate. Setup auto-detects an unambiguous
site, configures the proxy, generates credentials on first installation, and
starts the services. `--nginx-site` and `--certificate` resolve ambiguity.
`--host-tcp-ports 22,443,5201` selects server ports reachable inside the VPN.
Reruns preserve secrets, device accounts and ports, change only what's needed,
and write a per-run report and configuration backups under `/var/backups/xpn/`.
`--plan` previews without changes. `--show-admin-token` displays the administrator
token locally as root; never include that output in logs or issue reports.

## Migrate an installer-managed checkout

Back up `/etc/xpn.env`, `/etc/xpn/install.json`, nginx/systemd configuration and
`/var/lib/xpn` while the control service is stopped. Keep backups root-only.
Install the package, then run:

```sh
sudo xpn-server-setup --url https://vpn.example.com/xpn --migrate-checkout
```

The migration preserves endpoint, database/master key, admin token, certificate
pins, SMTP configuration and allowed host ports. It backs up/removes managed
`/etc/systemd/system/xpn-*.service` checkout overrides, adopts the package's
vendor units, and writes only port/path/firewall settings in managed drop-ins.
Custom unmanaged units/drop-ins cause a refusal instead of being overwritten.
The checkout is retained for rollback. Expect a brief VPN interruption.

For rollback, stop XPN, restore the previous units/environment/install state from
the recorded backup, and remove the package-mode `xpn.conf` drop-ins in
`xpn-native.service.d` and `xpn-network.service.d` if they were newly created by
the migration. Run `systemctl daemon-reload`, then
`systemctl reenable xpn-control xpn-native xpn-network` to retarget boot links to
the restored units, and start the prior units.
Use the saved database snapshot only if a database change requires it; otherwise
retain newer accounts. Restore configuration before removing the package, whose
removal stops XPN. Do not purge data. Package upgrades stop XPN; rerun
`xpn-server-setup --url ...` afterward to validate and start the updated service.

## Client

```sh
xpn enroll ./device.json
sudo xpn connect ./device.json
```

Enrollment prompts for an invitation; see `xpn --help` for camera enrollment and
route options. Keep each device's profile private. Noble/OpenSSL 3.0 supports
PSK mode; ML-KEM hybrid needs OpenSSL 3.5+ on both endpoints and fails closed when
unavailable. Resolute supplies OpenSSL 3.5. Current full-tunnel Linux routing and
IPv6 policy are described in PROTOCOL.md.

For automatic startup and the updated client's built-in retries, see
[Linux client service setup](LINUX-CLIENT-SERVICE.md). The initial PPA release
requires the updated launcher from this checkout; the guide gives a manual
installation procedure using the existing native binary. A subsequent package
release will include both the updated launcher and setup command.

## Release workflow

Prepare each series with `packaging/prepare-source.py`, using the same
`SOURCE_DATE_EPOCH` and upstream source. Increment `--revision` for repeat uploads.
Build/test Noble on `little-guy-root`, Resolute on `seven-root` with
`dpkg-buildpackage -us -uc -b`; run `lintian` and the native/Node integration tests.
Create source uploads using `dpkg-buildpackage -S -sa -us -uc`.
Transfer only source upload artifacts to `ren`; sign using
`debsign -kA70890AEB9BAF73E3CFE3DC26D0FC16CDE281EDE *_source.changes`, then
`dput ppa:sqrammi/xpn *_source.changes`. Private signing keys remain on ren.
Launchpad rebuilds the signed source; local `.deb` files are not PPA uploads.
Verify Launchpad builds/publication and apt package provenance before migration.

The initial release targets amd64, matching the specified build hosts and Alta.
C source is never built on the Mac during this workflow. Exact host operations
and published versions are recorded separately in `PPA-RELEASE-2026-10-27.md`.
