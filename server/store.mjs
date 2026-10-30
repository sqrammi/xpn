import { DatabaseSync } from 'node:sqlite';
import { randomBytes, randomUUID, createHash, createCipheriv, createDecipheriv } from 'node:crypto';
import { isIP } from 'node:net';

export const hash = value => createHash('sha256').update(value).digest('hex');
export function seal(key, value) {
  const nonce = randomBytes(12), cipher = createCipheriv('aes-256-gcm', key, nonce);
  const body = Buffer.concat([cipher.update(JSON.stringify(value)), cipher.final()]);
  return Buffer.concat([nonce, body, cipher.getAuthTag()]).toString('base64url');
}
export function unseal(key, value) {
  const data = Buffer.from(value, 'base64url');
  const decipher = createDecipheriv('aes-256-gcm', key, data.subarray(0, 12));
  decipher.setAuthTag(data.subarray(-16));
  return JSON.parse(Buffer.concat([decipher.update(data.subarray(12, -16)), decipher.final()]));
}
export function transportSettings(input = {}) {
  const sni = input.sni ?? '';
  if (typeof sni !== 'string' || sni.length > 253 || (sni && (isIP(sni) || sni.split('.').some(label => !/^[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?$/i.test(label))))) throw new Error('Invalid SNI: use a DNS hostname without a port');
  const pins = input.certificatePins ?? [];
  if (!Array.isArray(pins) || pins.length > 4 || pins.some(pin => typeof pin !== 'string' || !(/^[a-f\d]{64}$/i.test(pin) || /^(?:[a-f\d]{2}:){31}[a-f\d]{2}$/i.test(pin)))) throw new Error('Invalid certificate pins: supply up to four SHA-256 certificate fingerprints');
  const certificatePins = [...new Set(pins.map(pin => pin.replaceAll(':', '').toLowerCase()))];
  if (sni && !certificatePins.length) throw new Error('Invalid SNI configuration: a certificate pin is required');
  return { sni: sni.toLowerCase(), certificatePins };
}
export function policy(input, defaults = {}) {
  const mode = input.mode ?? 'psk';
  if (!['hybrid', 'psk'].includes(mode)) throw new Error('Invalid crypto mode');
  const fullTunnel = input.fullTunnel ?? !(Array.isArray(input.routes) && input.routes.length);
  if (typeof fullTunnel !== 'boolean') throw new Error('Invalid fullTunnel');
  const routes = input.routes ?? [];
  if (!Array.isArray(routes) || routes.length > 32 || routes.some(route => {
    if (typeof route !== 'string') return true;
    const [ip, bits, extra] = route.split('/');
    return extra !== undefined || isIP(ip) !== 4 || !/^\d+$/.test(bits ?? '') || +bits > 32;
  })) throw new Error('Routes must be IPv4 CIDRs');
  if (fullTunnel && routes.length) throw new Error('Invalid routing: select subnet-only routing when specifying subnets');
  if (!fullTunnel && !routes.length) throw new Error('Split tunnel needs at least one subnet');
  if (!fullTunnel && routes.some(r => Number(r.split('/')[1]) === 0)) throw new Error('Use full tunnel for a default route');
  const dns = input.dns ?? ['1.1.1.1'];
  if (!Array.isArray(dns) || !dns.length || dns.length > 3 || dns.some(x => typeof x !== 'string' || isIP(x) !== 4)) throw new Error('Invalid DNS servers');
  return { mode, fullTunnel, routes, dns, ...transportSettings({ ...defaults, ...input }) };
}
export class Store {
  constructor(path, masterKey, publicURL, transportDefaults = {}) {
    this.key = Buffer.from(masterKey, 'hex');
    if (this.key.length !== 32 || !/^[a-f\d]{64}$/i.test(masterKey)) throw new Error('MASTER_KEY must be 32 bytes in hex');
    this.url = publicURL.replace(/\/$/, '');
    this.transportDefaults = transportSettings(transportDefaults);
    this.db = new DatabaseSync(path);
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
      CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT, ip TEXT UNIQUE NOT NULL,
        secret TEXT NOT NULL, policy TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS invites (hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
        ciphertext TEXT NOT NULL, expires INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS audit (at INTEGER NOT NULL, event TEXT NOT NULL, user_id TEXT);`);
    // Detect accidental master-key changes before accepting new writes.
    const row = this.db.prepare('SELECT secret FROM users LIMIT 1').get();
    if (row) unseal(this.key, row.secret);
  }
  audit(event, id) { this.db.prepare('INSERT INTO audit VALUES (?, ?, ?)').run(Date.now(), event, id); }
  list() { return this.db.prepare('SELECT id,name,email,ip,policy,revoked,created FROM users ORDER BY created DESC').all().map(x => ({ ...x, policy: JSON.parse(x.policy) })); }
  create(input) {
    if (typeof input.name !== 'string' || !input.name.trim() || input.name.length > 80) throw new Error('Name must be 1–80 characters');
    if (input.email && (typeof input.email !== 'string' || input.email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.email))) throw new Error('Invalid email');
    const p = policy(input, this.transportDefaults), id = randomUUID();
    const used = new Set(this.list().map(x => x.ip));
    let ip;
    for (let i = 2; i < 255; i++) if (!used.has(`10.77.0.${i}`)) { ip = `10.77.0.${i}`; break; }
    if (!ip) throw new Error('Address pool exhausted (253 devices)');
    const secret = seal(this.key, randomBytes(32).toString('base64url'));
    this.db.prepare('INSERT INTO users (id,name,email,ip,secret,policy,created) VALUES (?,?,?,?,?,?,?)').run(id, input.name.trim(), input.email || null, ip, secret, JSON.stringify(p), Date.now());
    this.audit('user.create', id);
    return { user: this.list().find(x => x.id === id), invitation: this.invite(id) };
  }
  credential(id) {
    const u = this.db.prepare('SELECT * FROM users WHERE id=? AND revoked=0').get(id);
    if (!u) return null;
    const settings = JSON.parse(u.policy);
    // Older clients reject v2 rather than silently ignoring certificate pins.
    return { version: settings.certificatePins?.length ? 2 : 1, id, key: unseal(this.key, u.secret), address: u.ip, endpoint: this.url.replace(/^https:/, 'wss:') + '/vpn', ...settings };
  }
  invite(id) {
    const profile = this.credential(id);
    if (!profile) throw new Error('Unknown or revoked user');
    const token = randomBytes(32).toString('base64url'), wrappingKey = randomBytes(32);
    const expires = Date.now() + 15 * 60 * 1000;
    this.db.exec('BEGIN IMMEDIATE');
    try {
      this.db.prepare('DELETE FROM invites WHERE user_id=? OR expires<?').run(id, Date.now());
      this.db.prepare('INSERT INTO invites VALUES (?,?,?,?,0)').run(hash(token), id, seal(wrappingKey, profile), expires);
      this.audit('invite.create', id); this.db.exec('COMMIT');
    } catch (e) { this.db.exec('ROLLBACK'); throw e; }
    // Fragment values are never sent in HTTP requests or access logs.
    const fragment = new URLSearchParams({ token, key: wrappingKey.toString('base64url') });
    return { uri: `${this.url}/join#${fragment}`, expires };
  }
  redeem(token) {
    if (typeof token !== 'string' || !/^[\w-]{43}$/.test(token)) return null;
    // Atomic consume. Concurrent processes cannot redeem the same invitation twice.
    const row = this.db.prepare(`UPDATE invites SET used=1 WHERE hash=? AND used=0 AND expires>?
      AND user_id IN (SELECT id FROM users WHERE revoked=0) RETURNING ciphertext,user_id`).get(hash(token), Date.now());
    if (!row) return null;
    this.audit('invite.redeem', row.user_id);
    return row.ciphertext;
  }
  revoke(id) {
    const result = this.db.prepare('UPDATE users SET revoked=1 WHERE id=?').run(id);
    if (!result.changes) throw new Error('Unknown user');
    this.db.prepare('DELETE FROM invites WHERE user_id=?').run(id); this.audit('user.revoke', id);
  }
  rotate(id) {
    const result = this.db.prepare('UPDATE users SET secret=? WHERE id=? AND revoked=0').run(seal(this.key, randomBytes(32).toString('base64url')), id);
    if (!result.changes) throw new Error('Unknown or revoked user');
    this.db.prepare('DELETE FROM invites WHERE user_id=?').run(id);
    this.audit('user.rotate', id);
    return this.invite(id);
  }
  setTransport(id, input) {
    const user = this.db.prepare('SELECT policy FROM users WHERE id=? AND revoked=0').get(id);
    if (!user) throw new Error('Unknown or revoked user');
    const settings = { ...JSON.parse(user.policy), ...transportSettings(input) };
    this.db.exec('BEGIN IMMEDIATE');
    try {
      this.db.prepare('UPDATE users SET policy=? WHERE id=?').run(JSON.stringify(settings), id);
      this.db.prepare('DELETE FROM invites WHERE user_id=?').run(id);
      this.audit('user.transport', id); this.db.exec('COMMIT');
    } catch (error) { this.db.exec('ROLLBACK'); throw error; }
    return this.invite(id);
  }
  close() { this.db.close(); }
}
