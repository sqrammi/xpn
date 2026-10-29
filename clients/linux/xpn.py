#!/usr/bin/env python3
"""Linux camera enrollment and transactional routing around the native C client."""
import argparse
import ipaddress
import json
import os
import pathlib
import selectors
import random
import time
import signal
import socket
import subprocess
import sys
import urllib.parse

def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)

def camera():
    # zbarcam reads a real camera and emits a decoded QR payload; no browser needed.
    proc = subprocess.Popen(['zbarcam', '--raw', '--nodisplay'], stdout=subprocess.PIPE, text=True)
    try:
        for line in proc.stdout:
            if line.startswith('https://') and '#token=' in line:
                return line.strip()
        raise RuntimeError('No invitation scanned')
    finally:
        proc.terminate()
        proc.wait(timeout=5)

RNG = random.SystemRandom()
pause = time.sleep


class CleanupError(Exception):
    """Do not retry on top of network state that could not be removed."""


class Backoff:
    def __init__(self, initial=10, maximum=300, stable=120):
        self.initial, self.maximum, self.stable = initial, maximum, stable
        self.ceiling = initial

    def next(self, connected_for=0):
        if connected_for >= self.stable:
            self.ceiling = self.initial
        delay = RNG.uniform(self.ceiling / 2, self.ceiling)
        self.ceiling = min(self.maximum, self.ceiling * 2)
        return delay


def monitor_native(proc, authenticated, timeout=25):
    """Read native status without blocking on partial lines or a stuck event loop."""
    connected = False
    deadline = time.monotonic() + timeout
    pending = b''
    with selectors.DefaultSelector() as selector:
        selector.register(proc.stdout, selectors.EVENT_READ)
        while True:
            if not connected and time.monotonic() >= deadline:
                raise RuntimeError('Native TLS tunnel did not authenticate within 25 seconds')
            if not selector.select(timeout=min(1, max(0, deadline - time.monotonic())) if not connected else 1):
                continue
            data = os.read(proc.stdout.fileno(), 4096)
            if not data:
                raise RuntimeError('Native tunnel closed')
            pending += data
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                text = line.decode('utf-8', errors='replace').rstrip('\r')
                if text == 'CONNECTED' and not connected:
                    authenticated()
                    connected = True
                else:
                    print(text, flush=True)
                # Older native builds can announce closure but remain in their
                # event loop. Let connect_once's finally stop them and clean up.
                if text in ('Both VPN connections unavailable; reconnect', 'Tunnel closed; reconnect to rekey'):
                    raise RuntimeError('Native tunnel requests reconnection')
            if len(pending) > 65536:
                raise RuntimeError('Native status line exceeded limit')


def connect(args):
    # Invalid local configuration is not a transient network failure.
    profile = json.loads(args.profile.read_text())
    if not isinstance(profile, dict) or type(profile.get('fullTunnel')) is not bool:
        raise ValueError('Invalid enrolled profile')
    endpoint = urllib.parse.urlsplit(profile['endpoint'])
    if endpoint.scheme != 'wss' or not endpoint.hostname or endpoint.username or endpoint.password:
        raise ValueError('Profile requires a wss:// endpoint without credentials')
    endpoint.port  # Validate before entering the retry loop.
    ipaddress.IPv4Address(profile['address'])
    if not isinstance(profile['routes'], list) or not isinstance(profile['dns'], list):
        raise ValueError('Invalid profile routes/DNS')
    for route in profile['routes']: ipaddress.IPv4Network(route, strict=False)
    for address in profile['dns']: ipaddress.IPv4Address(address)
    if not os.access(args.native, os.X_OK):
        raise ValueError('Native executable is missing or not executable: ' + str(args.native))
    backoff = Backoff(args.retry_initial, args.retry_max, args.stable_seconds)
    def stop(*_): raise KeyboardInterrupt()
    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        if not args.no_retry:
            startup = RNG.uniform(0, min(5, args.retry_initial))
            print(f'Initial connection in {startup:.1f}s', flush=True)
            pause(startup)
        attempt = 0
        while True:
            attempt += 1
            print(f'Connection attempt {attempt}', flush=True)
            state = {'connected_at': None, 'ended_at': None}
            try:
                # DNS is resolved anew each time, after previous state is removed.
                connect_once(args, profile, state)
            except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
                if args.no_retry: raise
                print(str(error), file=sys.stderr, flush=True)
            if args.no_retry: return
            connected_for = (state['ended_at'] - state['connected_at']) if state['connected_at'] is not None else 0
            delay = backoff.next(connected_for)
            print(f'Disconnected; retrying in {delay:.1f}s', flush=True)
            pause(delay)
    finally:
        for sig, handler in previous.items(): signal.signal(sig, handler)


def connect_once(args, profile, state):
    full = profile['fullTunnel']
    # IPv4-only tunnel: full mode explicitly blocks IPv6 instead of leaking it.
    endpoint = urllib.parse.urlsplit(profile['endpoint'])
    ips = sorted({x[4][0] for x in socket.getaddrinfo(endpoint.hostname, endpoint.port or 443, socket.AF_INET, socket.SOCK_STREAM)})
    if not ips:
        raise RuntimeError('The endpoint needs an IPv4 A record')
    interface = 'xpn' + str(os.getpid() % 100000)
    table = 'xpn_' + str(os.getpid())
    cleanup = []
    proc = None
    def undo(*args): cleanup.append(args)
    try:
        run('ip', 'tuntap', 'add', 'dev', interface, 'mode', 'tun')
        undo('ip', 'link', 'delete', interface)
        run('ip', 'address', 'add', profile['address'] + '/32', 'dev', interface)
        run('ip', 'link', 'set', 'dev', interface, 'mtu', '1400', 'up')
        # Preserve existing host routes. Add only routes owned by this invocation.
        if full or any(any(ipaddress.IPv4Address(ip) in ipaddress.IPv4Network(route, strict=False) for route in profile['routes']) for ip in ips):
            for ip in ips:
                existing = json.loads(run('ip', '-j', 'route', 'show', 'exact', ip + '/32', capture_output=True).stdout)
                if existing:
                    continue
                route = json.loads(run('ip', '-j', 'route', 'get', ip, capture_output=True).stdout)[0]
                command = ['ip', 'route', 'add', ip + '/32']
                if route.get('gateway'): command += ['via', route['gateway']]
                command += ['dev', route['dev']]
                run(*command)
                undo('ip', 'route', 'del', ip + '/32')
        native_command = [args.native, 'client', str(args.profile), interface]
        if args.single_stream:
            native_command.append('--single-stream')
        if args.inner_encryption is not None:
            native_command.append('--inner-encryption' if args.inner_encryption == 'on' else '--outer-only')
        if args.require_pq or (args.inner_encryption is not None and profile.get('mode') == 'hybrid'):
            native_command.append('--require-pq')
        proc = subprocess.Popen(native_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        def authenticated():
            if full:
                # Once authenticated, keep ordinary IPv4 and DNS from bypassing the
                # tunnel even when the native socket fails before cleanup runs.
                endpoints = ', '.join(ips)
                rules = f'''table inet {table} {{ chain output {{
                    type filter hook output priority -10; policy accept;
                    oifname "lo" accept
                    meta nfproto ipv6 reject
                    oifname "{interface}" accept
                    ip daddr {{ {endpoints} }} tcp dport {endpoint.port or 443} accept
                    reject
                }} }}'''
                run('nft', '-f', '-', input=rules)
                undo('nft', 'delete', 'table', 'inet', table)
            routes = ['0.0.0.0/1', '128.0.0.0/1'] if full else profile['routes']
            for subnet in routes:
                subnet = str(ipaddress.IPv4Network(subnet, strict=False))
                run('ip', 'route', 'add', subnet, 'dev', interface)
                undo('ip', 'route', 'del', subnet, 'dev', interface)
            # Ubuntu uses systemd-resolved. Split mode leaves host DNS unchanged.
            if full:
                run('resolvectl', 'dns', interface, *profile['dns'])
                undo('resolvectl', 'revert', interface)
                run('resolvectl', 'domain', interface, '~.')
                run('resolvectl', 'default-route', interface, 'yes')
            print('Connected. Ctrl-C disconnects and restores this session’s network changes.', flush=True)
            state['connected_at'] = time.monotonic()
        monitor_native(proc, authenticated)
    finally:
        state['ended_at'] = time.monotonic()
        # Finish removal even if a stop arrives during cleanup, then honor it.
        stop_requested = False
        def defer_stop(*_):
            nonlocal stop_requested
            stop_requested = True
        previous = {sig: signal.signal(sig, defer_stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            if proc:
                if proc.poll() is None:
                    proc.terminate()
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                proc.stdout.close()
            failures = []
            for command in reversed(cleanup):
                try:
                    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if result.returncode: failures.append(command[0])
                except OSError:
                    failures.append(command[0])
            if failures:
                raise CleanupError('Network cleanup failed; inspect routes/firewall before restarting: ' + ', '.join(failures))
        finally:
            for sig, handler in previous.items(): signal.signal(sig, handler)
            if stop_requested:
                raise KeyboardInterrupt()

def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['enroll', 'connect'])
    p.add_argument('profile', type=pathlib.Path)
    p.add_argument('--invitation', help='Prefer --scan to avoid putting secrets in shell history')
    p.add_argument('--scan', action='store_true')
    p.add_argument('--native', default='/usr/local/bin/xpnd')
    p.add_argument('--inner-encryption', choices=['on', 'off'], help='Extra ChaCha20-Poly1305 packet encryption; outer TLS always remains on')
    p.add_argument('--require-pq', action='store_true', help='Require hybrid ML-KEM key exchange; never fall back')
    p.add_argument('--single-stream', action='store_true', help='Disable the default authenticated standby (for older servers)')
    p.add_argument('--no-retry', action='store_true', help='Attempt one connection, then exit on failure/disconnect')
    p.add_argument('--retry-initial', type=float, default=10)
    p.add_argument('--retry-max', type=float, default=300)
    p.add_argument('--stable-seconds', type=float, default=120)
    args = p.parse_args()
    if not (1 <= args.retry_initial <= args.retry_max <= 3600 and 1 <= args.stable_seconds <= 86400):
        p.error('Require 1 <= retry-initial <= retry-max <= 3600 and stable-seconds in 1..86400')
    if args.action == 'enroll':
        invitation = camera() if args.scan else args.invitation or input('Invitation: ').strip()
        run(args.native, 'enroll', '-', str(args.profile), input=invitation + '\n')
        print('Saved device profile with mode 0600.')
        return
    if os.geteuid() != 0:
        raise RuntimeError('Connecting requires root for TUN, routing, and IPv6 leak prevention')
    connect(args)

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: pass
    except (CleanupError, KeyError, TypeError, RuntimeError, subprocess.CalledProcessError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
