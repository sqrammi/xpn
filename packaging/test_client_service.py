"""Service setup/retry regressions; mocked systemd never changes host networking."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'clients/linux/client-service.py'
spec = importlib.util.spec_from_file_location('client_service', SOURCE)
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


def profile():
    return {'version': 2, 'id': '00000000-0000-0000-0000-000000000001', 'key': 'A' * 43,
            'address': '10.77.0.2', 'endpoint': 'wss://vpn.example.test/xpn/vpn', 'mode': 'psk',
            'certificatePins': ['a' * 64], 'fullTunnel': False, 'routes': ['10.20.0.0/16'], 'dns': ['1.1.1.1']}


def arguments(path):
    return argparse.Namespace(profile=path, name='alta', no_start=False, xpn='/usr/bin/xpn',
                              native='/usr/lib/xpn/client/xpnd', inner_encryption=None,
                              require_pq=False, single_stream=False, retry_initial=10,
                              retry_max=300, stable_seconds=120)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / 'source.json'
        self.path.write_text(json.dumps(profile()))
        self.args = arguments(self.path)
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        for name, path in {'PROFILE_DIR': 'etc/xpn/clients', 'UNIT_DIR': 'etc/systemd/system',
                           'BACKUP_DIR': 'backups'}.items():
            self.patches.enter_context(patch.object(service, name, self.root / path))
        self.patches.enter_context(patch.object(service, 'ROOT_UID', os.getuid()))
        self.patches.enter_context(patch.object(service, 'executable', side_effect=Path))
        self.patches.enter_context(patch.object(service.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '--no-retry --retry-initial', '')))
        self.calls, self.active, self.enabled = [], False, False
        self.fail_start_once = False
        self.patches.enter_context(patch.object(service, 'ctl', side_effect=self.systemctl))
        self.patches.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def systemctl(self, *args, check=True):
        self.calls.append(args)
        if args[0] == 'is-active':
            code = 0 if self.active else 3
        elif args[0] == 'is-enabled':
            code = 0 if self.enabled else 1
        else:
            code = 0
            if args[0] == 'start':
                if self.fail_start_once:
                    self.fail_start_once = False
                    raise subprocess.CalledProcessError(1, ['systemctl', *args], stderr='test start failure')
                self.active = True
            if args[0] == 'stop': self.active = False
            if args[0] == 'enable': self.enabled = True
            if args[0] == 'disable': self.enabled = False
        return subprocess.CompletedProcess(args, code, '', '')

    def test_install_and_noop_do_not_restart(self):
        service.install(self.args)
        target = service.PROFILE_DIR / 'alta.json'
        self.assertEqual(target.read_bytes(), self.path.read_bytes())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o700)
        self.assertTrue(self.enabled and self.active)
        self.calls.clear()
        before = target.stat().st_mtime_ns
        service.install(self.args)
        self.assertEqual(self.calls, [('is-active', '--quiet', 'xpn-client-alta.service'),
                                     ('is-enabled', '--quiet', 'xpn-client-alta.service')])
        self.assertEqual(target.stat().st_mtime_ns, before)
        reports = [p.read_text() for p in service.BACKUP_DIR.glob('*/changes.md')]
        self.assertTrue(any('No changes' in text for text in reports))
        self.assertTrue(all(profile()['key'] not in text for text in reports))

    def test_update_restarts_and_preserves_backup(self):
        service.install(self.args)
        old = self.path.read_bytes()
        self.args.inner_encryption = 'off'
        p = profile(); p['routes'] = ['192.0.2.0/24']; self.path.write_text(json.dumps(p))
        self.calls.clear()
        service.install(self.args)
        actions = [call[0] for call in self.calls]
        self.assertLess(actions.index('stop'), actions.index('daemon-reload'))
        self.assertLess(actions.index('daemon-reload'), actions.index('start'))
        unit = (service.UNIT_DIR / 'xpn-client-alta.service').read_text()
        self.assertIn('"--inner-encryption" "off"', unit)
        backups = list(service.BACKUP_DIR.glob('**/alta.json'))
        self.assertTrue(any(p.read_bytes() == old for p in backups))

    def test_failure_restores_previous_profile_and_service(self):
        service.install(self.args)
        target = service.PROFILE_DIR / 'alta.json'
        old = target.read_bytes()
        p = profile(); p['routes'] = ['192.0.2.0/24']; self.path.write_text(json.dumps(p))
        self.fail_start_once = True
        with self.assertRaises(subprocess.CalledProcessError): service.install(self.args)
        self.assertEqual(target.read_bytes(), old)
        self.assertTrue(self.enabled and self.active)

    def test_no_start_and_unmanaged_units(self):
        self.args.no_start = True
        service.install(self.args)
        self.assertTrue(self.enabled)
        self.assertFalse(self.active)
        (service.UNIT_DIR / 'xpn-client-alta.service').write_text('[Service]\nExecStart=/bin/custom\n')
        self.calls.clear()
        with self.assertRaises(ValueError): service.install(self.args)
        self.assertEqual(self.calls, [])

    def test_symlink_destination_and_invalid_profile(self):
        service.PROFILE_DIR.mkdir(parents=True, mode=0o700)
        (service.PROFILE_DIR / 'alta.json').symlink_to(self.path)
        with self.assertRaises(ValueError): service.install(self.args)
        self.path.write_text('https://example.test/join#secret')
        with self.assertRaises(ValueError): service.install(self.args)
        self.assertEqual(self.calls, [])

    def test_old_client_refused_before_install(self):
        with patch.object(service.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'old help', '')):
            with self.assertRaisesRegex(ValueError, 'Upgrade the XPN client'):
                service.install(self.args)
        self.assertEqual(self.calls, [])
        self.assertFalse(service.PROFILE_DIR.exists())

    def test_systemd_escaping_and_restrictions(self):
        self.args.xpn = '/usr/local/bin/xpn%bad$name'
        unit = service.unit_text(self.args, service.PROFILE_DIR / 'alta.json')
        self.assertIn('xpn%%bad$$name', unit)
        self.assertIn('KillMode=mixed', unit)
        self.assertIn('\"connect\"', unit)
        self.assertNotIn('--run', unit)
        self.assertNotIn('client-service.py', next(line for line in unit.splitlines() if line.startswith('ExecStart=')))
        self.assertIn('RestartPreventExitStatus=1 78', unit)
        self.assertIn('NoNewPrivileges=yes', unit)


if __name__ == '__main__':
    unittest.main()
