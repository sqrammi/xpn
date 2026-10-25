import test from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { Store } from './store.mjs';
import { createApp, createInternal } from './app.mjs';

test('API authenticates admins, handles subpaths, sends QR email, and revokes', async () => {
  const store = new Store(':memory:', randomBytes(32).toString('hex'), 'https://vpn.test/xpn');
  const messages = [], app = createApp({ store, adminToken: 'a'.repeat(40), publicURL: 'https://vpn.test/xpn', mailer: { sendMail: async value => messages.push(value) } });
  await new Promise(resolve => app.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${app.address().port}/xpn`;
  const request = (path, value, headers = {}) => fetch(base + path, { method: value ? 'POST' : 'GET', headers: { Authorization: 'Bearer ' + 'a'.repeat(40), 'Content-Type': 'application/json', ...headers }, body: value ? JSON.stringify(value) : undefined });
  try {
    assert.equal((await request('/api/users', undefined, { Authorization: 'wrong' })).status, 401);
    assert.equal((await request('/api/users', undefined, { Origin: 'https://evil.test' })).status, 403);
    let response = await request('/'); assert.equal(response.status, 200); assert.ok((await response.text()).includes('XPN'));
    response = await request('/api/users', { name: '<script>x</script>', email: 'alice@example.test' });
    assert.equal(response.status, 201); const created = await response.json();
    assert.ok(created.invitation.qr.startsWith('data:image/png;base64,'));
    assert.equal((await request('/api/users/' + created.user.id + '/email', {})).status, 200);
    assert.equal(messages.length, 1); assert.equal(messages[0].to, 'alice@example.test');
    assert.ok(messages[0].attachments[0].content.length > 100);
    response = await request('/api/users/' + created.user.id + '/invite', {});
    const invitation = (await response.json()).invitation;
    const token = new URLSearchParams(new URL(invitation.uri).hash.slice(1)).get('token');
    response = await request('/api/enroll', { token }, { Authorization: '' }); assert.equal(response.status, 200);
    assert.ok((await response.json()).ciphertext);
    assert.equal((await request('/api/enroll', { token })).status, 410);
    response = await request('/api/users/' + created.user.id + '/rotate', {});
    assert.equal(response.status, 201); assert.ok((await response.json()).invitation.qr);
    assert.equal((await request('/api/users/' + created.user.id + '/revoke', {})).status, 200);
    assert.equal((await request('/api/users/' + created.user.id + '/invite', {})).status, 400);
    assert.equal((await request('/api/users', { name: 'x', routes: ['garbage'] })).status, 400);
  } finally { app.closeAllConnections(); await new Promise(resolve => app.close(resolve)); store.close(); }
});
test('internal snapshot contains active credentials only', async () => {
  const store = new Store(':memory:', randomBytes(32).toString('hex'), 'https://vpn.test');
  const a = store.create({ name: 'Alice' }), b = store.create({ name: 'Bob' }); store.revoke(a.user.id);
  const app = createInternal(store); // Production binds this service exclusively to a protected Unix socket.
  await new Promise(resolve => app.listen(0, '127.0.0.1', resolve));
  try {
    const response = await fetch(`http://127.0.0.1:${app.address().port}/users`), users = await response.json();
    assert.equal(users.length, 1); assert.equal(users[0].id, b.user.id); assert.equal(Buffer.from(users[0].key, 'base64url').length, 32);
  } finally { app.closeAllConnections(); await new Promise(resolve => app.close(resolve)); store.close(); }
});
