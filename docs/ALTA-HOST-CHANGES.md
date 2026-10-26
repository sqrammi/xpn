# Alta host change record

**Status: build/test installation only; no persistent VPN deployment.**

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
| Normal installer/audit residue | APT lists/logs, account databases, `/root/.npm/` cache/logs, SSH/system logs | Package installation, account creation and test execution |

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

### October 26: CI fixture-access regression check

Read-only reproduction confirmed that `xpn` receives Node's `MODULE_NOT_FOUND` when attempting to load the existing fixture directly through private `/root`. Ran the updated TUN harness from the checkout: the negative check now fails immediately with an explicit access diagnostic; the private read-only wrapper passes both split/full TUN/NAT tests. Updated test/workflow source in place (code details are in the working tree). The only additional persistent test output on Alta is `~/repo/xpn/build/ci-fixture-negative.log`; the combined SSH output is local `build/alta-ci-fixture-fix.log`. No package, account, persistent service, live nginx or host-network change occurred. Temporary namespaces/mount views and fixture processes were cleaned up.

The exact APT transaction is retained in [ALTA-PACKAGES-2026-10-25.txt](ALTA-PACKAGES-2026-10-25.txt); the original is `/var/log/apt/history.log` on Alta. Local `build/alta-*.log` files contain dependency installation and test output. [VALIDATION.md](VALIDATION.md) records results and limits. [ALTA-DEPLOYMENT.md](ALTA-DEPLOYMENT.md) describes proposed future deployment, not completed installation.

The requested cleanup is complete: `/opt/xpn-test` and `xpn-packet` are gone. To retire the remaining test setup later, preserve wanted evidence, then remove only the generated `build/` artifacts and `node_modules` from the checkout; retain the source and Git history. Remove `xpn` only after checking for processes/owned files and any later deployment. Do not recursively delete its configured home. For package cleanup, simulate removal of the six newly requested packages (`cmake`, `ninja-build`, `pkg-config`, `libwebsockets-dev`, `libjansson-dev`, `libcurl4-openssl-dev`) and review dependencies against the attached 48-package list. Do not purge pre-existing `build-essential`/`libssl-dev`, blindly run `autoremove`, or clear shared npm/system logs. No nginx or host-network rollback is needed for this work.

The migration backup can recover the old test source/build files if needed; moving Node back would require updating test paths again. Restoring a second service identity is unnecessary for the chosen single-account design. No rollback has been performed.

Future Alta mutations must append a dated entry here with the commands, affected paths/services, validation, and rollback information. Keep code implementation details in Git history.
