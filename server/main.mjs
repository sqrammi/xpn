import { mkdir, chmod, unlink, stat } from 'node:fs/promises';
import nodemailer from 'nodemailer';
import { Store } from './store.mjs';
import { createApp, createInternal } from './app.mjs';

process.umask(0o077);
const { PUBLIC_URL, MASTER_KEY, ADMIN_TOKEN, SMTP_URL, SMTP_FROM } = process.env;
if (!PUBLIC_URL || !MASTER_KEY || !ADMIN_TOKEN || ADMIN_TOKEN.length < 32) throw new Error('Set PUBLIC_URL, MASTER_KEY and ADMIN_TOKEN (32+ characters)');
const url = new URL(PUBLIC_URL);
if (PUBLIC_URL.length > 1800 || url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || !/^\/[a-zA-Z0-9/_-]*$/.test(url.pathname)) throw new Error('PUBLIC_URL must be an HTTPS origin with optional path prefix (1800 characters max)');
if (SMTP_URL && !SMTP_FROM) throw new Error('Set SMTP_FROM when configuring SMTP_URL');
const data = process.env.DATA_DIR || './data'; await mkdir(data, { recursive: true, mode: 0o700 });
const store = new Store(data + '/xpn.db', MASTER_KEY, PUBLIC_URL);
const mailer = SMTP_URL ? nodemailer.createTransport({ ...nodemailer.createTransport(SMTP_URL).options, requireTLS: true, disableFileAccess: true, disableUrlAccess: true }, { from: SMTP_FROM }) : null;
const app = createApp({ store, publicURL: PUBLIC_URL, adminToken: ADMIN_TOKEN, mailer });
const socket = process.env.CONTROL_SOCKET || data + '/control.sock';
try { const s = await stat(socket); if (!s.isSocket()) throw new Error('Control path is not a socket'); await unlink(socket); } catch (err) { if (err.code !== 'ENOENT') throw err; }
const internal = createInternal(store);
await new Promise(resolve => internal.listen(socket, resolve)); await chmod(socket, 0o660);
app.listen(Number(process.env.PORT || 3000), '127.0.0.1', () => console.log('XPN administration listening on loopback'));
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => { app.close(); internal.close(() => { store.close(); process.exit(0); }); });
