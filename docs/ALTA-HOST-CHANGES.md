# Alta host change record

**Status: installed and running at https://alta.jeffhansen.com/xpn/; unchanged installer rerun verified October 26.**

Before the live installation described below: stock XPN unit files are now present in `/etc/systemd/system`, and `xpn-control` was reported as activating while `/etc/xpn.env` was absent. These appeared after the earlier audit and were not installed or started by the installer-development work below. The live installer subsequently adopted these stock templates and replaced their `/opt` references with the existing checkout.

Host: `alta.jeffhansen.com`, Ubuntu 26.04.1 Resolute, x86-64. Initial work October 25, 2026; migrated to the existing checkout and one service account October 26, 2026 (America/Denver). Commands below describe completed work, not instructions to run again. Code changes are intentionally excluded.

## What remains on the host

| Change | Location / identity | Purpose |
| --- | --- | --- |
| 48 new Ubuntu packages; no upgrades/removals | System package database; exact versions in [package record](ALTA-PACKAGES-2026-10-25.txt) | Compile/test the C server |
| In-place build/test workspace | `/root/repo/xpn/` (existing `~/repo/xpn` checkout) | No separate runtime/source tree under `/opt` |
| Private Node 24.22.1 and bundled npm | `/root/repo/xpn/build/tools/node-v24.22.1-linux-x64/` | Backend tests; `/usr/bin/node` remains 22.22.1 |
| Download archive and checksum list | `/root/repo/xpn/build/tools/node-v24.22.1-linux-x64.tar.xz`, `SHASUMS256.txt` | Moved with the verified runtime; no new download |
| Locked JavaScript dependencies | `/root/repo/xpn/node_modules/` | Reinstalled in place with lifecycle scripts disabled |
| Native build outputs | `/root/repo/xpn/build/native/` | Fresh CMake/Ninja build against this checkout |
| Migration backup/evidence | `/root/repo/xpn/build/host-migration-2026-10-26/` | `previous-opt-source.tar.gz` and test logs |
| One non-login service account/group | `xpn`: UID 996, primary GID 998 | Both Node and C services; `xpn-packet` removed |
| Live credentials and install record | `/etc/xpn.env` and `/etc/xpn/install.json`, root-only mode 0600 | Generated independent admin/master keys; incremental rerun state |
| Installed/enabled services | `/etc/systemd/system/xpn-{network,control,native}.service` and corresponding `multi-user.target.wants/` symlinks | Non-root backend/native services; brief root network setup |
| Private checkout mount view | `/run/xpn-source` inside service mount namespaces | Read-only source access with `/root` still private |
| Runtime/database | `/run/xpn`, `/var/lib/xpn` | Control socket and encrypted device database |
| nginx integration | `/etc/nginx/conf.d/xpn-http.conf`, `/etc/nginx/snippets/xpn-locations.conf`, include in `/etc/nginx/sites-available/default` | HTTPS-only `/xpn` console/API and WebSocket route; loopback 3300/3301 |
| VPN networking | `xpn0`, route `10.77.0.0/24`, nftables `inet xpn`, IPv4 forwarding | TUN/NAT for authenticated clients |
| Installer reports/backups | `/var/backups/xpn/<timestamp>/`; `/run/lock/xpn-install.lock` | Exact change reports, command logs, prior configuration, concurrent-run lock |
| Normal installer/audit residue | APT lists/logs, account databases, `/root/.npm/` cache/logs, SSH/system logs | Package installation, account creation and test execution |

## Live installation and rerun verification — October 26

Ran from `/root/repo/xpn`, using the existing root SSH connection:

```sh
python3 deploy/install-server.py --url https://alta.jeffhansen.com/xpn
```

The installer used existing packages, the existing `xpn` account, and the existing private Node runtime. **No additional APT install/update, account creation, system Node replacement, certificate/key modification, or `/root` permission change occurred.** No device accounts or invitation emails were created. No PPA or cloud firewall settings were changed.

1. **18:13:22 UTC — first attempt, safely rolled back.** Report directory `/var/backups/xpn/20261026T181322898883Z/`. Stopped the already-activating stock control service; ran locked `npm ci --omit=dev --ignore-scripts`, CMake/Ninja and all three passing CTests in the checkout. Generated root-only `/etc/xpn.env`; replaced the three stock service files; added the two nginx snippets and the selected server-block include. Reloaded systemd, started all XPN services, checked authenticated local administration, and reloaded nginx. The immediate HTTPS check hit an old nginx worker and returned 404. The installer stopped affected services, removed its new nginx files, restored the original site/unit files, reloaded systemd/nginx and requested restart of the formerly activating stock control unit. It retained the new environment file, database, npm/build outputs and global IPv4 forwarding. `xpn0` and its nftables table were removed by network stop. Credentials were never printed. Output: `build/installer-live-first.log`.
2. **Temporary regression tests and readiness correction.** Re-ran isolated Python tests; a test initially encountered the now-present production database through an unmocked existence check. Fixed the fixture isolation, then all 22 tests then passed locally and on Alta (23 after the final permission-repair regression). No test modified production configuration. Added bounded HTTPS readiness retries because nginx's systemd reload signals the master before new workers necessarily accept connections. Implementation changes are in Git, not enumerated here.
3. **18:15:29 UTC — successful installation.** Report directory `/var/backups/xpn/20261026T181529916342Z/`. Reused the retained credentials/database; reran npm and the native build/tests because no successful build record yet existed (Ninja reported no work). Replaced the three stock units and installed the proxy snippets/include again. Started all three services and reloaded nginx. HTTPS returned 200 on the second readiness attempt. Enabled all three startup symlinks and created `/etc/xpn/install.json`. Output: `build/installer-live-second.log`.
4. **18:16:18 UTC — HTTPS-only route correction.** Report directory `/var/backups/xpn/20261026T181618355954Z/`. The existing selected nginx block listens on both 80 and 443. Re-running the installer after adding XPN-only HTTP rejection updated **only** `/etc/nginx/snippets/xpn-locations.conf` and reloaded nginx. It did not build, rewrite units/secrets/state, or restart XPN. Output: `build/installer-https-only.log`.
5. **18:16:55 UTC — verified no-op rerun.** Report directory `/var/backups/xpn/20261026T181655507441Z/`. Compared 512 configuration/native-build/Node-dependency files before and after: identical bytes, modification times, inodes and modes. Service PIDs/activation timestamps, `xpn0` ifindex and the nftables ruleset were unchanged. No package/account/build/configuration/start/stop/enable/reload actions occurred. Only installer audit files and ordinary request logs were added. Evidence: `build/installer-noop.log` and `build/installer-noop-verification.json` on Alta.

Each report directory contains `changes.md` and `actions.log`; runs that changed configuration also contain `manifest.json` and backups at matching paths. These directories are mode 0700 and can contain secret configuration backups; do not publish them. Each file/resource action is recorded in the concise report, including rollback actions. The run folders are an audit trail, not a shell-script undo operation.

Final live configuration:

- `/etc/systemd/system/xpn-control.service`: non-root `xpn`, read-only checkout at `/run/xpn-source`, private Node, protected home/system, root-owned environment file.
- `/etc/systemd/system/xpn-native.service`: non-root `xpn`, checkout-built C binary, loopback port 3301 and `/xpn/vpn`; no capabilities and no-new-privileges.
- `/etc/systemd/system/xpn-network.service`: root oneshot calls the checkout's network script; no persistent root VPN process. Creates `xpn0` at `10.77.0.1/24`, MTU 1400, and the dedicated `inet xpn` filtering/NAT table. Applies `net.ipv4.ip_forward=1`, `net.ipv4.conf.xpn0.rp_filter=2`, and `net.ipv4.conf.xpn0.accept_source_route=0`.
- `/etc/nginx/conf.d/xpn-http.conf`: WebSocket connection map and XPN request/connection zones.
- `/etc/nginx/snippets/xpn-locations.conf`: console/API to loopback 3300, WebSocket to 3301; plain HTTP rejected for XPN paths.
- `/etc/nginx/sites-available/default`: one added include in the selected server; other locations, including `/ips/` on port 3001, remain intact. Existing `sites-enabled` symlink is preserved.
- `/etc/xpn.env`: independent generated `ADMIN_TOKEN`/`MASTER_KEY`, public URL, loopback backend port, data/socket paths and certificate pin. `/etc/xpn/install.json`: successful-install metadata and hashes. Both are mode 0600; no secret values appear in this document.
- `/run/xpn` and `/var/lib/xpn`: runtime socket and persistent database initialized by the control service. `/root/.npm/` logs/cache and normal system/journal/nginx access logs also contain installation activity.

Verified public HTTPS console **200**, unauthenticated HTTPS admin API **401**, plain-HTTP console and WebSocket paths **404**. Both running service processes have UID 996/GID 998, zero effective capabilities, and `NoNewPrivs: 1`. All three XPN services are active and enabled. This verifies live installation, proxy access and privilege separation; at that point a real client session had not yet been tested. The later Mac session and host-access repair are recorded below; iOS and Internet throughput remain untested.

To unlock the console, run `sudo python3 ~/repo/xpn/deploy/install-server.py --show-admin-token` on Alta and paste it at https://alta.jeffhansen.com/xpn/. Keep the master key with database backups.

For deliberate removal, stop/disable `xpn-native`, `xpn-control`, then `xpn-network`; network stop removes only `xpn0` and `inet xpn` and leaves global forwarding alone. Preserve `/etc/xpn.env` and `/var/lib/xpn`. Remove the XPN server-block include and two generated nginx snippets together, validate with `nginx -t`, then reload. Remove the three generated units only after stopping/disabling them and run `systemctl daemon-reload`. Restore a backed-up shared nginx file only after checking for subsequent unrelated edits. Rollback does not restore old binaries or databases. These removal steps have **not** been executed.

## Host-access repair and first live Mac session — October 26, 13:26–13:48 Denver

The first Mac connection succeeded but could not reach Alta itself. Read-only inspection found `inet xpn input` dropped all traffic from `xpn0`; the native destination policy also rejected `10.77.0.1`. No unrelated host firewall rules were changed.

1. The user disconnected XPN to restore direct SSH access. Copied the repair and its tests into the existing checkout. Built a separate test tree with `cmake -S native -B build/native-host-access -G Ninja -DCMAKE_BUILD_TYPE=Release`, `cmake --build build/native-host-access -j2`, and CTest. The initial namespace test reproduced the native gateway rejection; after correcting it, all three CTests and real split/full TUN tests passed. Tests ran through `native/tools/test-as-xpn.sh --root` in disposable network/mount namespaces and removed their temporary resources. They verified HTTP to both the server's tunnel/WAN addresses, gateway ping, blocking of an unlisted listening port, NAT forwarding and non-root server threads.
2. Ran six native transport cases through the non-root wrapper with `XPN_TEST_CONNECT_ADDRESS=127.0.0.1`. Ordinary CA/hostname validation, custom SNI, HTTP Host preservation, wrong-pin rejection, pin rotation, packet exchange and revocation passed. These used temporary loopback nginx instances/certificates and did not modify live nginx.
3. At **19:39:49 UTC**, ran `python3 deploy/install-server.py --url https://alta.jeffhansen.com/xpn --host-tcp-ports 85,443`. Exact report/backups: `/var/backups/xpn/20261026T193949525848Z/`. It rebuilt/tested `build/native`, restarted the affected XPN services, updated `/etc/systemd/system/xpn-network.service` with `Environment=XPN_HOST_TCP_PORTS=85,443`, and updated `/etc/xpn/install.json` to preserve that selection on reruns. Network setup recreated `xpn0` and replaced only `inet xpn`. No APT/account/credential/certificate/nginx changes occurred, and nginx was not reloaded. Output: `build/host-access-install.log`.
4. Live host policy now permits VPN-source ICMP echo requests at 25/second (burst 50), TCP **85** (existing SSH) and **443** (HTTPS), plus established/related replies. Source validation, loopback/metadata rejection, other host-port drops, peer-to-peer blocks and existing forwarding/NAT remain. New installations default to host TCP 22,443; Alta explicitly uses 85,443. The native policy allows the gateway only when the device's full/split routes authorize it.
5. The user relaunched the rebuilt Mac app and connected at **13:42:23 Denver**. macOS reported connected at **13:42:26**, about 3.4 seconds after extension start was requested. Live checks from VPN address `10.77.0.3`: ping to `10.77.0.1` returned both replies (about 42–49 ms); `https://alta.jeffhansen.com/xpn/` returned 200 in about 0.16 seconds; certificate-validated HTTPS explicitly routed to `10.77.0.1` returned 200 in about 0.15 seconds. Alta's SSH socket showed the connection's peer as `10.77.0.3`, confirming access through the VPN. The user connection remained running after these checks.
6. At **19:47:36 UTC**, all 25 Python regressions passed on Alta and an installer rerun without `--host-tcp-ports` preserved 85/443, reported no installation changes, and retained the native service PID. Report: `/var/backups/xpn/20261026T194736464589Z/changes.md`; output: `build/host-access-noop.log`. Updated this host record and operational documentation in the existing checkout.

Additional retained test outputs on Alta: `build/native-host-access/`, `build/host-access-python.log`, `build/host-access-build.log`, `build/host-access-tun.log` and `build/host-access-install.log`. No additional packages/accounts or persistent test services were created. Local Mac evidence: `build/apple-connect-dns.log`, `build/apple-tunnel-timeline.log`, `build/apple-dns-fix-live-timing.log`, `build/apple-dns-fix-native.log`, `build/apple-dns-fix-build.log` and `build/dial-address-integration.log`. The Mac framework rebuild retained its previous version at `clients/apple/Frameworks/XPNNative.previous-20261026133937-28416.xcframework`. No credentials were printed or reissued. Restoring the prior network unit/rules would re-block host access; use the installer with the desired `--host-tcp-ports` to change the policy deliberately.

## Optional packet encryption — October 26

1. Copied updated source into `/root/repo/xpn` with `tar --no-same-owner`; built isolated `build/native-options` and `build/native-options-asan` directories. All four CTests passed in Release and with AddressSanitizer/UndefinedBehaviorSanitizer. Temporary nginx fixtures tested all four inner-encryption/PQ selections, custom SNI, certificate pins, IP-address dialing, revocation, wrong-pin rejection and required-PQ rejection against a classical-only outer endpoint. The namespace harness passed single-layer real split/full TUN/NAT and server-host access with non-root threads. Fixtures removed their temporary processes, certificates, network namespaces and mounts. These tests did not change live nginx or host firewall rules.
2. After the user disconnected, at **21:10:27 UTC** ran `python3 deploy/install-server.py --url https://alta.jeffhansen.com/xpn`. Report: `/var/backups/xpn/20261026T211027875321Z/changes.md`; complete commands/output: sibling `actions.log` and checkout `build/encryption-options-install.log`. The installer stopped `xpn-native`, rebuilt/tested `build/native` (four passing tests), stopped `xpn-control`, then started both. It reused `/run/xpn` and `/var/lib/xpn` and updated only `/etc/xpn/install.json` among configuration files. The existing network service and nginx kept running; nginx syntax was checked, without reload. Host TCP ports 85/443 were retained. No packages, accounts, unit files, nginx configuration, credentials, certificates or device profiles were changed. Public HTTPS readiness passed. Both restarted daemons were verified as UID 996/GID 998, `CapEff: 0`, `NoNewPrivs: 1`.

3. Final review corrected a raw-record batching defect. Rebuilt the isolated Release and sanitizer trees; all four tests passed in each, including a 1,000-packet keepalive-interleaving regression. A temporary-nginx single-layer/PQ test passed across a 25-second idle period; a legacy v1 client also passed. After verifying there were no established connections to the VPN backend, at **21:13:11 UTC** reran the same installer command. Report: `/var/backups/xpn/20261026T211311569844Z/changes.md`; output: `build/encryption-framing-install.log`. It rebuilt/tested the runtime binary, restarted **only `xpn-native`**, and updated `/etc/xpn/install.json`. Control, network and nginx services remained running. All service/readiness checks passed; no other configuration or credential changes occurred.

4. At **21:13:37 UTC**, reran the installer unchanged. It reported **no installation changes**; no build, service restart, configuration rewrite or nginx reload occurred. Report: `/var/backups/xpn/20261026T211337475685Z/changes.md`; output: `build/encryption-options-noop.log`. Updated this host record and validation/protocol documentation in the existing checkout.

Retained evidence: `build/encryption-options-*.log`, `build/encryption-framing-*.log`, and the two isolated native build trees on Alta. The extra builds are test artifacts, not runtime installations. Installer backups restore configuration only; reverting executable behavior requires rebuilding the desired prior source and rerunning the installer while clients are disconnected. No rollback has been performed.

## Standby connections and 15-second keepalives — October 26

1. Copied source/test updates into `/root/repo/xpn` without changing the live executable. Built separate `build/native-standby` and `build/native-standby-asan` trees. Five CTests passed, including actual socket keepalive queries and authenticated standby association tests; the same suite passed AddressSanitizer/UndefinedBehaviorSanitizer. Temporary nginx/relay fixtures injected 700 ms response delays for all four encryption/PQ combinations, and tested abrupt primary closure, spare replenishment, packet exchange, pin rejection and revocation. Real split/full TUN/NAT tests passed with single-layer packets and paired connections. Fixture namespaces, mounts, temporary certificates and processes were cleaned up. Evidence: `build/standby-build.log`, `build/standby-tests.log`, `build/standby-matrix.log`, `build/standby-acceptance.log`.
2. Counted established connections on loopback port 3301 and found **zero**. Rechecked immediately before installation. At **21:36:31 UTC**, ran `python3 deploy/install-server.py --url https://alta.jeffhansen.com/xpn`. Report/backups: `/var/backups/xpn/20261026T213631277383Z/`; checkout log: `build/standby-install.log`. The installer stopped `xpn-native`, rebuilt and tested `build/native` (five passes), stopped `xpn-control`, updated `/etc/nginx/snippets/xpn-locations.conf`, restarted both application services, validated nginx and reloaded it, then updated `/etc/xpn/install.json`.
3. The XPN VPN location now enables `proxy_socket_keepalive on` and allows 16 connections per source address (previously eight), accommodating two streams per client. The existing shared nginx listening socket, certificate/key and other locations were not rewritten. Native client/server sockets now explicitly configure 15-second idle/interval timers and three keepalive retries. nginx's separate upstream-side socket uses its operating-system defaults; the native end has explicit 15-second timers. The standalone sample nginx config includes 15-second listener timers for new deployments, but was not installed over Alta's shared site.
4. The network service/rules remained running and unchanged; host TCP ports **85/443** were preserved. No packages, accounts, systemd unit definitions, credentials, device profiles or database keys were changed. Existing v1/v2 clients remain supported. HTTPS readiness passed. Both restarted daemons were verified as UID 996/GID 998, zero effective capabilities, and `NoNewPrivs: 1`.
5. At **21:42:54 UTC**, reran the installer unchanged: **no installation changes**, build, service restart or nginx reload. Report: `/var/backups/xpn/20261026T214254677929Z/changes.md`; output: `build/standby-noop.log`. Updated protocol/validation/host documentation in the same checkout.

For rollback, preserve credentials/database, rebuild the selected older source and rerun the installer while clients are disconnected; review the saved nginx snippet before restoring it. Configuration backups do not revert binaries. No rollback was performed. No PPA upload, Git push, SMTP email or cloud control-plane change occurred.

## Iperf host-port installation repair — October 26, 22:15 UTC

The user's run at `/var/backups/xpn/20261026T220604966207Z/` failed with `Address already in use` and rolled back, leaving only host TCP ports 85/443 allowed. Read-only inspection and disposable loopback-socket tests reproduced a false conflict from recently closed connections; no production service was stopped for that reproduction.

1. Ran 27 installer/network tests successfully in the existing checkout. Evidence: `build/installer-port-fix-tests.log`. The socket regression used temporary ephemeral loopback ports; it did not change host configuration.
2. After confirming no established VPN backend connections, ran from `/root/repo/xpn`:
   ```sh
   python3 deploy/install-server.py --url https://alta.jeffhansen.com/xpn --host-tcp-ports 85,443,5201
   ```
   Successful report: `/var/backups/xpn/20261026T221520052743Z/changes.md`; output: `build/iperf-port-install.log`.
3. `xpn-native.service`: stopped; CMake/Ninja checked the existing native artifacts (no compilation needed), and all five native CTests passed. `xpn-network.service`: stopped. `/etc/systemd/system/xpn-network.service`: updated `XPN_HOST_TCP_PORTS` to `85,443,5201`. Reloaded systemd unit definitions and started network/native services. The control service remained running.
4. `xpn0` and the dedicated `inet xpn` table: recreated by network service startup with the existing address/MTU/NAT and sysctl settings. The input rule now permits authenticated VPN traffic to host TCP **85,443,5201**, plus the existing ping allowance. `/etc/xpn/install.json`: updated successful-install/build fingerprints. No nginx configuration/reload, package/account change, certificate change, credential rotation or database change occurred.
5. From the connected Mac (`10.77.0.3`, route through `utun10`), `iperf3 -c 10.77.0.1 -t 3 --connect-timeout 3000` completed: 11.3 Mbps received, 12.9 Mbps sent, 1,158 sender retransmissions. This verifies TCP connectivity, not the throughput target. Two established VPN backend streams were observed.
6. At **23:02:20 UTC**, reran the installer without specifying host ports. It retained **85,443,5201** and reported **no installation changes**, with no build/restart/reload. Report: `/var/backups/xpn/20261026T230220295091Z/changes.md`; output: `build/iperf-port-noop.log`. Updated this record and the validation document in the checkout.

To remove the added access, rerun the installer with `--host-tcp-ports 85,443` while clients are disconnected; this restarts network/native services. The successful report retains the prior configuration. No rollback was performed after the successful installation.

## Initial steps performed — October 25 (historical layout)

1. **Inspected the host over existing root SSH access.** Checked OS, tools, free disk, listeners, nginx configuration/certificate metadata and the existing checkout. No SSH configuration, authorized keys or certificate files were edited. An initial `git fetch origin` in `/root/repo/xpn` failed with GitHub `Permission denied (publickey)`; the chained merge/install did not execute. No checkout changes were applied by that attempt.

2. **Created an isolated source workspace.** Archived local commit `623e40b` with `git archive`, transferred it over SSH, and extracted it into `/opt/xpn-test/src`. Later transferred the TUN test fixtures into that workspace. The existing `/root/repo/xpn` checkout was not used as an installation directory. No remote Git credentials were added.

3. **Installed Ubuntu build dependencies.** Ran as root:

   ```sh
   apt-get update -qq
   DEBIAN_FRONTEND=noninteractive apt-get install -y \
     build-essential cmake ninja-build pkg-config libssl-dev \
     libwebsockets-dev libjansson-dev libcurl4-openssl-dev
   ```

   APT recorded October 26, 03:27:02–03:27:13 UTC (October 25, 21:27:02–21:27:13 Denver). `build-essential` and `libssl-dev` were already installed/current. APT installed 48 packages, downloaded 26.3 MB, and estimated 93.1 MB additional installed space. It reported **0 upgrades, 0 removals, and no services requiring restart**. No repository/PPA was added. Standard package triggers updated linker/manual/info caches.

4. **Installed a private Node runtime.** Created `/opt/xpn-test/tools`; downloaded `SHASUMS256.txt` and `node-v24.22.1-linux-x64.tar.xz` from `https://nodejs.org/dist/v24.22.1/`. Checked the matching published SHA-256 with `sha256sum -c`, then extracted the archive. Selected its `bin` directory using a shell-local `PATH` for test commands. No global Node replacement, shell-profile edit, symlink or alternatives change was made.

5. **Installed test dependencies and built the server.** From `/opt/xpn-test/src`, using the private Node runtime:

   ```sh
   npm ci --omit=dev
   npm test
   npm run check
   cmake -S native -B build/native -G Ninja -DCMAKE_BUILD_TYPE=Release
   cmake --build build/native -j2
   ctest --test-dir build/native --output-on-failure
   build/native/test_privilege --root
   ```

   Ten backend tests and three native CTests passed. npm populated the workspace's `node_modules` and root's npm cache/logs. Backend tests created temporary databases/sockets; no production database was installed. The native executable stayed in the build directory; `cmake --install` was not run.

6. **Created two system accounts.** Ran `sh deploy/create-users.sh`, which created groups `xpn` and `xpn-packet` and matching system users with `/usr/sbin/nologin` shells. Their configured home paths are `/var/lib/xpn` and `/nonexistent`; neither home directory was created. Supplementary `xpn` membership was assigned only to test processes, not persistently to the packet account. Ran the privilege test as `xpn-packet`, and verified an actual root `xpnd server` invocation refuses to start.

7. **Ran temporary nginx/transport tests.** Ran `server/native-integration.mjs` as `xpn-packet` for legacy trust, custom SNI, wrong pin, trusted certificate/wrong pin, pin rotation, pin-only, and hybrid/custom-SNI cases. These launched separate nginx processes on ephemeral loopback ports, with temporary certificates, profiles and control sockets under `/tmp/xpn-nginx-*`. They did not reload the installed nginx service or use its production certificate. Test processes and temporary directories were removed. All cases passed.

8. **Ran isolated real-TUN tests.** Ran `python3 native/tests/tun-integration.py build/native/xpnd` as root with the private Node on `PATH`. The harness used disposable network namespaces: Node ran as `xpn`, the VPN server ran as `xpn-packet`, and test clients/HTTP/nginx fixtures were temporary. TUN/veth devices, routes, forwarding sysctls and the `inet xpn` nftables table existed **only inside those namespaces**. Split/full routing and NAT passed with a verified 1 MiB transfer. All server threads had non-root IDs, zero capabilities and `NoNewPrivs: 1`. Cleanup terminated fixtures and removed temporary profiles, directories and namespaces. No host routes, forwarding settings or firewall rules were changed by these tests.

9. **Checked deployment files without installing them.** `systemd-analyze verify` reported the expected missing `/usr/local/bin/xpnd` and `/opt/xpn/deploy/network.sh` paths. No XPN units were installed, enabled or started; no daemon-reload was performed. Audited the remaining state again on October 26.

## Migration to the requested layout — October 26

1. Inspected `/root/repo/xpn`: clean checkout at `4d46eb2`. Checked that `xpn-packet` had no running processes and that no files on the host root filesystem belonged to UID 995/GID 994. No persistent XPN services were installed.
2. Preserved the old source/build workspace before removal:
   ```sh
   cd /root/repo/xpn
   mkdir -p build/host-migration-2026-10-26
   tar -czf build/host-migration-2026-10-26/previous-opt-source.tar.gz -C /opt/xpn-test src
   ```
   Applied the requested single-account updates to this existing checkout without resetting Git or replacing the checkout. Source changes remain reviewable in its working tree; implementation details belong in Git history.
3. Moved `/opt/xpn-test/tools` to `/root/repo/xpn/build/tools` after verifying the destination did not exist. This moved the existing verified Node runtime, archive and checksums; it did not install another system runtime or edit shell profiles. The final ownership audit found that the original tar extraction had preserved the archive's numeric owner (displayed as the existing `vpn` user). Rechecked the download SHA-256 and compared the entire extracted tree with the archive, then ran `chown -R root:root build/tools/node-v24.22.1-linux-x64` so the retained runtime is root-owned.
4. Selected the private Node in the command's `PATH`, ran `npm ci --omit=dev --ignore-scripts`, ten backend tests and syntax checks. Ran `deploy/create-users.sh` (now idempotently provisions only `xpn`). Configured and built a **fresh** `build/native` with CMake/Ninja; did not reuse the old path-bound CMake cache. All three native tests and the explicit root/privilege inheritance cases passed.
5. Tested as `xpn` using `native/tools/test-as-xpn.sh`. It temporarily bind-mounts the same checkout read-only inside a private mount namespace, so non-root tests can access it without opening `/root` or copying code. The TUN harness's root orchestration still launches Node and C as `xpn`. Both split/full real-TUN/NAT transfers passed, with zero capabilities and no-new-privileges verified for every server thread. All six nginx/pinning cases and hybrid/custom-SNI passed; the hybrid rerun followed a test-wrapper variable-name fix. Five network-script tests and actual root-server refusal passed.
6. Verified future service access with a transient, automatically collected unit:
   ```sh
   systemd-run --unit=xpn-checkout-access-test --collect --wait --pipe \
     -p User=xpn -p Group=xpn -p ProtectHome=yes -p ProtectSystem=strict \
     -p BindReadOnlyPaths=/root/repo/xpn:/run/xpn-source \
     -p NoNewPrivileges=yes -p CapabilityBoundingSet= \
     /usr/bin/env /run/xpn-source/build/tools/node-v24.22.1-linux-x64/bin/node --version
   ```
   It printed `v24.22.1` and exited successfully. An earlier attempt specifying the namespace-only executable directly was rejected before launch. Removed the empty `/run/xpn-source` mountpoint after the successful unit exited. No persistent unit file was installed.
7. Rechecked the obsolete account's UID/GID, processes and owned files; ran `userdel xpn-packet` and removed its group if still present. No home-directory deletion was used. `xpn` remained UID 996/GID 998.
8. Verified the backup archive, removed only `/opt/xpn-test/src`, then removed the now-empty `/opt/xpn-test` directory. The backup remains under the existing checkout. No package removal or additional APT install occurred.
9. Copied the migration logs and this updated host record into the checkout. Set the transferred source/documentation files to `root:root` to avoid retaining local archive UID/GID metadata. Verified `/root` remains mode `0700`, system Node remains 22.22.1, nginx remains active, and no XPN host network resources or persistent services were installed.

## Verified deployment boundary — after October 26 migration

- No XPN systemd units, running XPN test daemon, host `xpn0`, or host `inet xpn` table remained at audit.
- `/opt/xpn`, `/usr/local/bin/xpnd`, `/etc/xpn.env`, `/var/lib/xpn`, `/run/xpn` and the proposed nginx XPN include files were absent.
- Live nginx remained active. No live nginx configuration/reload, TLS certificate change, public listener, SMTP setup/email, PPA publication or cloud control-plane change was performed by this work.
- Existing nginx has an `/ips/` upstream on port 3001. Future XPN deployment must choose another native port and check availability; it must not take over that route.
- Root access was used for installation/account setup and namespace orchestration. In the new tests both Node and the connected C server ran as `xpn`; no persistent root VPN process was installed.

## Evidence and cleanup

### October 26: automated installer development and validation

Copied `deploy/install-server.py` and its temporary-file tests into the existing checkout, then ran `--url https://alta.jeffhansen.com/xpn --plan` and the Python test suite. The preview selected the existing `/etc/nginx/sites-available/default` HTTPS block, `/etc/ssl/cert.pem`, private Node under `build/tools`, and backend ports 3300/3301. It recognized the newly present stock service templates without modifying them. All 16 installer/network tests passed. Validated generated unit files using `systemd-analyze verify` and generated nginx snippets using `nginx -t` in a temporary directory, then removed the temporary files. The existing certificate/key were read by nginx for syntax validation and were not copied or changed.

Updated documentation and installer source remain in `~/repo/xpn`. Local logs are `build/alta-installer-plan.log`, `build/alta-installer-config-validation.log` and `build/installer-tests.log`. **At this earlier validation stage the install command had not yet been executed:** this stage did not write `/etc/xpn.env`, modify installed systemd/nginx files, start/stop/enable/reload services, add packages/accounts, or change host networking. The later live runs are recorded above with their root-only backup/report directories.

### October 26: CI fixture-access regression check

Read-only reproduction confirmed that `xpn` receives Node's `MODULE_NOT_FOUND` when attempting to load the existing fixture directly through private `/root`. Ran the updated TUN harness from the checkout: the negative check now fails immediately with an explicit access diagnostic; the private read-only wrapper passes both split/full TUN/NAT tests. Updated test/workflow source in place (code details are in the working tree). The only additional persistent test output on Alta is `~/repo/xpn/build/ci-fixture-negative.log`; the combined SSH output is local `build/alta-ci-fixture-fix.log`. No package, account, persistent service, live nginx or host-network change occurred. Temporary namespaces/mount views and fixture processes were cleaned up.

The exact APT transaction is retained in [ALTA-PACKAGES-2026-10-25.txt](ALTA-PACKAGES-2026-10-25.txt); the original is `/var/log/apt/history.log` on Alta. Local `build/alta-*.log` files contain dependency installation and test output. [VALIDATION.md](VALIDATION.md) records results and limits. [ALTA-DEPLOYMENT.md](ALTA-DEPLOYMENT.md) describes the installer and its reuse; the live-installation section above records completed installation.

Historical migration cleanup was completed before the live installation: `/opt/xpn-test` and `xpn-packet` are gone. The following historical test-workspace cleanup advice applies only after retiring the live services described above. To retire the remaining test setup later, preserve wanted evidence, then remove only the generated `build/` artifacts and `node_modules` from the checkout; retain the source and Git history. Remove `xpn` only after checking for processes/owned files and any later deployment. Do not recursively delete its configured home. For package cleanup, simulate removal of the six newly requested packages (`cmake`, `ninja-build`, `pkg-config`, `libwebsockets-dev`, `libjansson-dev`, `libcurl4-openssl-dev`) and review dependencies against the attached 48-package list. Do not purge pre-existing `build-essential`/`libssl-dev`, blindly run `autoremove`, or clear shared npm/system logs. That earlier test-only migration needed no nginx or host-network rollback; the later live installation does, as described above.

The migration backup can recover the old test source/build files if needed; moving Node back would require updating test paths again. Restoring a second service identity is unnecessary for the chosen single-account design. No rollback has been performed.

Future Alta mutations must append a dated entry here with the commands, affected paths/services, validation, and rollback information. Keep code implementation details in Git history.
