# Linux client at boot

`xpn connect` itself retries connection failures with randomized exponential
backoff, whether run interactively or at boot. The setup helper only installs a
systemd service that runs that command directly; it does not supervise attempts
or implement another retry loop. Certificate pins and encryption policy remain
the same on every attempt.

This requires `xpn-client` 0.1.1 or newer, or the updated Linux launcher in this
checkout. The initial 0.1.0 PPA packages do not include these changes. No native C rebuild is
required to use the updated launcher with the existing PPA native executable.

For an interactive connection with the updated launcher:

```sh
sudo python3 clients/linux/xpn.py connect ./xpn-profile.json --native /usr/lib/xpn/client/xpnd
```

Ctrl-C or SIGTERM stops retries and cleans up the connection. Add `--no-retry`
for a single attempt that exits after failure or disconnect.

## Set up

Use an already enrolled JSON profile. Downloading the profile in the browser
redeems its invitation; use that JSON directly. Stop any foreground connection
using that identity before starting the service.

With `xpn-client` 0.1.1 or newer, setup is one command:

```sh
sudo xpn-client-setup ./xpn-profile.json --name alta
```

If still using the initial 0.1.0 package, install the updated launcher separately from the
package-owned `/usr/bin/xpn`, then run setup from the checkout:

```sh
sudo install -o root -g root -m 755 clients/linux/xpn.py /usr/local/bin/xpn
sudo python3 clients/linux/client-service.py ./xpn-profile.json --name alta --xpn /usr/local/bin/xpn
```

For a remote machine without a checkout, copy both `clients/linux/xpn.py` and
`clients/linux/client-service.py` to it and run:

```sh
sudo install -o root -g root -m 755 ./xpn.py /usr/local/bin/xpn
sudo python3 ./client-service.py ./xpn-profile.json --name alta --xpn /usr/local/bin/xpn
```

The helper writes a private copy of the profile to `/etc/xpn/clients/alta.json`.
The original helper and profile need not remain in the working directory.
It refuses setup with an older launcher that lacks built-in retry support.
The source launcher uses `/usr/local/bin/xpnd` by default; when running it
interactively with the existing PPA, pass `--native /usr/lib/xpn/client/xpnd`.
The generated service already specifies that native path.

The 0.1.1 package includes the entry point:

```sh
sudo xpn-client-setup ./xpn-profile.json --name alta
```

The already published `0.1.0-0ubuntu1~noble1` / `~resolute1` packages do not
contain the helper or built-in launcher retries. Use the two-file procedure
above if an updated package is not yet available in your APT indexes. After upgrading to a package that
includes retries, remove only the manually installed `/usr/local/bin/xpn` and
rerun `xpn-client-setup` to select the package-owned `/usr/bin/xpn`.

Add `--no-start` to enable at boot without connecting immediately. Full tunnel
can interrupt SSH, so start remote testing with a split-tunnel profile. Optional
`--inner-encryption on|off`, `--require-pq` and `--single-stream` are stored in the
unit; omitted encryption options retain the profile/client defaults.
Repeat any explicit policy/retry flags when rerunning setup; each run generates
the unit from that command's options, rather than merging previous flags.

## Manage

```sh
systemctl status xpn-client-alta
journalctl -u xpn-client-alta -f
sudo systemctl restart xpn-client-alta
sudo systemctl stop xpn-client-alta
sudo systemctl disable --now xpn-client-alta
```

`active (running)` means the client is running, not necessarily that the VPN
has authenticated. The journal reports each attempt, `Connected`, and the delay
before the next attempt. Stopping the service cancels both connections and retries.
There is no artificial retry-count limit. Malformed local configuration, a
missing executable or failed network cleanup requires repair and a restart.
Systemd can restart a crashed client; ordinary connection failures are handled
inside the client without exiting or restarting the service.

## Retry behavior

The first attempt is delayed randomly by 0-5 seconds to spread simultaneous boot
connections. After failures, wait a random time from half to all of an
exponentially growing ceiling: **5-10, 10-20, 20-40, 40-80, 80-160, then 150-300
seconds**. The ceiling remains five minutes on prolonged failures. Delays are
independently sampled using the OS random source. Retry time is in addition to
connection-attempt time; the existing native active/standby transport can make
bounded lane-repair attempts within each session.

Only an authenticated connection lasting at least two minutes resets the retry
window. Brief successful handshakes followed by a disconnect do not reset it.
Defaults can be changed with `--retry-initial`, `--retry-max`, and
`--stable-seconds`. No retry bypasses certificate checks, revocation or required
encryption. A revoked credential keeps failing until its configuration is fixed.

The existing launcher cleans up its routes, DNS and firewall after each attempt.
**Ordinary networking resumes between attempts, before the first connection and
when the service is stopped. This is not a persistent kill switch.** The full
mode firewall applies while the individual client is connected. Force-killing a
launcher can leave its process-specific routes/firewall behind; graceful service
stop is preferred. The helper does not change the launcher's current LAN-routing
behavior or add roaming support.

## Files and repeat runs

- `/etc/xpn/clients/`: root-owned, mode 0700; each profile mode 0600.
- `/etc/systemd/system/xpn-client-alta.service`: generated unit, mode 0644.
- `/usr/local/bin/xpn`: updated launcher when using the manual installation
  above; a future package supplies it as `/usr/bin/xpn`.
- `/var/backups/xpn-client/<timestamp>/changes.md`: concise action report and
  root-only copies of replaced files. Backups can contain device credentials.

The unit runs as root because the current Linux launcher configures TUN, routes,
nftables and DNS, but capabilities are limited to NET_ADMIN/NET_RAW, privilege
escalation is disabled, the filesystem is read-only and home directories are
hidden. This does not alter the server's unprivileged service account.

Unchanged reruns leave active connections alone. Changed files cause the selected
instance to stop, update and start. `--no-start` leaves an updated instance
stopped. Unmanaged units and custom unit drop-ins are refused. Setup serializes
concurrent invocations and restores previous file/service state on an error.
If an earlier helper installed `/usr/local/lib/xpn/client-service.py`, regenerated
units no longer use it. Remove that old helper only after checking all XPN units
have been migrated to direct `xpn connect` execution.

Different names allow separate server connections using separate device profiles.
Use non-overlapping split routes; overlapping routes/multiple full-tunnel instances
are not coordinated by this helper.
