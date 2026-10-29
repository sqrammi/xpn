#!/usr/bin/env python3
"""Install a boot-started XPN client using an already enrolled JSON profile."""
import argparse
import base64
from datetime import datetime, timezone
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import uuid

MARKER = '# Managed by XPN client-service.py\n'
PROFILE_DIR = Path('/etc/xpn/clients')
UNIT_DIR = Path('/etc/systemd/system')
BACKUP_DIR = Path('/var/backups/xpn-client')
LOCK = Path('/run/lock/xpn-client-setup.lock')
ROOT_UID = 0


def profile_bytes(path):
    with path.open('rb') as stream:
        data = stream.read(8193)
    if len(data) > 8192:
        raise ValueError('Profile is too large')
    p = json.loads(data)
    if not isinstance(p, dict) or p.get('version') not in (1, 2):
        raise ValueError('Expected an enrolled XPN JSON profile, not an invitation')
    uuid.UUID(p['id'])
    key = p['key']
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', key) or len(base64.urlsafe_b64decode(key + '=')) != 32:
        raise ValueError('Invalid device key in profile')
    endpoint = urlsplit(p['endpoint'])
    if endpoint.scheme != 'wss' or not endpoint.hostname or endpoint.username or endpoint.password:
        raise ValueError('Profile endpoint must be a wss:// URL without credentials')
    ipaddress.IPv4Address(p['address'])
    if type(p['fullTunnel']) is not bool or p.get('mode') not in ('psk', 'hybrid'):
        raise ValueError('Invalid tunnel policy')
    if not isinstance(p['routes'], list) or (not p['fullTunnel'] and not p['routes']):
        raise ValueError('Invalid routes')
    for route in p['routes']:
        ipaddress.IPv4Network(route, strict=False)
    if not isinstance(p['dns'], list) or not p['dns']:
        raise ValueError('Missing DNS servers')
    for address in p['dns']:
        ipaddress.IPv4Address(address)
    if p['version'] == 2 and (not isinstance(p.get('certificatePins'), list) or not p['certificatePins'] or
                             any(not isinstance(pin, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', pin) for pin in p['certificatePins'])):
        raise ValueError('Invalid certificate pins')
    return data, p


def ctl(*args, check=True):
    return subprocess.run(['systemctl', *args], check=check, text=True, capture_output=True)


def executable(value):
    path = Path(value).resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('Not an executable: ' + str(path))
    # These commands will run as root. Refuse a writable executable or parent.
    for part in [path, *path.parents]:
        info = part.stat()
        if info.st_uid != ROOT_UID or info.st_mode & 0o022:
            raise ValueError('Executable and parent directories must be root-owned and not group/world writable: ' + str(part))
    return path


def quote_unit(value):
    # systemd specifiers and environment expansion are distinct from shell syntax.
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def options(args):
    result = ['--native', str(args.native), '--retry-initial', str(args.retry_initial),
              '--retry-max', str(args.retry_max), '--stable-seconds', str(args.stable_seconds)]
    if args.inner_encryption is not None:
        result += ['--inner-encryption', args.inner_encryption]
    if args.require_pq:
        result.append('--require-pq')
    if args.single_stream:
        result.append('--single-stream')
    return result


def unit_text(args, profile):
    command = [str(args.xpn), 'connect', str(profile), *options(args)]
    return MARKER + '''[Unit]
Description=XPN VPN client (%s)
Wants=network-online.target
After=network-online.target nss-lookup.target
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart=%s
Restart=on-failure
RestartSec=30s
RestartPreventExitStatus=1 78
KillMode=mixed
TimeoutStopSec=30s
UMask=0077
NoNewPrivileges=yes
ProtectHome=yes
ProtectSystem=strict
PrivateTmp=yes
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
''' % (args.name, ' '.join(quote_unit(part) for part in command))


def atomic_write(path, data, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.xpn-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def install(args):
    data, profile = profile_bytes(args.profile)
    args.xpn, args.native = executable(args.xpn), executable(args.native)
    help_result = subprocess.run([str(args.xpn), '--help'], capture_output=True, text=True, check=True, timeout=10)
    if '--no-retry' not in help_result.stdout or '--retry-initial' not in help_result.stdout:
        raise ValueError('Upgrade the XPN client first: this service requires built-in retry support')
    unit = 'xpn-client-' + args.name + '.service'
    unit_path = UNIT_DIR / unit
    target = PROFILE_DIR / (args.name + '.json')
    desired = [(target, data, 0o600), (unit_path, unit_text(args, target).encode(), 0o644)]
    if unit_path.exists() and not unit_path.read_text().startswith(MARKER):
        raise ValueError('Refusing to replace an unmanaged unit: ' + str(unit_path))
    if any((UNIT_DIR / (unit + '.d')).glob('*.conf')):
        raise ValueError('Review/remove custom service drop-ins before running setup')
    changed = []
    for path, contents, mode in desired:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError('Refusing non-regular destination: ' + str(path))
        old = path.read_bytes() if path.exists() else None
        info = path.stat() if path.exists() else None
        if info and info.st_uid != ROOT_UID:
            raise ValueError('Refusing destination not owned by root: ' + str(path))
        if old != contents or (info and stat.S_IMODE(info.st_mode) != mode):
            changed.append((path, contents, mode, old, stat.S_IMODE(info.st_mode) if info else None))
    if PROFILE_DIR.is_symlink():
        raise ValueError('Refusing symlinked profile directory')
    PROFILE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    if PROFILE_DIR.stat().st_uid != ROOT_UID or stat.S_IMODE(PROFILE_DIR.stat().st_mode) != 0o700:
        raise ValueError('Profile directory must be owned by root with mode 0700')
    active = ctl('is-active', '--quiet', unit, check=False).returncode == 0
    enabled = ctl('is-enabled', '--quiet', unit, check=False).returncode == 0
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = BACKUP_DIR / stamp
    backup.mkdir(parents=True, mode=0o700)
    report = []
    applied = []
    try:
        if changed and active:
            ctl('stop', unit)
            report.append(f'{unit}: Stopped for configuration update')
        for path, contents, mode, old, old_mode in changed:
            if old is not None:
                atomic_write(backup / str(path).lstrip('/'), old, 0o600)
            # Include this entry before writing so failure recovery also covers it.
            applied.append((path, old, old_mode))
            atomic_write(path, contents, mode)
            report.append(f'{path}: {"Added" if old is None else "Updated"}; mode {mode:04o}')
        if changed:
            ctl('daemon-reload')
        if not enabled:
            ctl('enable', unit)
            report.append(f'{unit}: Enabled at boot')
        if not args.no_start and (changed or not active):
            ctl('start', unit)
            report.append(f'{unit}: Started client (connection status is in the journal)')
        elif args.no_start and changed and active:
            report.append(f'{unit}: Left stopped because --no-start was specified')
        if not report:
            report.append('No changes; running service was not restarted')
    except BaseException:
        ctl('stop', unit, check=False)
        for path, old, mode in reversed(applied):
            if old is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, old, mode)
        ctl('daemon-reload', check=False)
        ctl('enable' if enabled else 'disable', unit, check=False)
        if active:
            ctl('start', unit, check=False)
        report.append('Setup failed; restored prior files and requested prior service state')
        raise
    finally:
        atomic_write(backup / 'changes.md', ('# XPN client setup\n\n' + '\n'.join('- ' + item for item in report) + '\n').encode(), 0o600)
        print('Change report:', backup / 'changes.md', flush=True)
    print('\n'.join(report))
    print('Status: systemctl status ' + unit)
    print('Logs: journalctl -u ' + unit + ' -f')
    if profile['fullTunnel']:
        print('Full tunnel: ordinary networking is restored between retries and on stop; this is not a persistent kill switch.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', type=Path, help='Already enrolled JSON profile (not an invitation URL)')
    parser.add_argument('--name', default='default', help='Service name suffix, e.g. alta')
    parser.add_argument('--no-start', action='store_true', help='Enable at boot without starting now')
    parser.add_argument('--inner-encryption', choices=['on', 'off'])
    parser.add_argument('--require-pq', action='store_true')
    parser.add_argument('--single-stream', action='store_true')
    parser.add_argument('--xpn', default='/usr/bin/xpn', help='Installed XPN launcher')
    parser.add_argument('--native', default='/usr/lib/xpn/client/xpnd')
    parser.add_argument('--retry-initial', type=float, default=10, help='Initial retry window in seconds (default 10)')
    parser.add_argument('--retry-max', type=float, default=300, help='Maximum retry window in seconds (default 300)')
    parser.add_argument('--stable-seconds', type=float, default=120, help='Connected time before resetting backoff (default 120)')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,31}', args.name):
        parser.error('Name must be 1-32 lowercase letters, digits, underscores or hyphens')
    if not (1 <= args.retry_initial <= args.retry_max <= 3600 and 1 <= args.stable_seconds <= 86400):
        parser.error('Require 1 <= retry-initial <= retry-max <= 3600 and stable-seconds in 1..86400')
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error('Run as root on Linux with systemd')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        install(args)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        # Never print a malformed profile or command input, which can contain keys.
        print('XPN client service setup error:', type(exc).__name__, file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError):
            print((exc.stderr or '').strip(), file=sys.stderr)
        elif isinstance(exc, (ValueError, OSError)) and not isinstance(exc, json.JSONDecodeError):
            print(str(exc), file=sys.stderr)
        sys.exit(78)
