"""Direct Linux client retries: harmless fake native process and mocked network tools."""
import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'clients/linux/xpn.py'
spec = importlib.util.spec_from_file_location('xpn_client', SOURCE)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class BackoffTests(unittest.TestCase):
    def test_growth_cap_and_stable_reset(self):
        windows = []
        with patch.object(client.RNG, 'uniform', side_effect=lambda a, b: windows.append((a, b)) or a):
            backoff = client.Backoff()
            for _ in range(9): backoff.next()
            self.assertEqual(windows[:7], [(5, 10), (10, 20), (20, 40), (40, 80), (80, 160), (150, 300), (150, 300)])
            backoff.next(119)
            self.assertEqual(windows[-1], (150, 300))
            backoff.next(120)
            self.assertEqual(windows[-1], (5, 10))

    def test_jitter_varies_and_stays_bounded(self):
        values = [client.Backoff().next() for _ in range(30)]
        self.assertTrue(all(5 <= value <= 10 for value in values))
        self.assertGreater(len(set(values)), 1)


class RetryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.native = self.root / 'native.py'
        self.native.write_text('#!/usr/bin/env python3\nprint("CONNECTED",flush=True)\n')
        self.native.chmod(0o700)
        self.profile = {'fullTunnel': False, 'endpoint': 'wss://vpn.example.test/xpn/vpn',
                        'address': '10.77.0.2', 'routes': ['192.0.2.0/24'], 'dns': ['1.1.1.1'], 'mode': 'psk'}
        config = self.root / 'profile.json'; config.write_text(json.dumps(self.profile))
        self.args = argparse.Namespace(profile=config, native=str(self.native), no_retry=False,
                                       retry_initial=10, retry_max=300, stable_seconds=120,
                                       single_stream=False, inner_encryption=None, require_pq=False)
        self.stack = contextlib.ExitStack(); self.addCleanup(self.stack.close)
        self.commands = []
        def command(*args, **kwargs):
            self.commands.append(args)
            return subprocess.CompletedProcess(args, 0, '[]', '')
        self.stack.enter_context(patch.object(client, 'run', side_effect=command))
        def cleanup(command, **kwargs):
            self.commands.append(tuple(command))
            return subprocess.CompletedProcess(command, 0, '', '')
        self.cleanup = self.stack.enter_context(patch.object(client.subprocess, 'run', side_effect=cleanup))
        self.dns = self.stack.enter_context(patch.object(client.socket, 'getaddrinfo', return_value=[(0, 0, 0, '', ('203.0.113.1', 443))]))
        self.output = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))
        self.stack.enter_context(contextlib.redirect_stderr(self.output))

    def run_until_backoff(self, retries):
        waits = []
        def sleep(delay):
            waits.append(delay)
            if len(waits) > retries: raise KeyboardInterrupt()
        with patch.object(client, 'pause', side_effect=sleep), patch.object(client.RNG, 'uniform', side_effect=lambda a,b:b):
            with self.assertRaises(KeyboardInterrupt): client.connect(self.args)
        return waits

    def test_direct_client_retries_exit_zero_and_cleans_each_attempt(self):
        self.assertEqual(self.run_until_backoff(2), [5, 10, 20])
        self.assertEqual(self.output.getvalue().count('Connection attempt'), 2)
        self.assertEqual(self.output.getvalue().count('Connected.'), 2)
        self.assertEqual(self.dns.call_count, 2)
        adds = [i for i, c in enumerate(self.commands) if c[:3] == ('ip', 'tuntap', 'add')]
        removes = [i for i, c in enumerate(self.commands) if c[:3] == ('ip', 'link', 'delete')]
        self.assertLess(removes[0], adds[1])
        self.assertGreater(removes[1], adds[1])

    def test_dns_failure_is_retried_and_resolved_again(self):
        self.dns.side_effect = [socket.gaierror('offline'), [(0, 0, 0, '', ('203.0.113.1', 443))]]
        self.assertEqual(self.run_until_backoff(2), [5, 10, 20])
        self.assertEqual(self.output.getvalue().count('Connected.'), 1)

    def test_terminal_native_message_stops_stuck_process(self):
        marker = self.root / 'native.pid'
        self.native.write_text('#!/usr/bin/env python3\nimport os,time\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').write_text(str(os.getpid()))\nprint("CONNECTED",flush=True)\nprint("Both VPN connections unavailable; reconnect",flush=True)\ntime.sleep(60)\n')
        self.run_until_backoff(1)
        with self.assertRaises(ProcessLookupError): os.kill(int(marker.read_text()), 0)
        self.assertIn('requests reconnection', self.output.getvalue())

    def test_no_retry_skips_startup_delay_and_attempts_once(self):
        self.args.no_retry = True
        with patch.object(client, 'pause') as pause:
            with self.assertRaisesRegex(RuntimeError, 'Native tunnel closed'): client.connect(self.args)
        pause.assert_not_called()
        self.assertEqual(self.output.getvalue().count('Connection attempt'), 1)

    def test_invalid_profile_does_not_retry(self):
        self.args.profile.write_text('{}')
        with patch.object(client, 'pause') as pause:
            with self.assertRaises(ValueError): client.connect(self.args)
        pause.assert_not_called()
        self.assertFalse(self.commands)

    def test_failed_network_cleanup_stops_retries(self):
        self.cleanup.side_effect = lambda command, **kwargs: subprocess.CompletedProcess(command, 1)
        with patch.object(client, 'pause'):
            with self.assertRaises(client.CleanupError): client.connect(self.args)
        self.assertEqual(self.output.getvalue().count('Connection attempt'), 1)

    def test_sigterm_during_connection_cleans_up_without_retry(self):
        def monitor(proc, authenticated):
            authenticated()
            os.kill(os.getpid(), signal.SIGTERM)
        with patch.object(client, 'pause'), patch.object(client, 'monitor_native', side_effect=monitor):
            with self.assertRaises(KeyboardInterrupt): client.connect(self.args)
        self.assertTrue(any(c[:3] == ('ip', 'link', 'delete') for c in self.commands))
        self.assertNotIn('retrying in', self.output.getvalue())

    def test_partial_native_line_cannot_block_authentication_timeout(self):
        self.native.write_text('#!/usr/bin/env python3\nimport sys,time\nsys.stdout.write("CONNE");sys.stdout.flush();time.sleep(60)\n')
        proc = subprocess.Popen([str(self.native)], stdout=subprocess.PIPE)
        try:
            with self.assertRaisesRegex(RuntimeError, 'did not authenticate'):
                client.monitor_native(proc, lambda: self.fail('Incomplete handshake'), timeout=.1)
        finally:
            proc.terminate(); proc.wait(timeout=5); proc.stdout.close()

    def test_stop_during_cleanup_is_honored_after_all_removals(self):
        removed = []
        def cleanup(command, **kwargs):
            removed.append(tuple(command))
            os.kill(os.getpid(), signal.SIGTERM)
            return subprocess.CompletedProcess(command, 0)
        self.cleanup.side_effect = cleanup
        with patch.object(client, 'pause'):
            with self.assertRaises(KeyboardInterrupt): client.connect(self.args)
        self.assertTrue(any(c[:3] == ('ip', 'route', 'del') for c in removed))
        self.assertTrue(any(c[:3] == ('ip', 'link', 'delete') for c in removed))
        self.assertNotIn('retrying in', self.output.getvalue())


if __name__ == '__main__':
    unittest.main()
