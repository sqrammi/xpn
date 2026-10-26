#!/usr/bin/env python3
"""Root-only Linux test in disposable network namespaces; no host routes/firewall changes.

Requires the xpn account, Node 24, nginx, iproute2, nftables, curl,
util-linux and a built xpnd. Run: sudo env PATH="$PATH" python3
native/tests/tun-integration.py /absolute/path/to/xpnd
"""
import os
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
        run('sh', ROOT / 'deploy/network.sh', env={**os.environ, 'XPN_WAN_IFACE': 'test-wan'})
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
            client = start(['nsenter', '-t', client_ns.pid, '-n', '--', binary, 'client', control / f'{mode}.json', 'testvpn'], mode)
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
            print(f'PASS: {mode} routing, pinned custom-SNI WSS, real TUN, NAT and non-root server threads', flush=True)
            client.terminate()
            client.wait(timeout=5)
            ns(client_ns, 'ip', 'route', 'del', route, 'dev', 'testvpn')
            ns(client_ns, 'ip', 'addr', 'del', f'10.77.0.{index}/32', 'dev', 'testvpn')
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
