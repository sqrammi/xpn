"""Exercise root network lifecycle with fake commands; never touch host networking."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'deploy/network.sh'


class NetworkLifecycle(unittest.TestCase):
    def invoke(self, action, present, ports='22,443'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stub = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
name=Path(sys.argv[0]).name
args=sys.argv[1:]
body=sys.stdin.read() if name=='nft' and args==['-f','-'] else ''
with open(os.environ['XPN_TEST_LOG'],'a') as log:
    log.write(json.dumps([name,args,body])+'\\n')
if (name=='nft' and args[:2]==['list','table']) or (name=='ip' and args[:2]==['link','show']):
    sys.exit(0 if os.environ['XPN_TEST_PRESENT']=='1' else 1)
'''
            for command in ['ip', 'nft', 'sysctl', 'id']:
                path = root / command
                path.write_text(stub)
                path.chmod(0o755)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                       XPN_TEST_LOG=str(root / 'log'), XPN_TEST_PRESENT=str(int(present)), XPN_WAN_IFACE='eth0', XPN_HOST_TCP_PORTS=ports)
            result = subprocess.run(['sh', str(SCRIPT), action], env=env, capture_output=True, text=True)
            import json
            log = [json.loads(line) for line in (root / 'log').read_text().splitlines()] if (root / 'log').exists() else []
            return result, log

    def test_stop_removes_only_owned_resources(self):
        result, log = self.invoke('stop', True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([(cmd, args) for cmd, args, _ in log], [
            ('nft', ['list', 'table', 'inet', 'xpn']), ('nft', ['delete', 'table', 'inet', 'xpn']),
            ('ip', ['link', 'show', 'xpn0']), ('ip', ['link', 'delete', 'xpn0'])])

    def test_stop_is_idempotent(self):
        result, log = self.invoke('stop', False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(log), 2)
        self.assertTrue(all('delete' not in args for _, args, _ in log))

    def test_start_owns_tun_and_replaces_only_its_table(self):
        result, log = self.invoke('start', True)
        self.assertEqual(result.returncode, 0, result.stderr)
        rules = next(body for cmd, args, body in log if cmd == 'nft' and args == ['-f', '-'])
        self.assertIn('delete table inet xpn', rules)
        self.assertIn('table inet xpn', rules)
        self.assertNotIn('flush ruleset', rules)
        self.assertIn('tcp dport { 22,443 } accept', rules)
        self.assertIn('icmp type echo-request limit rate', rules)
        self.assertIn('ip daddr { 127.0.0.0/8, 169.254.0.0/16 } drop', rules)
        self.assertLess(rules.index('tcp dport'), rules.index('iifname "xpn0" drop'))
        self.assertFalse(any(cmd == 'ip' and args[:2] == ['tuntap', 'add'] for cmd, args, _ in log))

    def test_unknown_action_changes_nothing(self):
        result, log = self.invoke('invalid', True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(log, [])

    def test_new_tun_is_owned_by_service_identity(self):
        result, log = self.invoke('start', False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(('ip', ['tuntap', 'add', 'dev', 'xpn0', 'mode', 'tun', 'user', 'xpn']),
                      [(cmd, args) for cmd, args, _ in log])

    def test_custom_host_ports_and_invalid_values(self):
        result, log = self.invoke('start', True, '85,443')
        self.assertEqual(result.returncode, 0)
        rules = next(body for cmd, args, body in log if cmd == 'nft' and args == ['-f', '-'])
        self.assertIn('tcp dport { 85,443 } accept', rules)
        for ports in ('443; flush ruleset', '0', '65536', '85,,443', '85,'):
            result, log = self.invoke('start', True, ports)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(log, [])


if __name__ == '__main__':
    unittest.main()
