import test from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { Store, unseal, policy } from './store.mjs';

const make = () => new Store(':memory:', randomBytes(32).toString('hex'), 'https://vpn.example.test/team/xpn');
test('individual keys, encrypted at rest and single-use encrypted enrollment', () => {
  const store = make();
  try {
    const a = store.create({ name: 'Alice' }), b = store.create({ name: 'Bob' });
    assert.notEqual(store.credential(a.user.id).key, store.credential(b.user.id).key);
    assert.equal(a.user.ip, '10.77.0.2'); assert.equal(b.user.ip, '10.77.0.3');
    const values = new URLSearchParams(new URL(a.invitation.uri).hash.slice(1));
    const cipher = store.redeem(values.get('token'));
    const profile = unseal(Buffer.from(values.get('key'), 'base64url'), cipher);
    assert.equal(profile.endpoint, 'wss://vpn.example.test/team/xpn/vpn');
    assert.equal(profile.mode, 'psk'); assert.equal(profile.id, a.user.id);
    assert.equal(store.redeem(values.get('token')), null);
    assert.throws(() => unseal(randomBytes(32), cipher));
    const raw = store.db.prepare('SELECT secret FROM users WHERE id=?').get(a.user.id).secret;
    assert.ok(!raw.includes(profile.key));
    assert.ok(!JSON.stringify(store.list()).includes(profile.key));
  } finally { store.close(); }
});
test('expiry, replacing an invitation, and revocation fail closed', () => {
  const store = make();
  try {
    const a = store.create({ name: 'Alice' });
    const token = uri => new URLSearchParams(new URL(uri).hash.slice(1)).get('token');
    const replaced = token(a.invitation.uri), fresh = token(store.invite(a.user.id).uri);
    assert.equal(store.redeem(replaced), null);
    store.db.prepare('UPDATE invites SET expires=?').run(Date.now() - 1000);
    assert.equal(store.redeem(fresh), null);
    const active = token(store.invite(a.user.id).uri);
    store.revoke(a.user.id);
    assert.equal(store.credential(a.user.id), null); assert.equal(store.redeem(active), null);
    assert.throws(() => store.invite(a.user.id));
    assert.equal(store.create({ name: 'Bob' }).user.ip, '10.77.0.3');
  } finally { store.close(); }
});
test('routing and crypto policies reject malformed or ambiguous settings', () => {
  for (const value of [{ mode: 'classical' }, { fullTunnel: 'false' }, { fullTunnel: false }, { routes: ['::/0'] }, { routes: ['1.2.3.4/33'] }, { routes: ['1.2.3.4/-1'] }, { routes: ['1.2.3.4/'] }, { dns: ['bad'] }, { fullTunnel: false, routes: ['0.0.0.0/0'] }, { fullTunnel: false, routes: ['0.0.0.0/00'] }]) assert.throws(() => policy(value));
  assert.equal(policy({ fullTunnel: false, routes: ['10.0.0.0/8'], mode: 'hybrid' }).mode, 'hybrid');
});
test('key rotation changes the PSK and invalidates previous invitations', () => {
  const store = make();
  try {
    const a = store.create({ name: 'Alice' }), oldKey = store.credential(a.user.id).key;
    const oldToken = new URLSearchParams(new URL(a.invitation.uri).hash.slice(1)).get('token');
    const invitation = store.rotate(a.user.id);
    assert.notEqual(store.credential(a.user.id).key, oldKey);
    assert.equal(store.redeem(oldToken), null);
    assert.ok(store.redeem(new URLSearchParams(new URL(invitation.uri).hash.slice(1)).get('token')));
    assert.equal(store.list().length, 1);
  } finally { store.close(); }
});
