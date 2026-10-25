import test from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { mkdtemp, stat, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import http from 'node:http';

test('production entry point creates a protected control socket and persistent database', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'xpn-test-'));
  const socket = join(directory, 'control.sock');
  const child = spawn(process.execPath, ['server/main.mjs'], {
    env: { ...process.env, PUBLIC_URL: 'https://vpn.test/xpn', MASTER_KEY: randomBytes(32).toString('hex'), ADMIN_TOKEN: randomBytes(32).toString('hex'), DATA_DIR: directory, CONTROL_SOCKET: socket, PORT: '0', SMTP_URL: '' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  try {
    await Promise.race([
      once(child.stdout, 'data'),
      once(child, 'exit').then(([code]) => { throw new Error(`Startup failed: ${code}`); }),
      new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error('Startup timeout')), 5000); timer.unref(); }),
    ]);
    assert.equal((await stat(socket)).mode & 0o777, 0o660);
    assert.equal((await stat(join(directory, 'xpn.db'))).mode & 0o777, 0o600);
    const snapshot = await new Promise((resolve, reject) => {
      http.get({ socketPath: socket, path: '/users' }, response => {
        let body = ''; response.setEncoding('utf8'); response.on('data', x => body += x); response.on('end', () => resolve(JSON.parse(body)));
      }).on('error', reject);
    });
    assert.deepEqual(snapshot, []);
  } finally {
    if (child.exitCode === null) { const closed = once(child, 'exit'); child.kill('SIGTERM'); await closed; }
    await rm(directory, { recursive: true, force: true });
  }
});
