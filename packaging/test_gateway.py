"""Gateway validation, least-privilege rule scope, persistence and failure handling."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gateway', ROOT / 'deploy/gateway.py')
gw = importlib.util.module_from_spec(spec); spec.loader.exec_module(gw)


def enabled():
    return dict(enabled=True, interface='wg0', sources=['172.9.0.0/16'], targets=['10.77.0.2'], tcpPorts=[22, 443], udpPorts=[53], allowPing=True)


class GatewayTests(unittest.TestCase):
    def test_client_ping_independent_opt_in_and_strict_pool_scope(self):
        self.assertFalse(gw.policy(enabled())['allowClientPing'])
        p = {**gw.DEFAULT, 'allowClientPing': True}
        rules = gw.rules(p)
        self.assertIn('iifname "xpn0" oifname "xpn0" ip saddr 10.77.0.2-10.77.0.254 ip daddr 10.77.0.2-10.77.0.254 icmp type echo-request', rules)
        self.assertIn('icmp type echo-reply ct state established accept', rules)
        self.assertNotIn('snat ip to', rules)
        self.assertNotIn('tcp', rules)
        self.assertNotIn('wg0', rules)
        with self.assertRaises(gw.PolicyError): gw.policy({**p, 'allowClientPing': 'yes'})

    def test_firewall_mode_uses_all_sources_services_without_wireguard(self):
        p = {**gw.DEFAULT, 'enabled': True}
        clean = gw.policy(p)
        self.assertTrue(clean['allDevices'])
        text = gw.rules(p)
        self.assertIn('ct direction original ct state new,established,related accept', text)
        self.assertIn('ct direction reply ct status snat ct state established,related accept', text)
        self.assertIn('snat ip to 10.77.0.1', text)
        self.assertNotIn('wg0', text)
        self.assertNotIn('dport', text)
        self.assertNotIn('flush ruleset', text)
        self.assertEqual(gw.policy(enabled())['filterMode'], 'restricted')
        with tempfile.TemporaryDirectory() as d:
            service = gw.Gateway(Path(d)/'policy.json', lambda _: None,
                                 lambda _: self.fail('Firewall mode must not require WireGuard'))
            service.request(dict(action='set', revision=0, policy=p))
        disabled = gw.rules({**p, 'enabled': False})
        self.assertNotIn(' accept', disabled)
        self.assertIn('ct direction original drop', disabled)
        self.assertIn('ct direction reply ct status snat drop', disabled)
        with self.assertRaises(gw.PolicyError): gw.policy({**p, 'filterMode': 'anything'})

    def test_all_devices_is_opt_in_covers_only_client_pool_and_accepts_legacy_policy(self):
        self.assertFalse(gw.policy(enabled())['allDevices'])
        p = {**enabled(), 'allDevices': True, 'targets': []}
        self.assertEqual(gw.policy(p)['targets'], [])
        self.assertIn('ip daddr { 10.77.0.2-10.77.0.254 }', gw.rules(p))
        self.assertIn('ip saddr { 10.77.0.2-10.77.0.254 }', gw.rules(p))
        with self.assertRaises(gw.PolicyError): gw.policy({**p, 'allDevices': 'yes'})

    def test_validation_rejects_injection_and_overbroad_access(self):
        for key, value in [('interface', 'wg0; flush ruleset'), ('interface', 'xpn0'),
                           ('sources', ['0.0.0.0/0']), ('sources', ['10.77.0.0/16']),
                           ('sources', ['127.0.0.1/32']), ('targets', ['10.77.0.1']),
                           ('targets', ['8.8.8.8']), ('tcpPorts', [True]), ('udpPorts', [65536]),
                           ('enabled', 'yes'), ('allowPing', 1)]:
            p = enabled(); p[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(gw.PolicyError): gw.policy(p)
        p = enabled(); p['extra'] = 'command'
        with self.assertRaises(gw.PolicyError): gw.policy(p)

    def test_policy_normalization_and_disabled_defaults(self):
        p = enabled(); p['sources'] = ['172.9.0.7/16']; p['tcpPorts'] = [443, 22, 443]
        normalized = gw.policy(p)
        self.assertEqual(normalized['sources'], ['172.9.0.0/16'])
        self.assertEqual(normalized['tcpPorts'], [22, 443])
        self.assertFalse(gw.policy(gw.DEFAULT)['enabled'])

    def test_rules_scope_and_stateful_return_path(self):
        rules = gw.rules(enabled())
        self.assertEqual(rules.count('flush chain'), 2)
        self.assertNotIn('flush ruleset', rules)
        self.assertNotIn('delete table', rules)
        self.assertIn('tcp sport { 22, 443 } ct state established accept', rules)
        self.assertIn('tcp dport { 22, 443 } ct state new,established accept', rules)
        self.assertIn('snat ip to 10.77.0.1', rules)
        self.assertIn('ip saddr { 172.9.0.0/16 } ip daddr { 10.77.0.2 }', rules)
        self.assertNotIn('accept', gw.rules(gw.DEFAULT))

    def test_apply_is_one_bounded_nft_transaction(self):
        with patch.object(gw.subprocess, 'run') as run:
            gw.apply(enabled())
        self.assertEqual(run.call_count, 1)
        args, kw = run.call_args
        self.assertEqual(args[0], ['/usr/sbin/nft', '-f', '-'])
        self.assertEqual(kw['input'], gw.rules(enabled()))
        self.assertNotIn('shell', kw)

    def test_persistence_noop_restart_and_stale_revision(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'policy.json'; calls = []
            service = gw.Gateway(path, calls.append, lambda _: None)
            request = dict(action='set', revision=0, policy=enabled())
            result = service.request(request)
            self.assertEqual(result['revision'], 1)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(service.request(request)['status'], 409)
            service.request({**request, 'revision': 1})
            self.assertEqual(len(calls), 2)  # initial deny + one policy change
            restored = gw.Gateway(path, calls.append, lambda _: self.fail('Boot must not depend on link readiness'))
            self.assertEqual(restored.request({'action': 'get'}), result)
            disabled = {**enabled(), 'enabled': False}
            restored.request(dict(action='set', revision=1, policy=disabled))
            self.assertFalse(json.loads(path.read_text())['policy']['enabled'])

    def test_nft_failure_does_not_save_or_advance_revision(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'policy.json'
            service = gw.Gateway(path, lambda _: None, lambda _: None)
            service.apply = lambda _: (_ for _ in ()).throw(subprocess.CalledProcessError(1, ['nft']))
            with self.assertRaises(subprocess.CalledProcessError): service.request(dict(action='set', revision=0, policy=enabled()))
            self.assertFalse(path.exists())
            self.assertEqual(service.value['revision'], 0)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_persistence_failure_restores_previous_rules(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'policy.json'; calls = []
            service = gw.Gateway(path, calls.append, lambda _: None)
            with patch.object(gw.os, 'replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): service.request(dict(action='set', revision=0, policy=enabled()))
            self.assertEqual(calls[-1], gw.DEFAULT)
            self.assertFalse(service.value['policy']['enabled'])
            self.assertFalse(path.exists())

    def test_enable_checks_wireguard_and_disable_can_recover_missing_link(self):
        with tempfile.TemporaryDirectory() as d:
            check = lambda _: (_ for _ in ()).throw(gw.PolicyError('not wireguard'))
            service = gw.Gateway(Path(d)/'policy.json', lambda _: None, check)
            with self.assertRaises(gw.PolicyError): service.request(dict(action='set', revision=0, policy=enabled()))
            service.request(dict(action='set', revision=0, policy={**enabled(), 'enabled': False}))

    def test_wrong_interface_type_is_rejected(self):
        with patch.object(gw.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '[{"linkinfo":{"info_kind":"veth"}}]')):
            with self.assertRaises(gw.PolicyError): gw.wireguard_interface('wg0')

    def test_default_route_wireguard_is_rejected(self):
        replies = [subprocess.CompletedProcess([], 0, '[{"linkinfo":{"info_kind":"wireguard"}}]'),
                   subprocess.CompletedProcess([], 0, '[{"dev":"wg0"}]')]
        with patch.object(gw.subprocess, 'run', side_effect=replies):
            with self.assertRaises(gw.PolicyError): gw.wireguard_interface('wg0')

    def test_socket_checks_peer_uid_before_reading(self):
        connection, manager = Mock(), Mock()
        connection.getsockopt.return_value = struct.pack('3i', 123, 1234, 5678)
        with patch.object(gw.socket, 'SO_PEERCRED', 17, create=True):
            gw.handle(connection, manager, 999)
        connection.recv.assert_not_called()
        manager.request.assert_not_called()

    def test_socket_valid_request_and_bounded_invalid_input(self):
        for payload, expected in [(b'{"action":"get"}\n', 200),
                                  (b'{}\n{}\n', 400), (b'x' * 8193, 400), (b'invalid\n', 400)]:
            with self.subTest(payload=payload[:20]):
                connection, manager = Mock(), Mock()
                connection.getsockopt.return_value = struct.pack('3i', 123, 999, 999)
                connection.recv.return_value = payload
                manager.request.return_value = {'policy': gw.DEFAULT, 'revision': 0, 'applied': True}
                with patch.object(gw.socket, 'SO_PEERCRED', 17, create=True):
                    gw.handle(connection, manager, 999)
                reply = json.loads(connection.sendall.call_args.args[0])
                self.assertEqual(reply.get('status', 200), expected)
                if expected == 400: manager.request.assert_not_called()


if __name__ == '__main__': unittest.main()
