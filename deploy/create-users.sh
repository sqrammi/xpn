#!/bin/sh
# Root-only provisioning; no network changes and no daemon stays running.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run this account setup as root.' >&2; exit 1; }
getent group xpn >/dev/null || groupadd --system xpn
getent passwd xpn >/dev/null || useradd --system --gid xpn --home-dir /var/lib/xpn --shell /usr/sbin/nologin xpn
getent group xpn-packet >/dev/null || groupadd --system xpn-packet
getent passwd xpn-packet >/dev/null || useradd --system --gid xpn-packet --home-dir /nonexistent --shell /usr/sbin/nologin xpn-packet
[ "$(id -u xpn)" != 0 ] && [ "$(id -u xpn-packet)" != 0 ] && [ "$(id -u xpn)" != "$(id -u xpn-packet)" ] || {
    echo 'xpn and xpn-packet must have distinct non-root UIDs.' >&2; exit 1;
}
echo 'XPN control and packet accounts ready. Supplementary socket access is assigned only by the systemd unit.'
