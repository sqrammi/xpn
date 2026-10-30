import test from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { Store, unseal, policy, transportSettings } from './store.mjs';

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
    assert.equal(profile.version, 1);
    assert.equal(store.redeem(values.get('token')), null);
    assert.throws(() => unseal(randomBytes(32), cipher));
    const raw = store.db.prepare('SELECT secret FROM users WHERE id=?').get(a.user.id).secret;
    assert.ok(!raw.includes(profile.key));
    assert.ok(!JSON.stringify(store.list()).includes(profile.key));
  } finally { store.close(); }
});
test('custom SNI requires explicit certificate trust and rejects malformed input', () => {
  const pin = 'ab'.repeat(32);
  assert.deepEqual(transportSettings({ sni: 'App.JeffHansen.com', certificatePins: [pin, 'AB:'.repeat(31) + 'AB'] }), { sni: 'app.jeffhansen.com', certificatePins: [pin] });
  for (const sni of ['app.test', 'app.test:443', 'https://app.test', '127.0.0.1', '::1', '-app.test', 'app-.test', 'app..test', 'app.test.', 'a'.repeat(64) + '.test', 'app\0.test', 123]) {
    assert.throws(() => transportSettings({ sni }));
    if (sni !== 'app.test') assert.throws(() => transportSettings({ sni, certificatePins: [pin] }));
  }
  for (const certificatePins of [null, 'ab'.repeat(32), ['ab'], ['gg'.repeat(32)], Array(5).fill(pin)]) {
    // Null is deliberately treated like absent input; it cannot authorize SNI.
    assert.throws(() => transportSettings({ sni: 'app.test', certificatePins }));
  }
});
test('server defaults and overrides survive encrypted enrollment as v2 without changing endpoint', () => {
  const pins = ['ab'.repeat(32), 'cd'.repeat(32)];
  const store = new Store(':memory:', randomBytes(32).toString('hex'), 'https://vpn.example.test/xpn', { sni: 'app.jeffhansen.com', certificatePins: pins });
  try {
    const a = store.create({ name: 'Pinned' });
    const fragment = new URLSearchParams(new URL(a.invitation.uri).hash.slice(1));
    const profile = unseal(Buffer.from(fragment.get('key'), 'base64url'), store.redeem(fragment.get('token')));
    assert.equal(profile.version, 2); assert.equal(profile.sni, 'app.jeffhansen.com');
    assert.deepEqual(profile.certificatePins, pins);
    assert.equal(profile.endpoint, 'wss://vpn.example.test/xpn/vpn');
    const b = store.create({ name: 'Override', sni: 'alternate.test', certificatePins: [pins[1]] });
    assert.equal(store.credential(b.user.id).sni, 'alternate.test');
    assert.deepEqual(store.credential(b.user.id).certificatePins, [pins[1]]);
    const c = store.create({ name: 'Normal TLS', sni: '', certificatePins: [] });
    assert.equal(store.credential(c.user.id).version, 1);
    assert.throws(() => store.create({ name: 'Missing pin', certificatePins: [] }));
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
  for (const value of [{ fullTunnel: true, routes: ['10.77.0.0/24'] }, { mode: 'classical' }, { fullTunnel: 'false' }, { fullTunnel: false }, { routes: ['::/0'] }, { routes: ['1.2.3.4/33'] }, { routes: ['1.2.3.4/-1'] }, { routes: ['1.2.3.4/'] }, { dns: ['bad'] }, { fullTunnel: false, routes: ['0.0.0.0/0'] }, { fullTunnel: false, routes: ['0.0.0.0/00'] }]) assert.throws(() => policy(value));
  assert.equal(policy({ routes: ['10.77.0.0/24'] }).fullTunnel, false);
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
test('editing transport trust replaces invitations and preserves the device key', () => {
  const store = make();
  try {
    const a = store.create({ name: 'Alice' }), old = store.credential(a.user.id);
    const token = invitation => new URLSearchParams(new URL(invitation.uri).hash.slice(1)).get('token');
    assert.throws(() => store.setTransport(a.user.id, { sni: 'app.test' }));
    assert.equal(store.credential(a.user.id).version, 1);
    const invitation = store.setTransport(a.user.id, { sni: 'app.test', certificatePins: ['ab'.repeat(32)] });
    assert.equal(store.redeem(token(a.invitation)), null);
    assert.ok(store.redeem(token(invitation)));
    assert.equal(store.credential(a.user.id).key, old.key);
    assert.equal(store.credential(a.user.id).version, 2);
    store.setTransport(a.user.id, { sni: '', certificatePins: [] });
    assert.equal(store.credential(a.user.id).version, 1);
    store.revoke(a.user.id);
    assert.throws(() => store.setTransport(a.user.id, {}));
  } finally { store.close(); }
});
