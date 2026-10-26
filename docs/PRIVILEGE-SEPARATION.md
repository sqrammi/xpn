# Server privilege separation

The supplied deployment separates privileged network setup from network-facing XPN services. It does not fork a process per client: all client connections use a shared native event loop with TUN and credential-refresh threads.

| Component | Identity | Access |
| --- | --- | --- |
| `xpn-network.service` | root, short-lived setup/teardown script | Configure persistent TUN, forwarding and XPN's nftables table; exits after setup |
| `xpn-control.service` | `xpn` | Node admin/enrollment, private database, protected credential socket |
| `xpn-native.service` | `xpn` | Attach to owned TUN, read credential snapshots via socket, accept loopback WebSockets |

The native process has **no root privileges before authentication, during authentication, or after authentication**. Waiting until a peer authenticates would leave unauthenticated parsing exposed in a privileged process. POSIX threads share process credentials through libc's credential-changing wrappers, so per-connection `setuid` calls are not a suitable separation boundary in this event-loop architecture. [Linux NPTL credential behavior](https://man7.org/linux/man-pages/man7/nptl.7.html).

## Startup enforcement

The Linux `xpnd server` entry point now performs a mandatory check before curl/OpenSSL initialization, opening TUN, reading credentials, listening or creating workers:

- Reject root real/effective/saved UIDs, mismatched UIDs, root/mismatched GIDs and root supplementary group membership.
- Reject retained effective, permitted or inheritable Linux capabilities; clear ambient capabilities explicitly.
- Set and verify irreversible `no_new_privs`, so later threads/children inherit the restriction and cannot gain privileges from setuid executables/file capabilities.
- Disable process dumpability before loading device secrets.
- Exit on any failure. There is no `--allow-root` override.

The supervisor launches the server with its final identity. A manual `sudo xpnd server ...` invocation is rejected, even if the operator forgets the service restrictions. Start through `sudo systemctl start xpn-native` instead. The persistent TUN belongs to `xpn`, so the daemon does not need `CAP_NET_ADMIN` to attach. Network configuration remains in the short-lived root helper.

The service also supplies an empty capability bounding/ambient set, `NoNewPrivileges=yes`, read-only system paths, protected home directories, restricted device access, hidden other-user processes, restricted namespaces and disabled core files. The bounds are process-wide inherited restrictions, not a claim of separate client sandboxes. See [systemd execution controls](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html) and [Linux no_new_privs](https://www.kernel.org/doc/html/latest/userspace-api/no_new_privs.html).

These checks apply to the production Linux **server executable**. The Linux client launcher still needs root to configure its local TUN/routes/firewall, and its native client privilege model is unchanged by this server change. Applications embedding the raw C library must provide their own equivalent startup confinement; a library cannot safely change the credentials of an arbitrary threaded host process.

## One shared service account

Node and the C packet daemon both run as `xpn:xpn`. `/run/xpn` is owned by that account (mode `0710`), and the credential socket is `0660`. `/var/lib/xpn` is `0700`, database files are `0600`, and `/etc/xpn.env` is root-owned `0600`.

These permissions keep other host users out. They **do not isolate Node from C**, because the two services share a UID. The native systemd unit still masks the database and environment-file paths, but that is additional confinement, not a separate identity boundary. The native credential cache already holds active device keys. A compromise can affect all active sessions; there is no per-client memory/key isolation. Both services remain unprivileged throughout authentication and packet processing.

## Install or migrate

`deploy/create-users.sh` and the Debian server installer create only the `xpn` account. Alta builds and tests directly in `/root/repo/xpn`; see [the host change record](ALTA-HOST-CHANGES.md) for the completed migration and [the deployment guide](ALTA-DEPLOYMENT.md) for future service setup. No persistent VPN services are deployed there yet.

For an existing two-account deployment, stop `xpn-native` before changing ownership. Stop/restart `xpn-network` to recreate its persistent TUN under `xpn`, install the updated native unit/executable, run `systemctl daemon-reload`, and restart the services. The database stays owned by `xpn`. Inspect drop-ins for old `User`, `Group` or `SupplementaryGroups` overrides. Remove `xpn-packet` only after checking for remaining processes and owned files; installers do not delete an existing account automatically. Do not recursively remove either account's configured home directory.

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

Expect nonzero, identical real/effective/saved UID values for `xpn`, `NoNewPrivs: 1` and zero capability masks. The network unit should be `active (exited)` with no persistent root process. The control process should also run as `xpn`.

`test_privilege` runs during Linux CTest. Its explicit root-only mode tests root rejection, saved-root UID rejection, root groups, retained capabilities, clean identity acceptance and restrictions inherited by threads/forked children, all in disposable child processes without creating users or changing networking:

```sh
sudo env ASAN_OPTIONS=detect_leaks=0 build/native/test_privilege --root
```

These cases and an actual `xpnd server` root-launch rejection passed on alta (Ubuntu Resolute). Connected server threads also passed UID/capability/no-new-privileges checks during real TUN traffic. The CI workflow includes these tests, but has not been dispatched in this session.

To repeat the TUN test without modifying host routes or firewall rules:

```sh
sudo sh deploy/create-users.sh
sudo env PATH="$PATH" python3 native/tests/tun-integration.py "$(pwd)/build/native/xpnd"
```

Use a PATH containing Node 24, nginx, curl, OpenSSL, iproute2, nftables and util-linux. This Linux-only test requires root to create disposable network namespaces. Inside them, it runs both the actual server and Node as `xpn`, and verifies split/full routing through pinned custom-SNI WSS, TUN and NAT against a private HTTP fixture. It checks every connected server thread has a non-root UID, zero capability masks and `NoNewPrivs: 1`. Processes, temporary profiles and namespaces are cleaned up after the run. It does not install or validate the production systemd deployment.

When the checkout is under a private home such as `/root`, use the test wrapper instead of opening home-directory permissions or copying the code:

```sh
cd ~/repo/xpn
export PATH="$PWD/build/tools/node-v24.22.1-linux-x64/bin:$PATH"
sudo env PATH="$PATH" sh native/tools/test-as-xpn.sh build/native/test_privilege
sudo env PATH="$PATH" sh native/tools/test-as-xpn.sh node server/native-integration.mjs build/native/test_transport
sudo env PATH="$PATH" sh native/tools/test-as-xpn.sh --root python3 native/tests/tun-integration.py build/native/xpnd
```

The wrapper creates a read-only bind view of the same checkout in a private mount namespace. It runs ordinary tests as `xpn`; `--root` is reserved for the TUN harness's namespace setup, after which that harness launches Node and the server as `xpn`. The view is temporary and does not copy source or change host permissions. Use checkout-relative command arguments.
