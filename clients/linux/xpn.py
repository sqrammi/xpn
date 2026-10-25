#!/usr/bin/env python3
"""Linux camera enrollment and transactional routing around the native C client."""
import argparse
import ipaddress
import json
import os
import pathlib
import select
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

def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['enroll', 'connect'])
    p.add_argument('profile', type=pathlib.Path)
    p.add_argument('--invitation', help='Prefer --scan to avoid putting secrets in shell history')
    p.add_argument('--scan', action='store_true')
    p.add_argument('--native', default='/usr/local/bin/xpnd')
    args = p.parse_args()
    if args.action == 'enroll':
        invitation = camera() if args.scan else args.invitation or input('Invitation: ').strip()
        run(args.native, 'enroll', '-', str(args.profile), input=invitation + '\n')
        print('Saved device profile with mode 0600.')
        return
    if os.geteuid() != 0:
        raise RuntimeError('Connecting requires root for TUN, routing, and IPv6 leak prevention')
    profile = json.loads(args.profile.read_text())
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
    def stop(*_): raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
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
        proc = subprocess.Popen([args.native, 'client', str(args.profile), interface], stdout=subprocess.PIPE, text=True)
        if not select.select([proc.stdout], [], [], 25)[0] or proc.stdout.readline().strip() != 'CONNECTED':
            raise RuntimeError('Native TLS tunnel did not authenticate')
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
        print('Connected. Ctrl-C disconnects and restores this session’s network changes.')
        code = proc.wait()
        if code: raise RuntimeError(f'Native tunnel exited with status {code}')
    finally:
        if proc and proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        for command in reversed(cleanup):
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

if __name__ == '__main__':
    try: main()
    except KeyboardInterrupt: pass
    except (RuntimeError, subprocess.CalledProcessError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
