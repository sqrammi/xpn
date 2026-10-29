"""Installer configuration regressions; all writes use temporary directories."""
import importlib.util
from contextlib import ExitStack
from pathlib import Path
import shutil
import subprocess
import socket
import sys
import errno
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('installer', ROOT / 'deploy/install-server.py')
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def simulate_install(self, failure=False, plan=False, repeat=None, build=False):
        """Exercise the orchestration with actual temporary config files; fake
        only OS commands, HTTP, root identity and privileged destination paths."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'checkout'; source.mkdir()
            shutil.copytree(ROOT / 'deploy', source / 'deploy')
            shutil.copytree(ROOT / 'native', source / 'native')
            shutil.copytree(ROOT / 'server', source / 'server')
            for name in ('package.json', 'package-lock.json'): shutil.copy(ROOT / name, source / name)
            binary = source / 'build/native/xpnd'; binary.parent.mkdir(parents=True)
            binary.write_text('test binary'); binary.chmod(0o755)
            package = source / 'node_modules/qrcode/package.json'; package.parent.mkdir(parents=True)
            package.write_text('{}')
            site = root / 'site'
            original = 'server { listen 443 ssl; server_name vpn.example.com; ssl_certificate /etc/ssl/cert.pem; location /other { return 200; } }\n'
            site.write_text(original)
            env, state = root / 'xpn.env', root / 'install.json'
            http, locations = root / 'http.conf', root / 'locations.conf'
            calls = []
            running = False
            real_units, real_changes = installer.unit_files, installer.Changes

            def units(*args):
                return {root / 'units' / path.name: body for path, body in real_units(*args).items()}

            def command(*args, **kwargs):
                args = tuple(map(str, args)); calls.append(args)
                code, output = 0, ''
                if args[:2] == ('dpkg-query', '-W'):
                    output = ''.join(p + '\t1.0\tinstalled\n' for p in installer.PACKAGES)
                elif args[:2] == ('nginx', '-T'): output = original
                elif args[:2] == ('systemctl', 'show'): output = 'active\n' if running else 'inactive\n'
                elif args[:2] == ('systemctl', 'is-enabled'): code = 0 if running else 1
                elif args[:3] == ('ip', 'link', 'show') or args[:3] == ('nft', 'list', 'table'): code = 0 if running else 1
                elif args[:2] == ('sysctl', '-n'): output = '1\n'
                elif args[:3] == ('ip', '-j', '-4'): output = '[]'
                elif args == ('nginx', '-t') and failure and http.exists():
                    raise subprocess.CalledProcessError(1, args)
                return subprocess.CompletedProcess(args, code, stdout=output, stderr='')

            opener = MagicMock()
            opener.open.return_value.__enter__.return_value.status = 200
            argv = ['install-server.py', '--url', 'https://vpn.example.com/xpn', '--nginx-site', str(site), '--skip-build', '--host-tcp-ports', '85,443']
            if build: argv.remove('--skip-build')
            if plan: argv.append('--plan')
            with ExitStack() as stack:
                for name, value in {'SOURCE': source, 'ENV': env, 'STATE': state, 'HTTP': http, 'LOCATIONS': locations, 'LOCK': root / 'installer.lock', 'DATABASE': root / 'data/xpn.db', 'UNIT_DIR': root / 'units'}.items():
                    stack.enter_context(patch.object(installer, name, value))
                stack.enter_context(patch.object(installer, 'unit_files', side_effect=units))
                stack.enter_context(patch.object(installer, 'Changes', side_effect=lambda path: real_changes(root / 'backups' / path.name)))
                stack.enter_context(patch.object(installer, 'command', side_effect=command))
                stack.enter_context(patch.object(installer, 'available_port', side_effect=lambda preferred, _: preferred))
                stack.enter_context(patch.object(installer.socket, 'socket'))
                stack.enter_context(patch.object(installer, 'node_candidate', return_value=source / 'build/tools/node/bin/node'))
                stack.enter_context(patch.object(installer, 'node_ok', return_value=True))
                stack.enter_context(patch.object(installer.os, 'geteuid', return_value=0))
                stack.enter_context(patch.object(installer.sys, 'platform', 'linux'))
                stack.enter_context(patch.object(installer.sys, 'argv', argv))
                stack.enter_context(patch.object(installer.subprocess, 'check_output', return_value=b'certificate'))
                stack.enter_context(patch.object(installer.urllib.request, 'build_opener', return_value=opener))
                if failure:
                    with self.assertRaises(subprocess.CalledProcessError): installer.main()
                    self.assertEqual(site.read_text(), original)
                    self.assertFalse(http.exists()); self.assertFalse(locations.exists()); self.assertFalse(state.exists())
                    self.assertFalse(any(p.exists() for p in (root / 'units').glob('*')))
                    self.assertEqual(len(installer.read_environment(env.read_text())['MASTER_KEY']), 64)
                    self.assertFalse(any(c[:2] == ('systemctl', 'start') for c in calls))
                else:
                    installer.main()
                    if plan:
                        self.assertEqual(site.read_text(), original)
                        self.assertFalse(env.exists()); self.assertFalse((root / 'backups').exists())
                        self.assertFalse(any(c[0] in ('apt-get', 'systemctl', 'sh') for c in calls))
                    else:
                        self.assertTrue(state.exists()); self.assertIn(str(locations), site.read_text())
                        self.assertIn('Environment=XPN_HOST_TCP_PORTS=85,443', (root / 'units/xpn-network.service').read_text())
                        self.assertEqual(env.stat().st_mode & 0o777, 0o600)
                        self.assertIn(('systemctl', 'enable', *installer.UNITS), calls)
                        secret = installer.read_environment(env.read_text())['ADMIN_TOKEN']
                        self.assertNotIn(secret, next((root / 'backups').glob('*/actions.log')).read_text())
                        if repeat == 'migrate':
                            running = True
                            old_secret = env.read_bytes()
                            installed = root / 'package'
                            shutil.copytree(source, installed)
                            calls.clear()
                            argv.append('--migrate-checkout')
                            with patch.object(installer, 'PACKAGED', True), patch.object(installer, 'SOURCE', installed), patch.object(installer, 'PACKAGE_BINARY', binary):
                                installer.main()
                                self.assertEqual(env.read_bytes(), old_secret)
                                self.assertTrue(all(not (root / 'units' / (u + '.service')).exists() for u in installer.UNITS))
                                self.assertTrue((root / 'units/xpn-native.service.d/xpn.conf').exists())
                                self.assertIn(('systemctl', 'reenable', *installer.UNITS), calls)
                                self.assertFalse(any(c[0] in ('cmake', 'npm', 'apt-get') for c in calls))
                                calls.clear()
                                installer.main()
                                self.assertFalse(any(c[:2] in [('systemctl', a) for a in ('stop', 'start', 'reload', 'reenable', 'daemon-reload')] for c in calls))
                            return
                        if repeat:
                            argv.remove('--host-tcp-ports'); argv.remove('85,443')
                            running = True
                            calls.clear()
                            files = [env, state, http, locations, site, *units(source, source / 'build/tools/node/bin/node', 3301, '/xpn')]
                            before = {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in files}
                            if repeat == 'repair': locations.unlink()
                            if repeat == 'permissions':
                                locations.chmod(0o600)
                                (root / 'units/xpn-control.service').chmod(0o600)
                            if repeat == 'control': (source / 'server/main.mjs').write_text('// changed source')
                            if repeat == 'host-ports': argv.extend(['--host-tcp-ports', '85,443,5201'])
                            if repeat == 'health-failure':
                                opener.open.return_value.__enter__.return_value.status = 503
                                with self.assertRaisesRegex(ValueError, 'health check'): installer.main()
                            else: installer.main()
                            mutations = [c for c in calls if c[0] in ('npm', 'cmake', 'ctest', 'apt-get', 'sh') or c[:2] in
                                         [('systemctl', a) for a in ('start', 'stop', 'restart', 'reload', 'daemon-reload', 'enable', 'disable')]]
                            if repeat in ('noop', 'health-failure', 'permissions'):
                                self.assertEqual(mutations, [])
                                self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in files})
                                reports = sorted((root / 'backups').glob('*/changes.md'))
                                if repeat == 'permissions':
                                    self.assertEqual(locations.stat().st_mode & 0o777, 0o644)
                                    self.assertEqual((root / 'units/xpn-control.service').stat().st_mode & 0o777, 0o644)
                                    self.assertIn('Corrected permissions', reports[-1].read_text())
                                else: self.assertIn('No installation changes.', reports[-1].read_text())
                            elif repeat == 'repair':
                                self.assertEqual(mutations, [('systemctl', 'reload', 'nginx')])
                                self.assertEqual(locations.read_bytes(), before[locations][0])
                                for p in files:
                                    if p != locations: self.assertEqual(p.stat().st_mtime_ns, before[p][1])
                            elif repeat == 'control':
                                self.assertEqual(mutations, [('systemctl', 'stop', 'xpn-native', 'xpn-control'),
                                                             ('systemctl', 'start', 'xpn-control', 'xpn-native')])
                            elif repeat == 'host-ports':
                                self.assertEqual(mutations, [('systemctl', 'stop', 'xpn-native', 'xpn-gateway', 'xpn-network'),
                                                             ('systemctl', 'daemon-reload'),
                                                             ('systemctl', 'start', 'xpn-network', 'xpn-gateway', 'xpn-native')])
                                self.assertIn('Environment=XPN_HOST_TCP_PORTS=85,443,5201', (root / 'units/xpn-network.service').read_text())
                                self.assertEqual(env.read_bytes(), before[env][0])

    def test_migration_preserves_secrets_retargets_boot_links_and_reruns_cleanly(self): self.simulate_install(repeat='migrate')

    def test_complete_install_orchestration(self): self.simulate_install()

    def test_second_run_changes_no_files_services_or_builds(self): self.simulate_install(repeat='noop', build=True)

    def test_missing_nginx_include_repairs_only_that_file_and_reloads(self): self.simulate_install(repeat='repair', build=True)

    def test_control_change_restarts_control_and_dependent_not_network(self): self.simulate_install(repeat='control', build=True)

    def test_host_port_change_restarts_network_and_native_only(self): self.simulate_install(repeat='host-ports', build=True)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux socket restart semantics')
    def test_port_probe_accepts_time_wait_but_rejects_live_listener(self):
        with socket.socket() as listener, socket.socket() as client:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', 0)); listener.listen(1)
            address = listener.getsockname()
            with self.assertRaises(OSError) as busy:
                installer.check_port_available(address[1])
            self.assertEqual(busy.exception.errno, errno.EADDRINUSE)
            client.settimeout(2); client.connect(address)
            peer, _ = listener.accept()
            peer.close()
            self.assertEqual(client.recv(1), b'')
        # Reproduce the old false conflict, then verify the real restart probe.
        with socket.socket() as old_probe:
            with self.assertRaises(OSError) as stale:
                old_probe.bind(address)
            self.assertEqual(stale.exception.errno, errno.EADDRINUSE)
        installer.check_port_available(address[1])

    def test_noop_health_failure_does_not_stop_healthy_services(self): self.simulate_install(repeat='health-failure', build=True)

    def test_permission_repairs_do_not_reload_or_restart(self): self.simulate_install(repeat='permissions', build=True)

    def test_https_check_waits_for_reload_and_fails_if_never_ready(self):
        changes = MagicMock()
        failed = subprocess.CompletedProcess([], 22)
        changes.run.side_effect = [failed, subprocess.CompletedProcess([], 0)]
        with patch.object(installer.time, 'sleep') as sleep:
            installer.check_https(changes, 'vpn.example.com', 'https://vpn.example.com/xpn')
            self.assertEqual(changes.run.call_count, 2)
            sleep.assert_called_once_with(1)
            changes.run.side_effect = None
            changes.run.return_value = failed
            with self.assertRaises(subprocess.CalledProcessError):
                installer.check_https(changes, 'vpn.example.com', 'https://vpn.example.com/xpn')


    def test_nginx_validation_failure_restores_config_before_start(self): self.simulate_install(failure=True)

    def test_plan_has_no_mutations(self): self.simulate_install(plan=True)

    def test_nginx_insertion_keeps_other_locations_and_quotes(self):
        original = '''# comment { ignored }
server { listen 80; server_name vpn.example.com; }
server {
 listen 443 ssl default_server; server_name vpn.example.com;
 ssl_certificate "/etc/ssl/cert.pem";
 location /existing { return 200 "text with } and #"; }
}
'''
        server = installer.blocks(original)[1]
        result = installer.integrate_site(original, server, '/xpn')
        self.assertIn('location /existing { return 200 "text with } and #"; }', result)
        self.assertEqual(result.count('include /etc/nginx/snippets/xpn-locations.conf;'), 1)
        self.assertEqual(installer.integrate_site(result, installer.blocks(result)[1], '/xpn'), result)

    def test_nginx_existing_vpn_location_is_not_overwritten(self):
        original = 'server { listen 443 ssl; location ^~ /xpn/ { proxy_pass http://other; } }'
        with self.assertRaisesRegex(ValueError, 'Existing /xpn'):
            installer.integrate_site(original, installer.blocks(original)[0], '/xpn')

    def test_site_selection_uses_exact_name_and_rejects_ambiguity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'site'
            path.write_text('server { listen 443 ssl; server_name vpn.example.com; }\n'
                            'server { listen 443 ssl default_server; server_name _; }')
            _, _, block = installer.select_site('vpn.example.com', path)
            self.assertIn(['server_name', 'vpn.example.com'], block['directives'])
            path.write_text(path.read_text() + '\nserver { listen 443 ssl; server_name vpn.example.com; }')
            with self.assertRaisesRegex(ValueError, 'Cannot choose'):
                installer.select_site('vpn.example.com', path)

    def test_keys_are_independent_and_rerun_preserves_all_settings(self):
        text = installer.environment('https://vpn.example.com/xpn', 3300, 'a' * 64)
        values = installer.read_environment(text)
        self.assertEqual(len(values['MASTER_KEY']), 64)
        self.assertEqual(len(values['ADMIN_TOKEN']), 64)
        self.assertNotEqual(values['MASTER_KEY'], values['ADMIN_TOKEN'])
        text += 'SMTP_FROM="XPN <vpn@example.com>"\n# keep operator settings\n'
        self.assertEqual(installer.environment('https://vpn.example.com/xpn', 3300, 'b' * 64, text), text)
        with self.assertRaisesRegex(ValueError, 'PUBLIC_URL/PORT'):
            installer.environment('https://other.example.com/xpn', 3300, 'a' * 64, text)
        with self.assertRaisesRegex(ValueError, 'refusing to replace credentials'):
            installer.environment('https://vpn.example.com/xpn', 3300, 'a' * 64, text.replace(values['MASTER_KEY'], 'bad'))

    def test_units_use_checkout_and_one_unprivileged_identity(self):
        files = installer.unit_files(ROOT, ROOT / 'build/tools/node/bin/node', 3301, '/vpn-team')
        native = files[Path('/etc/systemd/system/xpn-native.service')]
        control = files[Path('/etc/systemd/system/xpn-control.service')]
        for unit in (native, control):
            self.assertIn('User=xpn\nGroup=xpn', unit)
            self.assertIn('ProtectHome=yes', unit)
            self.assertIn(f'BindReadOnlyPaths={ROOT}:/run/xpn-source', unit)
            self.assertIn('CapabilityBoundingSet=\n', unit)
            self.assertNotIn('/opt/xpn', unit)
        self.assertIn('/run/xpn-source/build/native/xpnd server 3301', native)
        self.assertIn('/vpn-team/vpn', native)
        self.assertIn('/run/xpn-source/build/tools/node/bin/node', control)

    def test_packaged_units_use_vendor_binary_and_only_scoped_overrides(self):
        units = installer.package_unit_files(3301, '/team', '5201,85,443')
        self.assertEqual(len(units), 2)
        native = units[installer.UNIT_DIR / 'xpn-native.service.d/xpn.conf']
        self.assertIn('ExecStart=\nExecStart=/usr/lib/xpn/server/xpnd server 3301', native)
        self.assertIn('/team/vpn xpn0 --loopback', native)
        self.assertNotIn('BindReadOnlyPaths', native)
        self.assertIn('XPN_HOST_TCP_PORTS=85,443,5201', units[installer.UNIT_DIR / 'xpn-network.service.d/xpn.conf'])
        self.assertEqual({installer.unit_name(p) for p in units}, {'xpn-native', 'xpn-network'})

    def test_checkout_unit_removal_is_recoverable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); unit = root / 'xpn-control.service'
            original = b'original checkout unit\n'
            unit.write_bytes(original); unit.chmod(0o640)
            changes = installer.Changes(root / 'backup')
            self.assertTrue(changes.remove(unit, 'checkout migration'))
            self.assertFalse(unit.exists())
            changes.rollback()
            self.assertEqual(unit.read_bytes(), original)
            self.assertEqual(unit.stat().st_mode & 0o777, 0o640)

    def test_rollback_restores_original_bytes_modes_and_keeps_new_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site, generated, secret = root / 'site', root / 'unit', root / 'env'
            site.write_text('original\n'); site.chmod(0o640)
            changes = installer.Changes(root / 'backup')
            changes.write(site, 'modified\n')
            changes.write(generated, 'unit\n')
            changes.write(secret, 'new credentials\n', 0o600)
            changes.rollback(preserve={secret})
            self.assertEqual(site.read_text(), 'original\n')
            self.assertEqual(site.stat().st_mode & 0o777, 0o640)
            self.assertFalse(generated.exists())
            self.assertEqual(secret.read_text(), 'new credentials\n')
            self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / 'backup').stat().st_mode & 0o777, 0o700)
            self.assertNotIn('new credentials', changes.logfile.read_text())

    def test_config_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / 'target'; target.write_text('keep')
            link = root / 'link'; link.symlink_to(target)
            changes = installer.Changes(root / 'backup')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                changes.write(link, 'replace')
            self.assertEqual(target.read_text(), 'keep')

    def test_unchanged_file_keeps_inode_and_mtime_and_mode_fix_keeps_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / 'env'
            path.write_text('private settings\n'); path.chmod(0o600)
            original = path.stat()
            changes = installer.Changes(root / 'backup')
            self.assertFalse(changes.write(path, path.read_text(), 0o600))
            self.assertEqual(changes.before, {})
            self.assertEqual(changes.entries, [])
            self.assertEqual(path.stat().st_ino, original.st_ino)
            self.assertEqual(path.stat().st_mtime_ns, original.st_mtime_ns)
            path.chmod(0o644)
            self.assertTrue(changes.write(path, path.read_text(), 0o600, 'private credentials'))
            self.assertEqual(path.stat().st_ino, original.st_ino)
            self.assertEqual(path.stat().st_mtime_ns, original.st_mtime_ns)
            self.assertIn('Corrected permissions 0644 → 0600', changes.report.read_text())
            self.assertNotIn('private settings', changes.report.read_text())
            changes.rollback()
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_invalid_url_and_source_path_cannot_inject_configuration(self):
        for url in ['http://vpn.example.com/xpn', 'https://user:pass@vpn.example.com/xpn',
                    'https://vpn.example.com/xpn;evil', 'https://vpn.example.com/xpn?secret=a',
                    'https://vpn.example.com:8443/xpn', 'https://vpn.example.com/']:
            with self.assertRaises(ValueError): installer.public_url(url)
        with self.assertRaises(ValueError): installer.safe_path('/root/repo/bad%path')

    def test_host_port_arguments_are_validated_and_normalized(self):
        import argparse
        self.assertEqual(installer.host_tcp_ports('443,85,443'), '85,443')
        for value in ('0', '65536', '443;accept', '85,,443', '85,', ''):
            with self.assertRaises(argparse.ArgumentTypeError): installer.host_tcp_ports(value)


if __name__ == '__main__': unittest.main()
