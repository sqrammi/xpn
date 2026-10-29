# XPN Ubuntu PPA release — October 29, 2026

Destination: `ppa:sqrammi/xpn`. Source snapshot corresponds to commit `38192dc`, including the release
version/documentation/source-preparation changes. Includes the latest committed client-owned retry
loop and the `xpn-client-setup` command. No C is built on the Mac.

Versions: `0.1.1-0ubuntu1~noble1` and `0.1.1-0ubuntu1~resolute1`.
A new upstream version is required because upstream source changed since the
published 0.1.0 archive. Source epoch: `1793302189`.
Both series' `xpn_0.1.1.orig.tar.xz` SHA-256:
`98dc7cd421f9cf68a97f3f57cce5f3c5d710eef8921c888b792bd2a0f2a4a0bb`.

## Queue and host changes

- Noble: `little-guy-root`, `/root/xpn-release-20261029/noble/`.
- Resolute: `seven-root`, `/root/xpn-release-20261029/resolute/`.
- Uploaded the corresponding source/test-script archive as
  `/root/xpn-release-20261029-SERIES-input.tar.gz`, extracted with
  `tar --no-same-owner` into a new root-only release workspace.
- Jobs use transient `systemd-run --collect` units named
  `xpn-release-20261029-SERIES`. They continue independently of SSH. Status is
  `BUILDING`, `FAILED` or `VALIDATED` in each workspace's `status` file;
  per-stage logs and artifacts remain there.
- Jobs refuse to replace packages if the build host has an active XPN server.
  After building, they install the new client/server packages on the build host
  to verify the installed entry points. Existing prerequisites are reused;
  no APT source, account or unrelated package changes are planned.
- TUN, firewall and routing tests use private namespaces. The installed service
  smoke test temporarily enables `xpn-client-releasecheck-20261029.service`,
  adds a `PrivateNetwork=yes` drop-in and uses dummy credentials. Its exit trap
  stops/disables/removes that test unit, drop-in and profile. Its journal, setup
  report under `/var/backups/xpn-client/`, and build artifacts are retained.
- Alta and Draper are not updated by this release job.

## Validation and publication

Local packaging regressions passed (48 tests, one Linux-only skip). Source
archives have matching hashes. The queued remote jobs perform native CTest,
Python and Node tests, source/binary lintian, real-TUN reconnect/transfer/cleanup,
outer-only transport, standby delay failover, wrong-pin rejection and the installed
service smoke test. Resolute additionally tests hybrid ML-KEM.

Both remote jobs reached `VALIDATED`. All 48 Python tests passed on each Linux
host, as did native CTest, Node checks, real-tunnel recovery and the installed
service smoke tests. Binary lintian reported no findings; source lintian
reported only the existing advisory about `pkg-config` versus `pkgconf`. Test
units and profiles were removed and server services remain inactive on the build
hosts. Installed test packages are now 0.1.1. No production server was changed.

Both checksum-verified source upload sets and the signing script are staged at
`ren:~/xpn-release-20261029/release/{noble,resolute}/`. The staging archive is
`ren:~/xpn-release-20261029-input.tar.gz`. After the user unlocked the signing key,
the previous staging directory was unexpectedly absent. Restored the original
validated source archive and successfully signed both series using the unlocked
key, without another passphrase prompt. The cause of the missing directory is
unknown.

Verified GPG signatures on each `.dsc`, source `.buildinfo` and `.changes` against
`A70890AEB9BAF73E3CFE3DC26D0FC16CDE281EDE`, validated their SHA-256 manifests,
and checked both upstream/Debian archives against the locally retained validated
source hashes. No private key material was copied. Verification/upload script:
`ren:~/xpn-release-20261029/release/verify-upload.py`; upload logs are each
series' `upload.log` in that directory.

Both `dput ppa:sqrammi/xpn` commands completed successfully. Upload logs confirm
that the `.dsc`, shared original archive, Debian archive, source `.buildinfo` and
`.changes` were transferred for each series. Signed manifest/log evidence is
also retained locally in `build/ppa-release-20261029/signed-source-evidence.tar.gz`.
Launchpad accepted both sources. Both builds now report `Successfully built`,
and the exact-version API lists both sources as `Published` at 20:14 UTC:

- [Noble build 33885508](https://launchpad.net/~sqrammi/+archive/ubuntu/xpn/+build/33885508)
- [Resolute build 33885509](https://launchpad.net/~sqrammi/+archive/ubuntu/xpn/+build/33885509)

At the 20:34 UTC check, both signed APT indexes verified against the expected
archive key and their Packages indexes matched the signed SHA-256 digests, but
both still offered only 0.1.0 binaries. Binary publication remains pending; source
publication alone is not enough. Evidence and a repeatable verifier are in
`build/ppa-release-20261029/apt-verification/` and
`build/ppa-release-20261029/verify-published.py`. The thread
follow-up `finish-xpn-ppa-publication` checks every 15 minutes, stays quiet on
unchanged processing status, and will notify on failure or verified availability
of both series. It must remove itself after completion. Do not treat this release as
installable until the PPA publishes the new packages.

At 21:19 UTC, exact-version binary API queries show both `xpn-client` 0.1.1
records as `Pending`, created around 21:01:56 UTC, with no publication time yet.
Both signed APT indexes still offer 0.1.0; no reupload or client changes are needed.

After publication, users can run:

```sh
sudo apt update
sudo apt install xpn-client
sudo xpn-client-setup ./xpn-profile.json --name alta
```

The profile must already be enrolled. The setup command enables boot startup and
runs `xpn connect` directly; retry/backoff lives inside the client. Unchanged
setup reruns leave an active connection alone. Check attempts with
`journalctl -u xpn-client-alta -f`.
