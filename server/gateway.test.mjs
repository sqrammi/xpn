import test from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { Store } from './store.mjs';
import { createApp } from './app.mjs';
import { gatewayRequest, gatewayTargetsReady } from './gateway.mjs';
import net from 'node:net';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('gateway API authenticates, rejects cross-origin and unsuitable devices, passes revisions and reports helper failures', async () => {
  const store = new Store(':memory:', randomBytes(32).toString('hex'), 'https://vpn.test/xpn');
  const { user } = store.create({ name: 'full' });
  const calls = []; let fail = false;
  const policy = { enabled: true, interface: 'wg0', sources: ['172.9.0.0/16'], targets: [user.ip], tcpPorts: [22], udpPorts: [], allowPing: true };
  const app = createApp({ store, adminToken: 'a'.repeat(40), publicURL: 'https://vpn.test/xpn', gateway: async message => {
    calls.push(message); if (fail) throw new Error('private internals');
    return message.revision === 9 ? { error: 'Refresh first', status: 409 } : { policy, revision: 1, applied: true };
  }});
  await new Promise(r => app.listen(0, '127.0.0.1', r));
  const request = (data, extra = {}) => fetch(`http://127.0.0.1:${app.address().port}/xpn/api/gateway`, {
    method: data ? 'POST' : 'GET', headers: { Authorization: 'Bearer ' + 'a'.repeat(40), 'Content-Type': 'application/json', ...extra }, body: data && JSON.stringify(data)
  });
  try {
    assert.equal((await request(null, { Authorization: '' })).status, 401);
    assert.equal((await request({ policy }, { Origin: 'https://evil.test' })).status, 403);
    assert.equal(calls.length, 0);
    assert.equal((await request()).status, 200);
    assert.equal((await request({ revision: 0, policy })).status, 200);
    assert.deepEqual(calls.at(-1), { action: 'set', revision: 0, policy });
    assert.equal((await request({ revision: 9, policy })).status, 409);
    assert.equal((await request({ revision: 1, policy: { ...policy, targets: ['10.77.0.254'] } })).status, 400);
    store.revoke(user.id);
    assert.equal((await request({ revision: 1, policy })).status, 400);
    fail = true;
    const response = await request(); assert.equal(response.status, 503);
    assert.ok(!(await response.text()).includes('private internals'));
  } finally { app.closeAllConnections(); await new Promise(r => app.close(r)); store.close(); }
});

test('gateway reply policy needs the gateway route for split users', () => {
  const user = { ip: '10.77.0.2', policy: { fullTunnel: false, routes: ['192.168.0.0/16'] } };
  assert.equal(gatewayTargetsReady([user], [user.ip]), false);
  user.policy.routes.push('10.77.0.1/32'); assert.equal(gatewayTargetsReady([user], [user.ip]), true);
});

test('gateway Unix client handles a split response and disconnect', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'xpn-gw-')); const path = join(directory, 's');
  const server = net.createServer(socket => socket.on('data', () => { socket.write('{"revision":'); socket.end('3}\n'); }));
  await new Promise(r => server.listen(path, r));
  try { assert.deepEqual(await gatewayRequest({ action: 'get' }, path), { revision: 3 }); }
  finally { await new Promise(r => server.close(r)); await rm(directory, { recursive: true }); }
  await assert.rejects(gatewayRequest({ action: 'get' }, path), /unavailable/);
});
