#!/usr/bin/env python3
"""Narrow privileged broker: atomically manage only XPN's two gateway chains."""
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import struct
import subprocess
import tempfile

STATE = Path('/var/lib/xpn-gateway/policy.json')
SOCKET = '/run/xpn-gateway/control.sock'
DEFAULT = dict(enabled=False, interface='wg0', sources=[], targets=[], tcpPorts=[22], udpPorts=[], allowPing=True)


class PolicyError(Exception):
    pass


def policy(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT):
        raise PolicyError('Invalid gateway policy fields')
    if type(value['enabled']) is not bool or type(value['allowPing']) is not bool:
        raise PolicyError('Invalid gateway switches')
    iface = value['interface']
    if not isinstance(iface, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', iface) or iface in ('lo', 'xpn0'):
        raise PolicyError('Invalid WireGuard interface')
    result = {**value}
    for name, limit in (('sources', 16), ('targets', 253), ('tcpPorts', 64), ('udpPorts', 64)):
        items = value[name]
        if not isinstance(items, list) or len(items) > limit:
            raise PolicyError('Invalid gateway ' + name)
        clean = []
        for item in items:
            try:
                if name == 'sources':
                    if not isinstance(item, str): raise ValueError()
                    net = ipaddress.IPv4Network(item, strict=False)
                    denied = ('0.0.0.0/8', '127.0.0.0/8', '169.254.0.0/16', '224.0.0.0/3', '10.77.0.0/24')
                    if net.prefixlen < 8 or any(net.overlaps(ipaddress.IPv4Network(n)) for n in denied): raise ValueError()
                    clean.append(str(net))
                elif name == 'targets':
                    if not isinstance(item, str): raise ValueError()
                    ip = ipaddress.IPv4Address(item)
                    if not int(ipaddress.IPv4Address('10.77.0.2')) <= int(ip) <= int(ipaddress.IPv4Address('10.77.0.254')): raise ValueError()
                    clean.append(str(ip))
                else:
                    if type(item) is not int or not 1 <= item <= 65535: raise ValueError()
                    clean.append(item)
            except (ValueError, TypeError):
                raise PolicyError('Invalid gateway ' + name) from None
        result[name] = sorted(set(clean))
    if value['enabled'] and (not result['sources'] or not result['targets'] or not (result['tcpPorts'] or result['udpPorts'] or result['allowPing'])):
        raise PolicyError('Select home subnets, XPN addresses and at least one allowed service')
    return result


def rules(value):
    p = policy(value)
    lines = ['flush chain inet xpn gateway_forward', 'flush chain inet xpn gateway_nat']
    if not p['enabled']: return '\n'.join(lines) + '\n'
    def group(items): return '{ ' + ', '.join(map(str, items)) + ' }'
    inbound = f'iifname "{p["interface"]}" oifname "xpn0" ip saddr {group(p["sources"])} ip daddr {group(p["targets"])}'
    reply = f'iifname "xpn0" oifname "{p["interface"]}" ip saddr {group(p["targets"])} ip daddr {group(p["sources"])}'
    for proto, ports in [('tcp', p['tcpPorts']), ('udp', p['udpPorts'])]:
        if ports:
            lines.append(f'add rule inet xpn gateway_forward {inbound} {proto} dport {group(ports)} ct state new,established accept')
            lines.append(f'add rule inet xpn gateway_forward {reply} {proto} sport {group(ports)} ct state established accept')
    if p['allowPing']:
        lines.append(f'add rule inet xpn gateway_forward {inbound} icmp type echo-request ct state new,established accept')
        lines.append(f'add rule inet xpn gateway_forward {reply} icmp type echo-reply ct state established accept')
    lines.append(f'add rule inet xpn gateway_forward {reply} ip protocol icmp ct state related accept')
    # Do not let broader WAN rules bypass the selected gateway restrictions.
    lines.append(f'add rule inet xpn gateway_forward iifname \"{p["interface"]}\" oifname \"xpn0\" drop')
    lines.append(f'add rule inet xpn gateway_forward iifname \"xpn0\" oifname \"{p["interface"]}\" drop')
    lines.append(f'add rule inet xpn gateway_nat {inbound} snat ip to 10.77.0.1')
    return '\n'.join(lines) + '\n'


def apply(value):
    # One nft transaction: never flush the whole ruleset or recreate xpn0.
    subprocess.run(['/usr/sbin/nft', '-f', '-'], input=rules(value), text=True, capture_output=True, check=True, timeout=5)


def wireguard_interface(name):
    info = json.loads(subprocess.run(['/usr/sbin/ip', '-j', '-d', 'link', 'show', 'dev', name],
                                    text=True, capture_output=True, check=True, timeout=3).stdout)
    if not info or info[0].get('linkinfo', {}).get('info_kind') != 'wireguard':
        raise PolicyError('The selected interface must be an existing WireGuard interface')
    defaults = json.loads(subprocess.run(['/usr/sbin/ip', '-j', '-4', 'route', 'show', 'default'],
                                        text=True, capture_output=True, check=True, timeout=3).stdout)
    if any(route.get('dev') == name for route in defaults):
        raise PolicyError('Use a dedicated home WireGuard interface, not the server default route')


class Gateway:
    def __init__(self, path=STATE, apply_rules=apply, check_interface=wireguard_interface):
        self.path, self.apply, self.check_interface = path, apply_rules, check_interface
        saved = json.loads(path.read_text()) if path.exists() else {'revision': 0, 'policy': DEFAULT}
        self.value = {'revision': saved['revision'], 'policy': policy(saved['policy'])}
        if type(self.value['revision']) is not int or self.value['revision'] < 0: raise PolicyError('Invalid saved revision')
        # Interface names can be restored before wg-quick has brought the link up.
        self.apply(self.value['policy'])

    def request(self, data):
        if data == {'action': 'get'}: return {**self.value, 'applied': True}
        if not isinstance(data, dict) or set(data) != {'action', 'revision', 'policy'} or data['action'] != 'set':
            raise PolicyError('Invalid gateway request')
        if type(data['revision']) is not int or data['revision'] != self.value['revision']:
            return {'error': 'Gateway settings changed; refresh before saving', 'status': 409}
        updated = policy(data['policy'])
        if updated['enabled']:
            self.check_interface(updated['interface'])
        if updated == self.value['policy']: return {**self.value, 'applied': True}
        new = {'revision': self.value['revision'] + 1, 'policy': updated}
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.policy-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                os.fchmod(stream.fileno(), 0o600)
                json.dump(new, stream); stream.flush(); os.fsync(stream.fileno())
            self.apply(updated)
            try:
                os.replace(name, self.path)
            except OSError:
                self.apply(self.value['policy'])
                raise
            self.value = new
            print(json.dumps({'event': 'gateway.policy', 'revision': new['revision'], 'enabled': updated['enabled']}), flush=True)
            return {**new, 'applied': True}
        finally:
            if os.path.exists(name): os.unlink(name)


def handle(connection, gateway, allowed_uid):
    _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
    if uid not in (0, allowed_uid): return
    connection.settimeout(3)
    try:
        data = b''
        while b'\n' not in data:
            chunk = connection.recv(4096)
            if not chunk: return
            data += chunk
            if len(data) > 8192: raise PolicyError('Gateway request too large')
        if data.split(b'\n', 1)[1]: raise PolicyError('One gateway request per connection')
        result = gateway.request(json.loads(data))
    except (PolicyError, ValueError, TypeError, KeyError) as error:
        result = {'error': str(error) if isinstance(error, PolicyError) else 'Invalid gateway request', 'status': 400}
    except (OSError, subprocess.SubprocessError):
        result = {'error': 'Gateway rules could not be applied; check the gateway service journal', 'status': 503}
        print('Gateway apply or persistence failed', flush=True)
    connection.sendall(json.dumps(result).encode() + b'\n')


def main():
    if os.geteuid() != 0: raise SystemExit('Run this helper through xpn-gateway.service')
    os.umask(0o077)
    gateway = Gateway()
    allowed_uid = pwd.getpwnam('xpn').pw_uid
    path = Path(SOCKET)
    if path.exists():
        if not stat.S_ISSOCK(path.lstat().st_mode): raise SystemExit('Gateway socket path is not a socket')
        path.unlink()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(SOCKET); os.chmod(SOCKET, 0o660); listener.listen(8)
        while True:
            connection, _ = listener.accept()
            with connection:
                try: handle(connection, gateway, allowed_uid)
                except (OSError, subprocess.SubprocessError): pass


if __name__ == '__main__': main()
