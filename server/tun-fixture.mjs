// Private fixture for native/tests/tun-integration.py; never a deployed service.
import { Store } from './store.mjs';
import { createInternal } from './app.mjs';
import { randomBytes, X509Certificate } from 'node:crypto';
import { readFileSync, writeFileSync, chmodSync } from 'node:fs';
const directory = process.argv[2];
process.umask(0o077);
const pin = new X509Certificate(readFileSync(`${directory}/cert.pem`)).fingerprint256.replaceAll(':', '');
const store = new Store(':memory:', randomBytes(32).toString('hex'), 'https://198.18.0.1:8443/xpn');
for (const fullTunnel of [false, true]) {
  const { user } = store.create({ name: fullTunnel ? 'full' : 'split', fullTunnel,
    routes: ['192.0.2.0/24'], sni: 'app.jeffhansen.com', certificatePins: [pin] });
  writeFileSync(`${directory}/control/${user.name}.json`, JSON.stringify(store.credential(user.id)), { mode: 0o600 });
}
const server = createInternal(store);
server.listen(`${directory}/control/control.sock`, () => {
  chmodSync(`${directory}/control/control.sock`, 0o660);
  writeFileSync(`${directory}/control/ready`, 'ready');
});
process.on('SIGTERM', () => server.close(() => { store.close(); process.exit(0); }));
