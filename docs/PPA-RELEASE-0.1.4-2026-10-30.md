# XPN 0.1.4 PPA release

Destination: `ppa:sqrammi/xpn`, Ubuntu Noble and Resolute, amd64 client/server.
Versions: `0.1.4-0ubuntu1~noble1` and `0.1.4-0ubuntu1~resolute1`.
Committed source base: `03850d6bc7797386e7019a4532b565480f9e6901`, plus release
version/changelog updates and the corresponding version note in GATEWAY.md.

This release includes:
- Correct nftables syntax in Linux full-tunnel setup, with a real full-launcher
  regression test rather than only native transport testing.
- A disabled, gray subnet field in full mode, editable in selected-subnets mode;
  retained text is excluded from full-mode submissions. Contradictory explicit
  full-mode/subnet API input is rejected.
- General incoming-traffic mode governed by existing server firewall rules, with
  optional scoped WireGuard/source/service restrictions. Legacy saved policies
  remain restricted; no existing access is silently broadened.

## Reproducible sources and validation

Source epoch: `1793371472`.
Identical upstream archive SHA-256 for both series:
`c08fcc36703ddea7c4eaa6ce262483e5e7d06480ca322451320d0e6128061216`.

Local evidence: `build/ppa-release-0.1.4-20261030/`.
Build workspaces: `/root/xpn-release-0.1.4-20261030/SERIES/`, on
`little-guy-root` (Noble) and `seven-root` (Resolute). Transient units:
`xpn-release-014-20261030-SERIES.service`. Packages are installed only on these
build hosts for validation; test profiles, services and network namespaces are
cleaned up. Signing destination: `ren:~/xpn-release-0.1.4-20261030/release/`.
No C is built locally and this release task does not modify Alta or Draper.

Build jobs run native CTests, Python and Node tests, source/binary lintian,
full/split real-TUN traffic, peer ping, full Linux launcher firewall/routing
setup and cleanup, incoming traffic and external firewall enforcement, reverse
isolation, live disable, client reconnect, outer-TLS-only transport, standby
failover, wrong-pin rejection and installed client/gateway service smoke tests.
Resolute also tests hybrid ML-KEM.

## Validated, signed and uploaded

Both release jobs reached `VALIDATED`. Each passed 5 native CTests, 63 Python
tests, 13 Node tests, source/binary lintian with no errors, all listed real-TUN
and transport checks, and both installed-service smoke tests. Resolute's hybrid
ML-KEM check also passed. Build/test evidence, debs and source sets are retained
under `validated/noble/` and `validated/resolute/` in the local artifact directory.

All retrieved artifact hashes and both original upstream archives were verified
before staging on ren. After interactive signing, verified all DSC/buildinfo/
changes signatures against `A70890AEB9BAF73E3CFE3DC26D0FC16CDE281EDE`, all
signed manifest sizes/hashes and the expected source archive hashes. Both dput
uploads to `ppa:sqrammi/xpn` completed successfully.

Signed source sets remain at `ren:~/xpn-release-0.1.4-20261030/release/`.
Local signed manifests and upload logs:
`build/ppa-release-0.1.4-20261030/signed-upload-evidence.tar.gz` and its matching
extracted directory. The initial Launchpad API check listed no 0.1.4 source
records yet. Acceptance, builds and public signed APT indexes remain pending.
The 15-minute thread heartbeat `finish-xpn-0-1-4-ppa-publication` monitors these
quietly and will notify on verified completion or an actionable failure. No
production host was changed and no duplicate upload was performed.
