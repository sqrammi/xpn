# Install the server on Alta

Run this from the existing checkout on Alta:

```sh
cd ~/repo/xpn
sudo python3 deploy/install-server.py --url https://alta.jeffhansen.com/xpn
```

No hand-written environment files, systemd units/drop-ins, or nginx includes are needed. The installer uses the source checkout in place and one non-root `xpn` account. It builds the C server, installs locked Node dependencies, reuses the private Node runtime (or downloads a checksum-verified one if needed), and configures startup.

It automatically selects the matching HTTPS nginx site—or the unique HTTPS default site—uses that site's existing certificate, and adds only the XPN path. XPN paths reject plain HTTP even if that block also listens on port 80. On Alta, the preview selected `/etc/nginx/sites-available/default`, `/etc/ssl/cert.pem`, and loopback ports **3300/3301**, leaving the existing `/ips/` upstream on 3001 alone. The HTTPS hostname must already resolve to this host, with nginx and a valid certificate configured.

## Unlock administration

After installation succeeds, show the generated admin token **in your own terminal**:

```sh
sudo python3 deploy/install-server.py --show-admin-token
```

Open **https://alta.jeffhansen.com/xpn/** and paste that token into **Unlock administration**. Create one device for the Mac, then paste its one-use invitation into the signed client or scan the QR.

`ADMIN_TOKEN` and a separate random `MASTER_KEY` are stored in root-only `/etc/xpn.env`. Rerunning the installer preserves that file, including SMTP/custom settings, and never silently replaces the master key. Back up `/etc/xpn.env` together with `/var/lib/xpn`.

## Preview or select a site

A read-only preview is available:

```sh
sudo python3 deploy/install-server.py --url https://alta.jeffhansen.com/xpn --plan
```

If multiple HTTPS blocks are eligible, specify the enabled site file:

```sh
sudo python3 deploy/install-server.py --url https://alta.jeffhansen.com/xpn \
  --nginx-site /etc/nginx/sites-enabled/default
```

If the certificate directive is in another included file, also supply `--certificate /absolute/path/fullchain.pem`. `--control-port` and `--native-port` override automatic backend selection. `--host-tcp-ports 85,443` allows VPN access to Alta’s existing SSH and HTTPS services; the default for a new installation is `22,443`. The selected list is preserved on later runs without that flag. Rate-limited ping is also allowed; other host services, other VPN clients, loopback and metadata remain blocked. Split-tunnel profiles must include the desired server address in their authorized routes. `--skip-build` uses an already-built native executable and installed Node dependencies; the default command builds them when their inputs or recorded outputs have changed. A run with `--skip-build` does not certify that prebuilt artifacts match current source; the next normal run may build them.

## What the command changes

- Installs required Ubuntu build dependencies and builds under `~/repo/xpn/build/native`; Node dependencies stay in the checkout. It does not replace system Node or copy the application into `/opt`.
- Creates/reuses only `xpn`. The running Node and packet services have no root privileges. The network setup runs briefly as root to configure TUN, forwarding and the dedicated `inet xpn` nftables table.
- Writes three complete systemd unit files with a private read-only checkout mapping. `/root` permissions stay private; no drop-ins need to be created by hand.
- Generates `/etc/xpn.env` on first installation and writes `/etc/xpn/install.json` to record the selected paths/ports.
- Writes the two nginx includes and inserts a single include into the selected HTTPS server block, preserving its certificate and other locations. Exact unmodified templates from the earlier manual instructions can be adopted; custom units, existing drop-ins, ambiguous sites and conflicting XPN locations are rejected for explicit reconciliation.
- Validates nginx, starts/checks the services and authenticated local admin API, reloads nginx, checks HTTPS, and enables the XPN services at boot.

Existing firewall FORWARD-drop policies must permit the VPN traffic; the installer does not rewrite unrelated firewall rules or cloud security groups. It rejects an overlapping `10.77.0.0/24` route or unmanaged existing XPN network resources. It pins the existing nginx leaf certificate for newly created devices; renewals require planned pin rotation, as described in [PINNING.md](PINNING.md).

## Logs, failures and updates

Every run prints the path to a root-only `/var/backups/xpn/<UTC timestamp>/changes.md` report. It lists actual changes by path/resource, for example:

```text
/etc/systemd/system/xpn-control.service: Updated non-root service with read-only checkout mounted at /run/xpn-source (mode 0644)
/etc/nginx/sites-available/default: Updated include for /etc/nginx/snippets/xpn-locations.conf in selected HTTPS server (mode 0644)
nginx.service: Reloaded changed proxy configuration
```

The same directory contains `actions.log` with commands/output, a `manifest.json` for changed configuration files, and backups of their original contents. Secrets never appear in the report/log. Configuration backups can contain secrets and are restricted to root. The installer writes complete service files; it does not require a `checkout.conf` drop-in or a separate “vpn-source” service.

Reruns compare file contents/permissions, dependency versions, source/build fingerprints, and service state. They preserve unchanged files (including timestamps), credentials, SMTP settings and device data. Missing managed files are recreated, missing packages/accounts are provisioned, and only affected services are stopped/started or enabled. Changing the control/network service also restarts its dependent packet service. nginx reloads only when its configuration changes. No-op runs perform health checks and write an audit report saying **No installation changes**; they do not build, reinstall packages, rewrite configuration or restart/reload services. Audit directories/logs and `/run/lock/xpn-install.lock` are bookkeeping, and health checks may appear in normal service/access logs. Concurrent installers are rejected.

A read-only `--plan` creates no report or configuration.

On failure, generated configuration changes are rolled back and previously running services are restarted. Newly generated `/etc/xpn.env` is retained so any newly created database does not lose its encryption key. Build packages, the `xpn` account, created directories, generated database/state and build artifacts remain. Rollback restores configuration, not previous application binaries or database contents; inspect the report before restarting an older application. Global IPv4 forwarding may remain enabled after a network-start failure; it is not blindly disabled on a shared host. Review the printed log path and `journalctl -u xpn-control -u xpn-native -u xpn-network` before retrying.

Run the same install command after updating the source. Changes that require stopping a running VPN service interrupt its active sessions; an unchanged rerun does not. The installer preserves secrets and existing device data. It does not support silently moving a live installation to a different checkout, nginx site, endpoint or native port.

Optional SMTP: add `SMTP_URL` and `SMTP_FROM` to `/etc/xpn.env`, then run `sudo systemctl restart xpn-control`. No email is sent by installation.

The [host change record](ALTA-HOST-CHANGES.md) distinguishes actual Alta changes from these instructions. The [manual reference](SERVER-MANUAL-DEPLOYMENT.md) remains available for custom deployments. The installer has now been run successfully on Alta, including a verified no-op rerun. The host record contains the failed/rolled-back first attempt, successful installation, targeted nginx update and unchanged rerun evidence.
