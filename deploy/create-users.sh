#!/bin/sh
# Root-only provisioning; no network changes and no daemon stays running.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run this account setup as root.' >&2; exit 1; }
getent group xpn >/dev/null || groupadd --system xpn
getent passwd xpn >/dev/null || useradd --system --gid xpn --home-dir /var/lib/xpn --shell /usr/sbin/nologin xpn
[ "$(id -u xpn)" != 0 ] && [ "$(id -g xpn)" != 0 ] || {
    echo 'xpn must have a non-root UID and primary GID.' >&2; exit 1;
}
echo 'XPN service account ready. Both control and packet services run as xpn.'
