#!/usr/bin/env python3
"""Root-only Linux test in disposable network namespaces; no host routes/firewall changes.

Requires the xpn account, Node 24, nginx, iproute2, nftables, curl,
util-linux and a built xpnd. Run: sudo env PATH="$PATH" python3
native/tests/tun-integration.py /absolute/path/to/xpnd
"""
import os
import json
import importlib.util
from pathlib import Path
import pwd
import shutil
import signal
import subprocess as sp
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def run(*args, **kwargs):
    kwargs.setdefault('check', True)
    return sp.run([str(a) for a in args], text=True, **kwargs)


def wait_for(predicate, description, process=None):
    for _ in range(150):
        if process is not None and process.poll() is not None:
            raise RuntimeError(f'{description} exited early (status {process.returncode}); see its log')
        if predicate():
            return
        time.sleep(0.1)
    raise RuntimeError(f'Timed out: {description}')


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run as root; all network changes are inside disposable namespaces.')
    binary = Path(sys.argv[1]).resolve(strict=True)
    if '--isolated' not in sys.argv:
        os.execvp('unshare', ['unshare', '--net', '--', sys.executable, __file__, str(binary), '--isolated'])
    assert os.readlink('/proc/self/ns/net') != os.readlink('/proc/1/ns/net'), 'Must not modify host network'
    processes, handles = [], []
    control_user = packet_user = pwd.getpwnam('xpn')
    directory = Path(tempfile.mkdtemp(prefix='xpn-tun-'))
    directory.chmod(0o755)

    def start(args, name):
        log = open(directory / f'{name}.log', 'w+')
        handles.append(log)
        proc = sp.Popen([str(a) for a in args], stdout=log, stderr=sp.STDOUT, start_new_session=True)
        processes.append(proc)
        return proc

    def identity(user, groups):
        return ['setpriv', f'--reuid={user.pw_uid}', f'--regid={user.pw_gid}',
                f'--groups={groups}', '--bounding-set=-all', '--inh-caps=-all',
                '--ambient-caps=-all', '--no-new-privs']

    def ns(proc, *args, **kwargs):
        return run('nsenter', '-t', proc.pid, '-n', '--', *args, **kwargs)

    def namespace(name):
        proc = start(['unshare', '--net', 'sleep', '180'], name)
        wait_for(lambda: os.readlink(f'/proc/{proc.pid}/ns/net') != os.readlink('/proc/self/ns/net'), name)
        ns(proc, 'ip', 'link', 'set', 'lo', 'up')
        return proc

    try:
        fixture = ROOT / 'server/tun-fixture.mjs'
        if not fixture.is_file():
            raise RuntimeError(f'Missing tracked test fixture: {fixture}')
        if run(*identity(control_user, control_user.pw_gid), '/usr/bin/test', '-r', fixture,
               check=False).returncode:
            raise RuntimeError(f'xpn cannot read {fixture}; a parent directory may be private. '
                               'Run through native/tools/test-as-xpn.sh --root.')
        run('ip', 'link', 'set', 'lo', 'up')
        client_ns, wan_ns = namespace('client-ns'), namespace('wan-ns')
        for proc, iface, network in [(client_ns, 'test-client', '198.18.0'), (wan_ns, 'test-wan', '192.0.2')]:
            run('ip', 'link', 'add', iface, 'type', 'veth', 'peer', 'name', 'peer0')
            run('ip', 'link', 'set', 'peer0', 'netns', proc.pid)
            run('ip', 'addr', 'add', f'{network}.1/24', 'dev', iface)
            run('ip', 'link', 'set', iface, 'up')
            ns(proc, 'ip', 'addr', 'add', f'{network}.2/24', 'dev', 'peer0')
            ns(proc, 'ip', 'link', 'set', 'peer0', 'up')
        # No return route to the VPN pool on the WAN: successful HTTP requires NAT.
        run('sh', ROOT / 'deploy/network.sh', env={**os.environ, 'XPN_WAN_IFACE': 'test-wan', 'XPN_HOST_TCP_PORTS': '8444'})
        run('openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256',
            '-nodes', '-days', '1', '-subj', '/CN=unrelated.example.invalid',
            '-keyout', directory / 'key.pem', '-out', directory / 'cert.pem', stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        control = directory / 'control'
        control.mkdir(mode=0o710)
        os.chown(control, control_user.pw_uid, control_user.pw_gid)
        control_process = start(identity(control_user, control_user.pw_gid) + ['node', fixture, directory], 'control')
        wait_for(lambda: (control / 'ready').exists(), 'control fixture', control_process)
        config = directory / 'nginx.conf'
        config.write_text(f'''pid {directory}/nginx.pid; daemon off; master_process off;
events {{ worker_connections 128; }}
http {{ access_log off; client_body_temp_path {directory}/body; proxy_temp_path {directory}/proxy;
server {{ listen 198.18.0.1:8443 ssl; ssl_certificate {directory}/cert.pem; ssl_certificate_key {directory}/key.pem;
location = /xpn/vpn {{ proxy_pass http://127.0.0.1:3001; proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection upgrade; proxy_buffering off; }} }} }}
''')
        start(['nginx', '-p', f'{directory}/', '-c', config], 'nginx')
        server = start(identity(packet_user, packet_user.pw_gid) +
                       [binary, 'server', '3001', control / 'control.sock', '/xpn/vpn', 'xpn0', '--loopback'], 'server')
        web = directory / 'web'
        web.mkdir()
        payload = web / 'payload'
        payload.write_bytes(os.urandom(1024 * 1024))
        for port in (8444, 8445):
            start(['python3', '-m', 'http.server', str(port), '--bind', '0.0.0.0', '--directory', web], f'host-{port}')
            wait_for(lambda: run('curl', '--noproxy', '*', '--silent', '--fail', '--max-time', '1',
                                 f'http://127.0.0.1:{port}/payload', stdout=sp.DEVNULL, check=False).returncode == 0,
                     f'host HTTP port {port}')
        start(['nsenter', '-t', wan_ns.pid, '-n', '--', 'python3', '-m', 'http.server', '8080',
               '--bind', '192.0.2.2', '--directory', web], 'http')
        wait_for(lambda: ns(wan_ns, 'curl', '--noproxy', '*', '--silent', '--fail',
                            '--max-time', '1', 'http://192.0.2.2:8080/payload',
                            stdout=sp.DEVNULL, check=False).returncode == 0, 'HTTP fixture')
        ns(client_ns, 'ip', 'tuntap', 'add', 'dev', 'testvpn', 'mode', 'tun')
        ns(client_ns, 'ip', 'link', 'set', 'testvpn', 'mtu', '1400', 'up')
        for index, mode in enumerate(['split', 'full'], start=2):
            ns(client_ns, 'ip', 'addr', 'add', f'10.77.0.{index}/32', 'dev', 'testvpn')
            route = '192.0.2.0/24' if mode == 'split' else 'default'
            ns(client_ns, 'ip', 'route', 'add', route, 'dev', 'testvpn')
            if mode == 'split': ns(client_ns, 'ip', 'route', 'add', '10.77.0.1/32', 'dev', 'testvpn')
            options = []
            if os.environ.get('XPN_TEST_INNER') in ('0', '1'):
                options.append('--outer-only' if os.environ['XPN_TEST_INNER'] == '0' else '--inner-encryption')
            if os.environ.get('XPN_TEST_PQ') == '1': options.append('--require-pq')
            client = start(['nsenter', '-t', client_ns.pid, '-n', '--', binary, 'client', control / f'{mode}.json', 'testvpn', *options], mode)
            wait_for(lambda: 'CONNECTED' in (directory / f'{mode}.log').read_text(), f'{mode} authentication', client)
            for task in Path(f'/proc/{server.pid}/task').iterdir():
                status = dict(line.split(':', 1) for line in (task / 'status').read_text().splitlines() if ':' in line)
                assert set(status['Uid'].split()) == {str(packet_user.pw_uid)}
                assert all(int(status[key].strip(), 16) == 0 for key in ['CapInh', 'CapPrm', 'CapEff', 'CapAmb', 'CapBnd'])
                assert status['NoNewPrivs'].strip() == '1'
            output = directory / 'received'
            ns(client_ns, 'curl', '--noproxy', '*', '--fail', '--silent', '--show-error',
               '--retry', '3', '--retry-connrefused', '--max-time', '15', '-o', output, 'http://192.0.2.2:8080/payload')
            assert output.read_bytes() == payload.read_bytes(), 'Tunneled payload mismatch'
            for address in ('10.77.0.1', '192.0.2.1'):
                ns(client_ns, 'curl', '--noproxy', '*', '--fail', '--silent', '--max-time', '5', '-o', output,
                   f'http://{address}:8444/payload')
                assert output.read_bytes() == payload.read_bytes(), 'Server-host payload mismatch'
                assert ns(client_ns, 'curl', '--noproxy', '*', '--silent', '--max-time', '1',
                          f'http://{address}:8445/payload', stdout=sp.DEVNULL, check=False).returncode != 0, 'Private host port exposed'
            # iputils-ping is not needed: build an ICMP echo on a raw socket in the test namespace.
            ping = '''import socket,struct
s=socket.socket(socket.AF_INET,socket.SOCK_RAW,socket.IPPROTO_ICMP); s.settimeout(3)
packet=struct.pack('!BBHHH',8,0,0,1234,1)
total=sum(struct.unpack('!4H',packet)); total=(total>>16)+(total&65535); total+=(total>>16)
packet=struct.pack('!BBHHH',8,0,(~total)&65535,1234,1)
s.sendto(packet,('10.77.0.1',0))
while True:
 data,source=s.recvfrom(2048)
 if source[0]=='10.77.0.1' and data[20]==0 and data[24:28]==packet[4:8]: break
'''
            ns(client_ns, 'python3', '-c', ping)
            print(f'PASS: {mode} server tunnel/WAN address access, ping and private host-port isolation', flush=True)
            print(f'PASS: {mode} routing, pinned custom-SNI WSS, real TUN, NAT and non-root server threads', flush=True)
            client.terminate()
            client.wait(timeout=5)
            ns(client_ns, 'ip', 'route', 'del', route, 'dev', 'testvpn')
            if mode == 'split': ns(client_ns, 'ip', 'route', 'del', '10.77.0.1/32', 'dev', 'testvpn')
            ns(client_ns, 'ip', 'addr', 'del', f'10.77.0.{index}/32', 'dev', 'testvpn')
        if os.environ.get('XPN_TEST_CLIENT_SERVICE') == '1':
            # Exercise the client directly, without a service helper, against the installed
            # native executable, including total server loss and a fresh session.
            service = start(['nsenter', '-t', client_ns.pid, '-n', '--', 'python3',
                             ROOT / 'clients/linux/xpn.py', 'connect', control / 'split.json',
                             '--native', binary,
                             '--retry-initial', '1', '--retry-max', '2', '--stable-seconds', '120'], 'retry-client')
            log = directory / 'retry-client.log'
            connected = 'Connected. Ctrl-C disconnects'
            wait_for(lambda: connected in log.read_text(), 'client connection', service)
            server.terminate()
            server.wait(timeout=5)
            wait_for(lambda: 'retrying in' in log.read_text(), 'client outage retry', service)
            server = start(identity(packet_user, packet_user.pw_gid) +
                           [binary, 'server', '3001', control / 'control.sock', '/xpn/vpn', 'xpn0', '--loopback'], 'server-restarted')
            wait_for(lambda: log.read_text().count(connected) >= 2, 'client reconnect', service)
            ns(client_ns, 'curl', '--noproxy', '*', '--fail', '--silent', '--max-time', '5',
               '-o', output, 'http://192.0.2.2:8080/payload')
            assert output.read_bytes() == payload.read_bytes(), 'Reconnected payload mismatch'
            if os.environ.get('XPN_TEST_GATEWAY') == '1':
                # A veth models decrypted WireGuard ingress; the broker's actual
                # WireGuard interface check is tested separately.
                spec = importlib.util.spec_from_file_location('gateway', ROOT / 'deploy/gateway.py')
                gateway = importlib.util.module_from_spec(spec); spec.loader.exec_module(gateway)
                run('ip', 'link', 'add', 'wg-check', 'type', 'wireguard')
                gateway.wireguard_interface('wg-check')
                home = namespace('home-ns')
                run('ip', 'link', 'add', 'gw-test', 'type', 'veth', 'peer', 'name', 'home0')
                run('ip', 'link', 'set', 'home0', 'netns', home.pid)
                run('ip', 'addr', 'add', '198.19.0.1/30', 'dev', 'gw-test')
                run('ip', 'link', 'set', 'gw-test', 'up')
                ns(home, 'ip', 'addr', 'add', '198.19.0.2/30', 'dev', 'home0')
                ns(home, 'ip', 'link', 'set', 'home0', 'up')
                ns(home, 'ip', 'route', 'add', '10.77.0.0/24', 'via', '198.19.0.1')
                device_ip = json.loads((control / 'split.json').read_text())['address']
                start(['nsenter', '-t', client_ns.pid, '-n', '--', 'python3', '-m', 'http.server',
                       '8082', '--bind', device_ip, '--directory', web], 'gateway-device-http')
                start(['nsenter', '-t', client_ns.pid, '-n', '--', 'python3', '-m', 'http.server',
                       '8083', '--bind', device_ip, '--directory', web], 'gateway-device-private-http')
                start(['nsenter', '-t', home.pid, '-n', '--', 'python3', '-m', 'http.server',
                       '8083', '--bind', '198.19.0.2', '--directory', web], 'gateway-home-http')
                # Listen checks are inside their namespaces, without creating tunnel traffic.
                wait_for(lambda: ':8082' in ns(client_ns, 'ss', '-ltn', capture_output=True).stdout, 'device HTTP listener')
                wait_for(lambda: ':8083' in ns(client_ns, 'ss', '-ltn', capture_output=True).stdout, 'device private HTTP listener')
                wait_for(lambda: ':8083' in ns(home, 'ss', '-ltn', capture_output=True).stdout, 'home HTTP listener')
                def home_get(port=8082):
                    return ns(home, 'curl', '--noproxy', '*', '--fail', '--silent', '--max-time', '2',
                              '-o', '/dev/null', f'http://{device_ip}:{port}/payload', check=False).returncode
                assert home_get() != 0, 'Gateway opened before opt-in'
                config = dict(enabled=True, interface='gw-test', sources=['198.19.0.2/32'],
                              targets=[device_ip], tcpPorts=[8082], udpPorts=[], allowPing=True)
                try:
                    gateway.wireguard_interface('gw-test')
                    raise AssertionError('Non-WireGuard interface accepted')
                except gateway.PolicyError:
                    pass
                manager = gateway.Gateway(directory / 'gateway-policy.json', check_interface=lambda _: None)
                manager.request(dict(action='set', revision=0, policy=config))
                assert home_get() == 0, 'Enabled gateway did not forward to the XPN client'
                assert home_get(8083) != 0, 'Unselected destination port was reachable'
                # Split profile explicitly routes the home subnet, so this tests
                # the server firewall rather than missing routes/client ACLs.
                assert ns(client_ns, 'curl', '--noproxy', '*', '--fail', '--silent', '--max-time', '2',
                          '-o', '/dev/null', 'http://198.19.0.2:8083/payload', check=False).returncode != 0, 'XPN initiated a home connection'
                # Keep a TCP connection established across the live disable.
                ready, proceed = directory / 'gateway-connected', directory / 'gateway-disabled'
                existing = start(['nsenter', '-t', home.pid, '-n', '--', 'python3', '-c', '''
import pathlib, socket, sys, time
with socket.create_connection((sys.argv[1], 8082), timeout=3) as connection:
    pathlib.Path(sys.argv[2]).touch()
    deadline = time.monotonic() + 10
    while not pathlib.Path(sys.argv[3]).exists():
        if time.monotonic() > deadline: raise RuntimeError('Disable signal missing')
        time.sleep(0.05)
    connection.sendall(b'GET /payload HTTP/1.0\\r\\n\\r\\n')
    try:
        if connection.recv(1024): raise RuntimeError('Disabled gateway passed established traffic')
    except socket.timeout:
        pass
''', device_ip, ready, proceed], 'gateway-established')
                wait_for(ready.exists, 'established gateway connection')
                manager.request(dict(action='set', revision=1, policy={**config, 'enabled': False}))
                proceed.touch()
                assert existing.wait(timeout=6) == 0, 'Disabled gateway passed an established connection'
                assert home_get() != 0, 'Disabled gateway still accepted new connections'
                assert service.poll() is None and log.read_text().count(connected) == 2, 'Policy update restarted the tunnel'
                print('PASS: live gateway opt-in, scoped ports, SNAT replies, reverse isolation and disable without reconnect', flush=True)
            service.terminate()
            service.wait(timeout=10)
            assert service.returncode == 0, 'Client did not stop cleanly'
            links = ns(client_ns, 'ip', '-o', 'link', 'show', capture_output=True).stdout
            assert not any(': xpn' in line for line in links.splitlines()), 'Client TUN left after service stop'
            tables = ns(client_ns, 'nft', 'list', 'tables', capture_output=True).stdout
            assert 'xpn_' not in tables, 'Client firewall left after service stop'
            print('PASS: direct client reconnected after total server outage, transferred data, stopped and removed network state', flush=True)
    except BaseException:
        for path in directory.glob('*.log'):
            print(f'{path.name}:\n{path.read_text()[-6000:]}', file=sys.stderr)
        raise
    finally:
        for proc in reversed(processes):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except sp.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
        for handle in handles:
            handle.close()
        shutil.rmtree(directory)


if __name__ == '__main__':
    main()
