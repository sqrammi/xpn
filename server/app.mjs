import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { timingSafeEqual } from 'node:crypto';
import QRCode from 'qrcode';

const equal = (a, b) => typeof a === 'string' && Buffer.byteLength(a) === Buffer.byteLength(b) && timingSafeEqual(Buffer.from(a), Buffer.from(b));
const json = (res, status, value) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(value)); };
async function body(req) {
  let text = '';
  for await (const chunk of req) { text += chunk; if (Buffer.byteLength(text) > 8192) throw new Error('Request too large'); }
  const value = JSON.parse(text || '{}');
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Expected an object');
  return value;
}
export function createApp({ store, adminToken, publicURL, mailer }) {
  const origin = new URL(publicURL).origin, base = new URL(publicURL).pathname.replace(/\/$/, '');
  const limits = new Map();
  function rate(req, scope, max) {
    // Direct peers only: nginx supplies connection limits; untrusted Forwarded headers are ignored.
    const key = scope + ':' + req.socket.remoteAddress, now = Date.now();
    if (limits.size > 10000) for (const [k, v] of limits) if (v.until < now) limits.delete(k);
    const entry = limits.get(key);
    if (!entry || entry.until < now) { limits.set(key, { count: 1, until: now + 60000 }); return true; }
    return ++entry.count <= max;
  }
  return http.createServer(async (req, res) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'");
    try {
      const path = new URL(req.url, origin).pathname;
      if (req.headers.origin && req.headers.origin !== origin) return json(res, 403, { error: 'Invalid origin' });
      if (path === base + '/api/enroll' && req.method === 'POST') {
        if (!rate(req, 'enroll', 60)) return json(res, 429, { error: 'Try later' });
        const data = store.redeem((await body(req)).token);
        return json(res, data ? 200 : 410, data ? { ciphertext: data } : { error: 'Invitation expired, used, or revoked' });
      }
      if (path.startsWith(base + '/api/')) {
        if (!rate(req, 'admin', 120)) return json(res, 429, { error: 'Try later' });
        if (!equal(req.headers.authorization, `Bearer ${adminToken}`)) return json(res, 401, { error: 'Unauthorized' });
        if (path === base + '/api/users' && req.method === 'GET') return json(res, 200, store.list());
        let result;
        if (path === base + '/api/users' && req.method === 'POST') result = store.create(await body(req));
        const match = path.match(new RegExp('^' + base.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '/api/users/([a-f0-9-]+)/(invite|rotate|revoke|email)$'));
        if (match && req.method === 'POST') {
          const [, id, action] = match;
          if (action === 'revoke') { store.revoke(id); return json(res, 200, { ok: true }); }
          if (action === 'invite') result = { invitation: store.invite(id) };
          if (action === 'rotate') result = { invitation: store.rotate(id) };
          if (action === 'email') {
            if (!mailer) return json(res, 503, { error: 'SMTP is not configured' });
            const user = store.list().find(x => x.id === id && !x.revoked);
            if (!user?.email) throw new Error('User has no email');
            const invitation = store.invite(id);
            const png = await QRCode.toBuffer(invitation.uri, { width: 480, errorCorrectionLevel: 'M' });
            await mailer.sendMail({ to: user.email, subject: 'Your XPN invitation (expires in 15 minutes)',
              text: `Open XPN and scan the attached QR code or paste this invitation:\n${invitation.uri}\nThis is a one-use device credential. Treat it as a password.`,
              attachments: [{ filename: 'xpn-invitation.png', content: png, contentType: 'image/png' }] });
            store.audit('invite.email', id); return json(res, 200, { ok: true });
          }
        }
        if (result) { result.invitation.qr = await QRCode.toDataURL(result.invitation.uri, { width: 480 }); return json(res, 201, result); }
        return json(res, 404, { error: 'Not found' });
      }
      if (!['GET', 'HEAD'].includes(req.method)) return json(res, 405, { error: 'Method not allowed' });
      const assets = { '/': ['index.html', 'text/html'], '/join': ['join.html', 'text/html'], '/app.js': ['app.js', 'text/javascript'], '/join.js': ['join.js', 'text/javascript'], '/app.css': ['app.css', 'text/css'] };
      if (path === base && base) { res.writeHead(308, { Location: base + '/' }); return res.end(); }
      const asset = assets[path.slice(base.length)];
      if (!path.startsWith(base + '/') || !asset) return json(res, 404, { error: 'Not found' });
      const file = await readFile(new URL('./public/' + asset[0], import.meta.url));
      res.writeHead(200, { 'Content-Type': asset[1], 'Cache-Control': 'no-store' }); res.end(req.method === 'HEAD' ? undefined : file);
    } catch (err) {
      // Validation errors are safe; do not return filesystem, SMTP or crypto internals.
      const safe = /^(Invalid|Name |Routes |Split tunnel|Use full tunnel|Unknown|Address pool|User has)/.test(err.message);
      json(res, safe || err instanceof SyntaxError ? 400 : 500, { error: safe ? err.message : 'Request failed' });
    }
  });
}
export function createInternal(store) {
  return http.createServer((req, res) => {
    if (req.method === 'GET' && req.url === '/users') return json(res, 200, store.list().filter(x => !x.revoked).map(x => store.credential(x.id)));
    const match = req.url.match(/^\/users\/([a-f0-9-]{36})$/);
    const value = req.method === 'GET' && match ? store.credential(match[1]) : null;
    json(res, value ? 200 : 404, value ?? { error: 'Not found' });
  });
}
