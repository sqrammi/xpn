#!/usr/bin/env python3
"""Install XPN from this checkout: sudo python3 deploy/install-server.py --url https://HOST/xpn"""
import argparse
import fcntl
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit

SOURCE = Path(__file__).resolve().parents[1]
NODE_VERSION = '24.22.1'
MARKER = '# Managed by XPN install-server.py'
UNITS = ['xpn-network', 'xpn-control', 'xpn-native']
ENV = Path('/etc/xpn.env')
STATE = Path('/etc/xpn/install.json')
HTTP = Path('/etc/nginx/conf.d/xpn-http.conf')
LOCATIONS = Path('/etc/nginx/snippets/xpn-locations.conf')
LOCK = Path('/run/lock/xpn-install.lock')
DATABASE = Path('/var/lib/xpn/xpn.db')
UNIT_DIR = Path('/etc/systemd/system')
PACKAGES = ('build-essential', 'cmake', 'ninja-build', 'pkg-config', 'libssl-dev',
            'libwebsockets-dev', 'libjansson-dev', 'libcurl4-openssl-dev',
            'iproute2', 'nftables', 'curl', 'xz-utils')


def command(*args, capture=False, env=None, check=True):
    return subprocess.run([str(a) for a in args], check=check, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None, env=env)


def safe_path(path):
    path = Path(path).resolve()
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(path)):
        raise ValueError(f'Use a path without whitespace or special characters: {path}')
    return path


def public_url(value):
    url = urlsplit(value)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.port not in (None, 443)
            or not re.fullmatch(r'[A-Za-z0-9.-]+', url.hostname)
            or not re.fullmatch(r'/[A-Za-z0-9/_-]+', url.path.rstrip('/'))):
        raise ValueError('Use an HTTPS hostname on port 443 with a path, e.g. https://vpn.example.com/xpn')
    return value.rstrip('/'), url.hostname, url.path.rstrip('/')


def tokens(text):
    """Nginx lexer with source offsets; braces inside quotes/comments are data."""
    result, i = [], 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        if text[i] == '#':
            end = text.find('\n', i)
            i = len(text) if end < 0 else end + 1
            continue
        start = i
        if text[i] in '{};':
            result.append((text[i], i, i + 1))
            i += 1
            continue
        value, quote = '', None
        while i < len(text):
            c = text[i]
            if c == '\\' and i + 1 < len(text):
                value += text[i + 1]; i += 2; continue
            if quote:
                if c == quote: quote = None
                else: value += c
            elif c in "\"'": quote = c
            elif c.isspace() or c in '{};#': break
            else: value += c
            i += 1
        if quote: raise ValueError('Unterminated quote in nginx configuration')
        if i == start: raise ValueError('Cannot parse nginx configuration')
        result.append((value, start, i))
    return result


def blocks(text):
    stack, pending, found = [], [], []
    for token, start, end in tokens(text):
        if token == '{':
            block = {'header': pending, 'open': end, 'directives': [], 'children': []}
            if stack: stack[-1]['children'].append(block)
            stack.append(block); pending = []
        elif token == '}':
            if not stack or pending: raise ValueError('Unsupported nginx block syntax')
            block = stack.pop(); block['close'] = start
            if block['header'] == ['server']: found.append(block)
        elif token == ';':
            if stack: stack[-1]['directives'].append(pending)
            pending = []
        else: pending.append(token)
    if stack: raise ValueError('Unbalanced nginx configuration')
    return found


def select_site(host, explicit=None):
    paths = [Path(explicit)] if explicit else sorted(Path('/etc/nginx/sites-enabled').glob('*')) + sorted(Path('/etc/nginx/conf.d').glob('*.conf'))
    candidates, seen = [], set()
    for path in paths:
        path = path.resolve()
        if path in seen or not path.is_file(): continue
        seen.add(path)
        text = path.read_text()
        for block in blocks(text):
            directives = block['directives']
            listens = [d for d in directives if d and d[0] == 'listen']
            if not any('ssl' in d and any(x == '443' or x.endswith(':443') for x in d[1:]) for d in listens): continue
            names = [x for d in directives if d and d[0] == 'server_name' for x in d[1:]]
            default = any('default_server' in d for d in listens)
            candidates.append((host in names, default, path, text, block))
    exact = [x for x in candidates if x[0]]
    choices = exact or [x for x in candidates if x[1]]
    if explicit and not choices and len(candidates) == 1: choices = candidates
    if len(choices) != 1:
        raise ValueError('Cannot choose one HTTPS nginx server. Specify --nginx-site /etc/nginx/sites-enabled/YOUR-SITE; its HTTPS block must match the hostname or be the unique default.')
    _, _, path, text, block = choices[0]
    return path, text, block


def integrate_site(text, block, base):
    include = ['include', str(LOCATIONS)]
    if include in block['directives']: return text
    for child in block['children']:
        header = child['header']
        if header and header[0] == 'location' and any(x.rstrip('/') == base or x.startswith(base + '/') for x in header[1:]):
            raise ValueError(f'Existing {base} locations require manual reconciliation; refusing to overwrite them')
    return text[:block['close']] + f'    include {LOCATIONS}; # XPN\n' + text[block['close']:]


def read_environment(text):
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        key, separator, value = line.partition('=')
        if not separator: raise ValueError('Invalid existing /etc/xpn.env line')
        value = value.strip()
        if value.startswith(('"', "'")):
            parts = shlex.split(value)
            if len(parts) != 1: raise ValueError('Unsupported quoted environment value')
            value = parts[0]
        result[key.strip()] = value
    return result


def environment(url, port, pin, existing=None):
    if existing is not None:
        values = read_environment(existing)
        if values.get('PUBLIC_URL') != url or values.get('PORT') != str(port):
            raise ValueError('Existing PUBLIC_URL/PORT differs. Reuse its values; installer does not silently change deployed device endpoints.')
        if not re.fullmatch('[a-fA-F0-9]{64}', values.get('MASTER_KEY', '')) or len(values.get('ADMIN_TOKEN', '')) < 32:
            raise ValueError('Existing ADMIN_TOKEN/MASTER_KEY is missing or invalid; refusing to replace credentials')
        if values.get('DATA_DIR') != '/var/lib/xpn' or values.get('CONTROL_SOCKET') != '/run/xpn/control.sock':
            raise ValueError('Existing custom data/socket paths need manual migration')
        return existing
    return (f'{MARKER}\nPUBLIC_URL={url}\nMASTER_KEY={secrets.token_hex(32)}\n'
            f'ADMIN_TOKEN={secrets.token_hex(32)}\nDATA_DIR=/var/lib/xpn\n'
            f'CONTROL_SOCKET=/run/xpn/control.sock\nPORT={port}\nVPN_CERTIFICATE_PINS={pin}\n')


def host_tcp_ports(value):
    if not re.fullmatch(r'[0-9]+(?:,[0-9]+)*', value):
        raise argparse.ArgumentTypeError('Use comma-separated host TCP ports, e.g. 22,443')
    ports = sorted(set(map(int, value.split(','))))
    if any(not 1 <= port <= 65535 for port in ports):
        raise argparse.ArgumentTypeError('Host TCP ports must be between 1 and 65535')
    return ','.join(map(str, ports))


def unit_files(source, node, port, base, host_ports='22,443'):
    view = Path('/run/xpn-source')
    try: executable = view / node.relative_to(source)
    except ValueError: executable = node
    control = (source / 'deploy/xpn-control.service').read_text()
    control = control.replace('WorkingDirectory=/opt/xpn', f'BindReadOnlyPaths={source}:{view}\nWorkingDirectory={view}')
    control = control.replace('ExecStart=/usr/bin/node /opt/xpn/server/main.mjs', f'ExecStart=/usr/bin/env {executable} {view}/server/main.mjs')
    native = (source / 'deploy/xpn-native.service').read_text()
    native = native.replace('ExecStart=/usr/local/bin/xpnd server 3001 /run/xpn/control.sock /xpn/vpn xpn0 --loopback',
                            f'BindReadOnlyPaths={source}:{view}\nExecStart=/usr/bin/env {view}/build/native/xpnd server {port} /run/xpn/control.sock {base}/vpn xpn0 --loopback')
    network = (source / 'deploy/xpn-network.service').read_text().replace('/opt/xpn/deploy/network.sh', f'/bin/sh {source}/deploy/network.sh')
    network = network.replace('[Service]\n', f'[Service]\nEnvironment=XPN_HOST_TCP_PORTS={host_tcp_ports(host_ports)}\n')
    return {UNIT_DIR / f'{name}.service': MARKER + '\n' + body
            for name, body in zip(UNITS, [network, control, native])}


class Changes:
    """Back up touched configuration files and restore them if installation fails."""
    def __init__(self, backup):
        self.backup, self.before = Path(backup), {}
        self.backup.mkdir(parents=True, mode=0o700)
        self.logfile = self.backup / 'actions.log'
        self.report = self.backup / 'changes.md'
        self.entries = []
        self.finish('In progress')

    def log(self, message):
        print(message, flush=True)
        with self.logfile.open('a') as f: f.write(message + '\n')

    def run(self, *args, **kwargs):
        self.log('$ ' + shlex.join(map(str, args)))
        result = command(*args, **{**kwargs, 'capture': True, 'check': False})
        for output in (result.stdout, result.stderr):
            if output: self.log(output.rstrip())
        if result.returncode and kwargs.get('check', True):
            raise subprocess.CalledProcessError(result.returncode, args)
        return result

    def changed(self, target, description):
        entry = f'{target}: {description}'
        self.entries.append(entry)
        self.log(entry)
        self.finish('In progress')

    def finish(self, status):
        self.report.write_text('# XPN installation changes\n\n'
                               f'Status: {status}\n\n' +
                               ('\n'.join('- ' + entry for entry in self.entries) if self.entries
                                else 'No installation changes.') +
                               '\n\nCommands and output: `actions.log`. Previous configuration: `manifest.json` and path-matched backups.\n')

    def write(self, path, text, mode=0o644, reason='installation configuration'):
        path = Path(path)
        if path.is_symlink(): raise ValueError(f'Refusing generated-file symlink: {path}')
        previous = path.read_bytes() if path.exists() else None
        old_mode = path.stat().st_mode & 0o777 if path.exists() else None
        if previous == text.encode() and old_mode == mode: return False
        if path not in self.before:
            self.before[path] = (previous, old_mode)
            if previous is not None:
                saved = self.backup / str(path).lstrip('/')
                saved.parent.mkdir(parents=True, exist_ok=True)
                saved.write_bytes(previous); saved.chmod(0o600)
            (self.backup / 'manifest.json').write_text(json.dumps({str(p): {'existed': old is not None, 'mode': m} for p, (old, m) in self.before.items()}, indent=2))
        missing = []
        parent = path.parent
        while not parent.exists():
            missing.append(parent); parent = parent.parent
        for parent in reversed(missing):
            parent.mkdir(mode=0o755)
            self.changed(parent, 'Added configuration directory (0755)')
        if previous == text.encode():
            path.chmod(mode)
            self.changed(path, f'Corrected permissions {old_mode:04o} → {mode:04o}; {reason}')
            return True
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.xpn-')
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, 'w') as f: f.write(text)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        self.changed(path, f'{"Added" if previous is None else "Updated"} {reason} (mode {mode:04o})')
        return True

    def rollback(self, preserve=()):
        for path, (previous, mode) in reversed(list(self.before.items())):
            if path in preserve:
                self.changed(path, 'Retained generated credentials during rollback to preserve database access')
                continue
            if previous is None: path.unlink(missing_ok=True)
            else: path.write_bytes(previous); path.chmod(mode)
            self.changed(path, 'Rolled back to previous contents/permissions' if previous is not None else 'Removed during rollback')


def fingerprint(paths):
    """Content, not timestamps: include names to detect additions/deletions."""
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        digest.update(str(path).encode() + b'\0')
        if path.is_file():
            with path.open('rb') as stream:
                digest.update(hashlib.file_digest(stream, 'sha256').digest())
        else: digest.update(b'missing')
    return digest.hexdigest()


def tree_files(path):
    return [p for p in path.rglob('*') if p.is_file() and '__pycache__' not in p.parts]


def package_versions():
    result = command('dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Status}\n',
                     capture=True)
    return {name: version for line in result.stdout.splitlines()
            for name, version, status in [line.split('\t')]
            if status == 'installed'}


def content_differs(path, text):
    return not path.exists() or path.read_bytes() != text.encode()


def account_setup(changes, source):
    group = command('getent', 'group', 'xpn', capture=True, check=False)
    user = command('getent', 'passwd', 'xpn', capture=True, check=False)
    if group.returncode or user.returncode:
        changes.run('sh', source / 'deploy/create-users.sh')
        if group.returncode: changes.changed('/etc/group', 'Added xpn system group')
        if user.returncode:
            changes.changed('/etc/passwd and /etc/shadow', 'Added xpn system account with nologin shell')
    uid = command('id', '-u', 'xpn', capture=True).stdout.strip()
    gid = command('id', '-g', 'xpn', capture=True).stdout.strip()
    if uid == '0' or gid == '0': raise ValueError('xpn must have a non-root UID and primary GID')


def check_https(changes, host, url):
    # systemctl's nginx reload returns after signalling the master, before new
    # workers necessarily accept connections. Check readiness, not just the signal.
    args = ('curl', '--fail', '--silent', '--show-error', '--noproxy', '*', '--max-time', '10',
            '--resolve', f'{host}:443:127.0.0.1', url + '/', '-o', '/dev/null')
    for attempt in range(10):
        result = changes.run(*args, check=False)
        if result.returncode == 0: return
        if attempt < 9: time.sleep(1)
    raise subprocess.CalledProcessError(result.returncode, args)


def node_ok(path):
    try:
        version = command(path, '--version', capture=True).stdout.strip().lstrip('v')
        return tuple(map(int, version.split('.'))) >= (24, 13, 1)
    except (OSError, ValueError, subprocess.CalledProcessError): return False


def node_candidate(source):
    candidates = sorted((source / 'build/tools').glob('node-v*-linux-*/bin/node'), reverse=True)
    if shutil.which('node'): candidates.append(Path(shutil.which('node')).resolve())
    return next((p for p in candidates if node_ok(p)), None)


def install_node(source, changes):
    arch = {'x86_64': 'x64', 'aarch64': 'arm64'}.get(platform.machine())
    if not arch: raise ValueError('Private Node download supports x86-64 and arm64')
    tools = source / 'build/tools'; tools.mkdir(parents=True, exist_ok=True)
    name = f'node-v{NODE_VERSION}-linux-{arch}'
    destination = tools / name
    if destination.exists(): raise ValueError(f'Existing unusable Node directory: {destination}')
    url = f'https://nodejs.org/dist/v{NODE_VERSION}/'
    with tempfile.TemporaryDirectory(dir=tools, prefix='node-download-') as tmp:
        tmp = Path(tmp)
        changes.log(f'Download private Node {NODE_VERSION} from nodejs.org into {tools}')
        with urllib.request.urlopen(url + 'SHASUMS256.txt', timeout=60) as response: sums = response.read().decode()
        filename = name + '.tar.xz'
        expected = next(line.split()[0] for line in sums.splitlines() if line.split()[-1] == filename)
        archive = tmp / filename
        with urllib.request.urlopen(url + filename, timeout=60) as response, archive.open('wb') as f: shutil.copyfileobj(response, f)
        with archive.open('rb') as f:
            if hashlib.file_digest(f, 'sha256').hexdigest() != expected:
                raise ValueError('Node download checksum mismatch')
        with tarfile.open(archive) as tar:
            if any(not (m.name == name or m.name.startswith(name + '/')) for m in tar.getmembers()):
                raise ValueError('Unexpected Node archive paths')
            tar.extractall(tmp, filter='data')
        (tmp / name).rename(destination)
    changes.changed(destination, 'Installed checksum-verified private Node runtime ' + NODE_VERSION)
    return destination / 'bin/node'


def available_port(preferred, reserved):
    for port in range(preferred, preferred + 100):
        if port in reserved or port > 65535: continue
        try:
            with socket.socket() as s: s.bind(('127.0.0.1', port))
            return port
        except OSError: pass
    raise ValueError('No available backend port; specify --control-port / --native-port')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='Public HTTPS URL, including /xpn (or another path)')
    parser.add_argument('--nginx-site', help='Existing enabled HTTPS site file; auto-detected when unambiguous')
    parser.add_argument('--certificate', help='Existing nginx leaf/fullchain PEM; normally auto-detected')
    parser.add_argument('--control-port', type=int)
    parser.add_argument('--native-port', type=int)
    parser.add_argument('--host-tcp-ports', type=host_tcp_ports, help='Host TCP services reachable through VPN; defaults to 22,443; ping is also allowed. Reruns preserve the selected list.')
    parser.add_argument('--plan', action='store_true', help='Read-only preview; does not install or start anything')
    parser.add_argument('--skip-build', action='store_true', help='Use already built native executable and node_modules')
    parser.add_argument('--show-admin-token', action='store_true', help='Print the existing admin token locally (root only)')
    args = parser.parse_args()
    if args.show_admin_token:
        if os.geteuid(): raise ValueError('Run with sudo to read the admin token')
        print(read_environment(ENV.read_text())['ADMIN_TOKEN']); return
    if not args.url: parser.error('--url is required')
    if not args.plan and (os.geteuid() or sys.platform != 'linux'):
        raise ValueError('Installation requires root on Ubuntu; use sudo python3 deploy/install-server.py ...')
    if args.plan:
        install(args)
    else:
        # Serialize state inspection as well as writes; a second installer must
        # never rotate first-install secrets or roll back another run's work.
        fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as lock:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('Another XPN installation is in progress')
            install(args)


def install(args):
    source = safe_path(SOURCE)
    url, host, base = public_url(args.url)
    site, site_text, block = select_site(host, args.nginx_site)
    site = safe_path(site)
    edited_site = integrate_site(site_text, block, base)
    certificates = [d[1] for d in block['directives'] if d and d[0] == 'ssl_certificate' and len(d) == 2]
    certificate = args.certificate or (certificates[0] if len(certificates) == 1 else None)
    if not certificate or not Path(certificate).is_absolute():
        raise ValueError('Cannot identify nginx certificate; provide --certificate /absolute/path/fullchain.pem')
    der = subprocess.check_output(['openssl', 'x509', '-in', certificate, '-outform', 'DER'])
    pin = hashlib.sha256(der).hexdigest()
    previous = json.loads(STATE.read_text()) if STATE.exists() else {}
    host_ports = args.host_tcp_ports or previous.get('host_tcp_ports', '22,443')
    old_env = ENV.read_text() if ENV.exists() else None
    if old_env is None and DATABASE.exists():
        raise ValueError('Existing database has no /etc/xpn.env; restore its original MASTER_KEY before installing')
    values = read_environment(old_env) if old_env is not None else {}
    nginx_dump = command('nginx', '-T', capture=True).stdout
    reserved = set(map(int, re.findall(r'127\.0\.0\.1:(\d+)', nginx_dump)))
    control_port = args.control_port or int(values.get('PORT', 0)) or available_port(3300, reserved)
    native_port = args.native_port or previous.get('native_port') or available_port(3301, reserved | {control_port})
    if not (1024 <= control_port <= 65535 and 1024 <= native_port <= 65535) or control_port == native_port:
        raise ValueError('Choose distinct unprivileged backend ports (1024–65535)')
    if previous and (previous.get('source') != str(source) or previous.get('site') != str(site) or previous.get('native_port') != native_port):
        raise ValueError('Existing installation uses a different source/site/native port; migrate explicitly instead of silently replacing it')
    for unit in UNITS:
        if list((UNIT_DIR / f'{unit}.service.d').glob('*.conf')):
            raise ValueError(f'Existing {unit} drop-ins need reconciliation before using the installer')
    for path in [HTTP, LOCATIONS] + [UNIT_DIR / f'{u}.service' for u in UNITS]:
        template = source / 'deploy' / path.name
        # Adopt verbatim files from the old manual instructions, with backups.
        # A custom unit/include still needs an explicit operator reconciliation.
        stock = template.is_file() and path.exists() and path.read_text() == template.read_text()
        if path.exists() and not path.read_text().startswith(MARKER) and not stock:
            raise ValueError(f'Existing unmanaged file needs reconciliation: {path}')
    env_text = environment(url, control_port, pin, old_env)
    node = node_candidate(source)
    print(f'Checkout: {source}\nConsole: {url}/\nHTTPS site: {site}\nCertificate: {certificate}\n'
          f'Backend ports: {control_port} / {native_port}\nVPN-accessible host TCP ports: {host_ports}\nService account: xpn\n'
          f'Node: {node or "download private Node " + NODE_VERSION + " into build/tools"}')
    if args.plan:
        print('Plan: reconcile missing packages/account, changed builds/configuration and affected services; preserve credentials; validate HTTP/HTTPS. Unchanged installation files and services are left alone. No changes made.')
        return
    changes = Changes(Path('/var/backups/xpn') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    active = {u for u in UNITS if command('systemctl', 'show', '-p', 'ActiveState', '--value', u,
                                        capture=True, check=False).stdout.strip() in ('active', 'activating', 'reloading')}
    enabled = {u for u in UNITS if command('systemctl', 'is-enabled', '--quiet', u, capture=True, check=False).returncode == 0}
    stopped, started, newly_enabled = set(), set(), set()
    unit_changed, nginx_reloaded = False, False

    def stop(units, reason):
        # Requires= propagates control/network stops to native, so explicitly
        # include the dependent to restore it even when its own file is current.
        units = set(units)
        if units & {'xpn-control', 'xpn-network'}: units.add('xpn-native')
        targets = [u for u in reversed(UNITS) if u in units & active - stopped]
        if targets:
            stopped.update(targets)
            changes.run('systemctl', 'stop', *targets)
            for unit in targets: changes.changed(unit + '.service', 'Stopped: ' + reason)

    try:
        changes.log(f'Install from {source}; report/backups: {changes.backup}')
        packages = package_versions()
        def installed(name): return name in packages or any(p.split(':')[0] == name for p in packages)
        missing = [p for p in PACKAGES if not installed(p)]
        if missing and not args.skip_build:
            changes.run('apt-get', 'update', '-qq')
            changes.changed('/var/lib/apt/lists', 'Refreshed package indexes for missing dependencies')
            try:
                changes.run('apt-get', 'install', '-y', '--no-upgrade', *missing,
                            env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'})
            finally:
                after = package_versions()
                for name in sorted(after):
                    if packages.get(name) != after[name]:
                        changes.changed('APT ' + name, ('Installed ' if name not in packages else 'Updated from ' + packages[name] + ' to ') + after[name])
                packages = after
        node = node or install_node(source, changes)
        if not node_ok(node): raise ValueError('Node 24.13.1+ is required')
        safe_path(node)
        env = {**os.environ, 'PATH': str(node.parent) + ':' + os.environ['PATH']}
        binary = source / 'build/native/xpnd'
        modules = source / 'node_modules'
        old_build = previous.get('build', {})
        # A recorded successful build is reusable only with matching inputs AND
        # outputs. Deleted/replaced artifacts must be repaired on the next run.
        inputs = {
            'native': fingerprint(tree_files(source / 'native')),
            'npm': fingerprint([source / 'package.json', source / 'package-lock.json', node]),
            'packages': {p: v for p, v in packages.items() if p.split(':')[0] in PACKAGES},
        }
        native_build = (old_build.get('native') != inputs['native'] or old_build.get('packages') != inputs['packages']
                        or old_build.get('binary') != fingerprint([binary]) or not os.access(binary, os.X_OK))
        npm_build = (old_build.get('npm') != inputs['npm']
                     or old_build.get('modules') != fingerprint(tree_files(modules))
                     or not (modules / 'qrcode/package.json').exists())
        if not args.skip_build:
            if npm_build:
                stop({'xpn-control'}, 'Node dependencies need installation')
                changes.run('npm', 'ci', '--omit=dev', '--ignore-scripts', '--prefix', source, env=env)
                changes.changed(modules, 'Installed locked production dependencies (npm cache/logs may also change)')
            if native_build:
                stop({'xpn-native'}, 'native build inputs or artifacts changed')
                changes.run('cmake', '-S', source / 'native', '-B', source / 'build/native', '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release')
                changes.run('cmake', '--build', source / 'build/native', '-j2')
                changes.run('ctest', '--test-dir', source / 'build/native', '--output-on-failure')
                changes.changed(source / 'build/native', 'Configured, built and tested native artifacts')
        if not os.access(binary, os.X_OK) or not (modules / 'qrcode/package.json').exists():
            raise ValueError('Missing native build or npm dependencies')
        build = {**inputs, 'binary': fingerprint([binary]), 'modules': fingerprint(tree_files(modules))}
        if args.skip_build:
            # Trust prebuilt output for this run, but do not claim we verified
            # its correspondence to the current sources/dependency lock.
            build = old_build
        account_setup(changes, source)
        if not previous and (command('ip', 'link', 'show', 'xpn0', capture=True, check=False).returncode == 0
                             or command('nft', 'list', 'table', 'inet', 'xpn', capture=True, check=False).returncode == 0):
            raise ValueError('Existing xpn0 / inet xpn resources are not managed by this installer')
        if not previous:
            pool = ipaddress.ip_network('10.77.0.0/24')
            routes = json.loads(command('ip', '-j', '-4', 'route', 'show', 'table', 'main', capture=True).stdout)
            for route in routes:
                destination = route.get('dst', 'default')
                if destination != 'default' and pool.overlaps(ipaddress.ip_network(destination, strict=False)):
                    raise ValueError(f'VPN pool 10.77.0.0/24 overlaps existing route {destination}; choose another pool before installing')
        units = unit_files(source, node, native_port, base, host_ports)
        applied = {
            'xpn-control': fingerprint(tree_files(source / 'server') + [node]) + hashlib.sha256(env_text.encode()).hexdigest() + fingerprint(tree_files(modules)),
            'xpn-native': fingerprint([binary]),
            'xpn-network': fingerprint([source / 'deploy/network.sh']),
        }
        needs_restart = {u for u in UNITS if previous.get('applied', {}).get(u) != applied[u]}
        # Detect deletion of resources even when the oneshot unit remains active.
        if previous and ('xpn-network' in active) and (
                command('ip', 'link', 'show', 'xpn0', capture=True, check=False).returncode
                or command('nft', 'list', 'table', 'inet', 'xpn', capture=True, check=False).returncode
                or command('sysctl', '-n', 'net.ipv4.ip_forward', capture=True).stdout.strip() != '1'):
            needs_restart.add('xpn-network')
        for path, body in units.items():
            if content_differs(path, body): needs_restart.add(path.stem)
        stop(needs_restart, 'configuration, runtime files or network resources changed')
        for unit, port in (('xpn-control', control_port), ('xpn-native', native_port)):
            if unit not in active or unit in stopped:
                with socket.socket() as sock: sock.bind(('127.0.0.1', port))
        changes.write(ENV, env_text, 0o600, 'admin/database credentials and server settings; existing values preserved')
        for path, body in units.items():
            reason = ('network setup service' if path.stem == 'xpn-network' else
                      'non-root service with read-only checkout mounted at /run/xpn-source')
            unit_changed |= content_differs(path, body)
            changes.write(path, body, reason=reason)
        locations = (source / 'deploy/nginx-xpn-locations.conf').read_text().replace('/xpn', base).replace(':3000', f':{control_port}').replace(':3001', f':{native_port}')
        http_text = MARKER + '\n' + (source / 'deploy/nginx-xpn-http.conf').read_text()
        nginx_changed = (content_differs(HTTP, http_text) or content_differs(LOCATIONS, MARKER + '\n' + locations)
                         or content_differs(site, edited_site))
        changes.write(HTTP, http_text, reason='nginx WebSocket map and request limit zones')
        changes.write(LOCATIONS, MARKER + '\n' + locations, reason=f'nginx {base} routes to loopback ports {control_port}/{native_port}')
        changes.write(site, edited_site, site.stat().st_mode & 0o777, reason=f'include for {LOCATIONS} in selected HTTPS server')
        changes.run('nginx', '-t')
        if unit_changed:
            changes.run('systemctl', 'daemon-reload')
            changes.changed('systemd', 'Reloaded changed unit definitions')
        to_start = [u for u in UNITS if u not in active or u in stopped]
        if to_start:
            # Track before invoking: a failed start can partially create resources.
            started.update(to_start)
            changes.run('systemctl', 'start', *to_start)
            for unit in to_start: changes.changed(unit + '.service', 'Started' + (' after update' if unit in stopped else ''))
            if 'xpn-network' in to_start:
                changes.changed('xpn0 / inet xpn / net.ipv4.*', 'Applied TUN 10.77.0.1/24, MTU 1400, VPN firewall/NAT, IPv4 forwarding=1, xpn0 rp_filter=2 and accept_source_route=0')
                changes.changed('inet xpn input', f'Allowed VPN clients to ping the host and access TCP ports {host_ports}; other host traffic remains blocked')
            if 'xpn-control' in to_start:
                changes.changed('/run/xpn and /var/lib/xpn', 'Service initialized/reused runtime socket and persistent database directories')
        token = read_environment(env_text)['ADMIN_TOKEN']
        request = urllib.request.Request(f'http://127.0.0.1:{control_port}{base}/api/users', headers={'Authorization': 'Bearer ' + token})
        local_http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for attempt in range(30):
            try:
                with local_http.open(request, timeout=2) as response:
                    if response.status != 200: raise ValueError('Admin API health check failed')
                break
            except OSError:
                if attempt == 29: raise
                time.sleep(1)
        for unit in UNITS: changes.run('systemctl', 'is-active', '--quiet', unit)
        if nginx_changed:
            nginx_reloaded = True
            changes.run('systemctl', 'reload', 'nginx')
            changes.changed('nginx.service', 'Reloaded changed proxy configuration')
        check_https(changes, host, url)
        to_enable = [u for u in UNITS if u not in enabled]
        if to_enable:
            newly_enabled.update(to_enable)
            changes.run('systemctl', 'enable', *to_enable)
            for unit in to_enable: changes.changed('/etc/systemd/system/multi-user.target.wants/' + unit + '.service', 'Enabled startup symlink')
        changes.write(STATE, json.dumps({'source': str(source), 'site': str(site), 'native_port': native_port,
                                        'url': url, 'host_tcp_ports': host_ports, 'build': build, 'applied': applied}, indent=2) + '\n',
                      0o600, 'successful installation/build fingerprints for incremental reruns')
        changes.finish('Succeeded')
        changes.log(('Installed/updated.' if changes.entries else 'Already up to date; no installation changes.') +
                    f' Open {url}/\nChange report: {changes.report}\nShow admin token locally: sudo python3 {source}/deploy/install-server.py --show-admin-token')
    except BaseException:
        changes.log('Installation failed. Restoring changed configuration; packages, account and build artifacts are retained.')
        # Do not stop unrelated healthy units on a no-change health-check failure.
        affected = stopped | started
        if affected:
            changes.run('systemctl', 'stop', *[u for u in reversed(UNITS) if u in affected], check=False)
            changes.changed('XPN services', 'Stopped affected units for rollback: ' + ', '.join(sorted(affected)))
        for unit in sorted(newly_enabled):
            changes.run('systemctl', 'disable', unit, check=False)
            changes.changed(unit + '.service', 'Disabled startup during rollback')
        preserve = {ENV} if old_env is None and ENV in changes.before else set()
        changes.rollback(preserve=preserve)
        if unit_changed: changes.run('systemctl', 'daemon-reload', check=False)
        if affected & active:
            changes.run('systemctl', 'start', *[u for u in UNITS if u in affected & active], check=False)
            changes.changed('XPN services', 'Requested restart of previously running affected units')
        if nginx_reloaded and command('nginx', '-t', capture=True, check=False).returncode == 0:
            changes.run('systemctl', 'reload', 'nginx', check=False)
            changes.changed('nginx.service', 'Reloaded restored proxy configuration')
        changes.finish('Failed; configuration rollback attempted (see actions.log)')
        changes.log(f'Inspect {changes.report}. Build artifacts/database and any global IPv4 forwarding change are retained; configuration rollback does not roll back application binaries.')
        raise


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f'XPN installation error: {error}', file=sys.stderr)
        sys.exit(1)
