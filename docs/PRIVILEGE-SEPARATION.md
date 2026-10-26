# Server privilege separation

The supplied deployment separates privileged network setup from network-facing XPN services. It does not fork a process per client: all client connections use a shared native event loop with TUN and credential-refresh threads.

| Component | Identity | Access |
| --- | --- | --- |
| `xpn-network.service` | root, short-lived setup/teardown script | Configure persistent TUN, forwarding and XPN's nftables table; exits after setup |
| `xpn-control.service` | `xpn` | Node admin/enrollment, private database, protected credential socket |
| `xpn-native.service` | `xpn-packet`, with supplementary group `xpn` | Attach to owned TUN, read credential snapshots via socket, accept loopback WebSockets |

The native process has **no root privileges before authentication, during authentication, or after authentication**. Waiting until a peer authenticates would leave unauthenticated parsing exposed in a privileged process. POSIX threads share process credentials through libc's credential-changing wrappers, so per-connection `setuid` calls are not a suitable separation boundary in this event-loop architecture. [Linux NPTL credential behavior](https://man7.org/linux/man-pages/man7/nptl.7.html).

## Startup enforcement

The Linux `xpnd server` entry point now performs a mandatory check before curl/OpenSSL initialization, opening TUN, reading credentials, listening or creating workers:

- Reject root real/effective/saved UIDs, mismatched UIDs, root/mismatched GIDs and root supplementary group membership.
- Reject retained effective, permitted or inheritable Linux capabilities; clear ambient capabilities explicitly.
- Set and verify irreversible `no_new_privs`, so later threads/children inherit the restriction and cannot gain privileges from setuid executables/file capabilities.
- Disable process dumpability before loading device secrets.
- Exit on any failure. There is no `--allow-root` override.

The supervisor launches the server with its final identity. A manual `sudo xpnd server ...` invocation is rejected, even if the operator forgets the service restrictions. Start through `sudo systemctl start xpn-native` instead. The persistent TUN belongs to `xpn-packet`, so the daemon does not need `CAP_NET_ADMIN` to attach. Network configuration remains in the short-lived root helper.

The service also supplies an empty capability bounding/ambient set, `NoNewPrivileges=yes`, read-only system paths, protected home directories, restricted device access, hidden other-user processes, restricted namespaces and disabled core files. The bounds are process-wide inherited restrictions, not a claim of separate client sandboxes. See [systemd execution controls](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html) and [Linux no_new_privs](https://www.kernel.org/doc/html/latest/userspace-api/no_new_privs.html).

These checks apply to the production Linux **server executable**. The Linux client launcher still needs root to configure its local TUN/routes/firewall, and its native client privilege model is unchanged by this server change. Applications embedding the raw C library must provide their own equivalent startup confinement; a library cannot safely change the credentials of an arbitrary threaded host process.

## Node and packet-service boundary

The control process owns `/run/xpn` as `xpn:xpn`, mode `0710`. The socket is `0660`. The native service receives supplementary group `xpn` through systemd, giving it directory traversal and socket connection permission without permission to list or modify the directory.

The database directory remains `/var/lib/xpn`, owned by `xpn`, mode `0700`; database files are `0600`. `/etc/xpn.env` remains root-owned `0600`. The packet account cannot read the database or the Node process's environment, or replace the control socket. Its systemd mount namespace additionally masks `/var/lib/xpn` and `/etc/xpn.env`.

The credential socket intentionally supplies active device keys to the native service so it can authenticate sessions. Therefore a native memory compromise could still affect **all active VPN sessions and cached device credentials**. There is no per-client address-space/key isolation. The change limits operating-system privileges and separates the database/admin process; it does not claim that one compromised native connection is isolated from other connections within that process.

## Install or migrate on alta

The source changes must first reach `~/repo/xpn` on alta. No remote service has been changed by this task.

For a fresh manual installation, run `sudo sh deploy/create-users.sh` before starting the services, then follow [the alta deployment guide](ALTA-DEPLOYMENT.md). The package installer creates both accounts automatically.

For a running deployment using the older shared `xpn` account, schedule a brief VPN interruption and perform this sequence from `~/repo/xpn`:

```sh
# Stop clients before changing the persistent TUN owner and runtime permissions.
sudo systemctl stop xpn-native xpn-control xpn-network
sudo sh deploy/create-users.sh

cmake -S native -B build/native -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build/native
ctest --test-dir build/native --output-on-failure

sudo install -m 755 build/native/xpnd /usr/local/bin/xpnd
sudo install -m 755 deploy/network.sh /opt/xpn/deploy/network.sh
sudo install -m 644 deploy/xpn-control.service deploy/xpn-native.service \
  deploy/xpn-network.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start xpn-network xpn-control xpn-native
```

Stopping the current network service removes `xpn0`; restarting recreates it with the new owner. If upgrading from a version without `ExecStop`, run `sudo sh deploy/network.sh stop` after stopping all three services and before restarting. Do not chown your database to `xpn-packet`: it stays owned by `xpn`. Do not make `/var/lib/xpn` group-readable. Existing systemd drop-ins can override the shipped settings; inspect them before assuming the migration took effect.

## Verify on Linux

```sh
systemctl show xpn-native -p User -p Group -p SupplementaryGroups \
  -p NoNewPrivileges -p CapabilityBoundingSet -p AmbientCapabilities
systemctl status xpn-network xpn-control xpn-native --no-pager
ps -o pid,user,group,args -C xpnd
sudo stat -c '%U:%G %a %n' /run/xpn /run/xpn/control.sock /var/lib/xpn /etc/xpn.env
```

For **each server thread**, use its actual PID:

```sh
XPN_PID=$(systemctl show xpn-native -p MainPID --value)
sudo sh -c 'grep -E "^(Name|Uid|Gid|Groups|Cap(Inh|Prm|Eff|Bnd|Amb)|NoNewPrivs):" /proc/"$1"/task/*/status' sh "$XPN_PID"
```

Expect nonzero, identical real/effective/saved UID values for `xpn-packet`, `NoNewPrivs: 1` and zero capability masks. The network unit should be `active (exited)` with no persistent root process. The control process should run as `xpn`, not as root or `xpn-packet`.

`test_privilege` runs during Linux CTest. Its explicit root-only mode tests root rejection, saved-root UID rejection, root groups, retained capabilities, clean identity acceptance and restrictions inherited by threads/forked children, all in disposable child processes without creating users or changing networking:

```sh
sudo env ASAN_OPTIONS=detect_leaks=0 build/native/test_privilege --root
```

The Linux CI workflow runs those cases plus an actual `xpnd server` root-launch rejection. They have been added but not executed on this macOS host. Five mocked network lifecycle tests run locally without touching networking. Actual systemd/TUN permissions and connected-client behavior must be checked on the Ubuntu host after installation.
