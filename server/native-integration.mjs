// Real nginx + HTTPS enrollment + C/OpenSSL WSS loopback test, without root/TUN.
import { mkdtemp, writeFile, readFile, chmod, rm } from 'node:fs/promises';
import { spawn, execFileSync } from 'node:child_process';
import { randomBytes, X509Certificate } from 'node:crypto';
import { once } from 'node:events';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import net from 'node:net';
import assert from 'node:assert/strict';
import { Store } from './store.mjs';
import { createApp, createInternal } from './app.mjs';

const binary = process.argv[2]; if (!binary) throw new Error('Usage: node server/native-integration.mjs /path/to/test_transport');
const pinning = process.env.XPN_TEST_PINNING || 'legacy';
assert.ok(['legacy', 'sni', 'wrong-pin', 'trusted-wrong-pin', 'rotation', 'pin-only'].includes(pinning));
const customSNI = ['sni', 'wrong-pin', 'rotation'].includes(pinning) ? 'app.jeffhansen.com' : '';
const reject = ['wrong-pin', 'trusted-wrong-pin'].includes(pinning);
const directory = await mkdtemp(join(tmpdir(), 'xpn-nginx-'));
const freePort = async () => { const s = net.createServer(); await new Promise(r => s.listen(0,'127.0.0.1',r)); const p=s.address().port; await new Promise(r => s.close(r)); return p; };
const port = await freePort(), tunnelPort = await freePort(), socket = join(directory, 'control.sock');
let proxy, native, store, app, internal;
try {
  const cert = join(directory,'cert.pem'), key = join(directory,'key.pem');
  execFileSync(process.env.OPENSSL_BIN || 'openssl', ['req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost','-keyout',key,'-out',cert], { stdio:'ignore' });
  // Neither endpoint localhost nor the requested SNI appears in this certificate.
  const otherCert = join(directory,'other.pem'), otherKey = join(directory,'other-key.pem');
  execFileSync(process.env.OPENSSL_BIN || 'openssl', ['req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:P-256','-nodes','-days','1','-subj','/CN=certificate.example.invalid','-addext','subjectAltName=DNS:certificate.example.invalid','-keyout',otherKey,'-out',otherCert], { stdio:'ignore' });
  const fingerprint = async path => new X509Certificate(await readFile(path)).fingerprint256.replaceAll(':','').toLowerCase();
  const correctPin = await fingerprint(customSNI ? otherCert : cert);
  // Wrong pin is a real certificate fingerprint, never accepted just because CA verification succeeds.
  const wrongPin = await fingerprint(customSNI ? cert : otherCert);
  const certificatePins = pinning === 'legacy' ? [] : reject ? [wrongPin] : pinning === 'rotation' ? [wrongPin, correctPin] : [correctPin];
  store = new Store(':memory:',randomBytes(32).toString('hex'),`https://localhost:${port}/xpn`);
  const created = store.create({name:'Integration device',fullTunnel:false,routes:['10.20.0.0/16'],mode:process.env.XPN_TEST_MODE || 'psk', sni:customSNI, certificatePins});
  const invitation = join(directory,'invitation.txt'); await writeFile(invitation,created.invitation.uri,{mode:0o600});
  internal=createInternal(store); await new Promise(r=>internal.listen(socket,r)); await chmod(socket,0o600);
  app=createApp({store,adminToken:randomBytes(32).toString('hex'),publicURL:`https://localhost:${port}/xpn`});
  await new Promise(r=>app.listen(0,'127.0.0.1',r));
  const configuration=`pid "${directory}/nginx.pid"; error_log stderr info; daemon off; master_process off;
events { worker_connections 128; }
http { log_format identity '$uri|$ssl_server_name|$http_host|$status'; access_log "${directory}/access.log" identity;
client_body_temp_path "${directory}/body"; proxy_temp_path "${directory}/proxy";
server { listen 127.0.0.1:${port} ssl; listen [::1]:${port} ssl; server_name localhost; ssl_certificate "${cert}"; ssl_certificate_key "${key}"; ssl_protocols TLSv1.3;
location = /xpn/vpn { if ($ssl_server_name != "${customSNI || 'localhost'}") { return 421; }
proxy_pass http://127.0.0.1:${tunnelPort}; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; proxy_buffering off; proxy_read_timeout 23s; }
location /xpn/ { proxy_pass http://127.0.0.1:${app.address().port}; }
}
server { listen 127.0.0.1:${port} ssl; listen [::1]:${port} ssl; server_name app.jeffhansen.com;
ssl_certificate "${otherCert}"; ssl_certificate_key "${otherKey}"; ssl_protocols TLSv1.3;
# HTTP Host must remain localhost and select the other HTTP virtual host.
location / { return 421; }
} }`;
  const config = join(directory,'nginx.conf'); await writeFile(config,configuration);
  proxy=spawn(process.env.NGINX_BIN || 'nginx',['-p',directory+'/', '-c',config],{stdio:['ignore','ignore','pipe']});
  let proxyLog=''; proxy.stderr.on('data',x=>proxyLog+=x);
  for(let i=0;i<100;i++) {
    if(proxy.exitCode!==null) throw new Error(proxyLog);
    try { const s=net.connect(port,'127.0.0.1'); await once(s,'connect'); s.destroy(); break; }
    catch { await new Promise(r=>setTimeout(r,30)); }
  }
  native=spawn(resolve(binary),[String(tunnelPort),socket,cert,invitation],{stdio:['ignore','pipe','pipe'], env:{...process.env, ...(reject ? {XPN_TEST_EXPECT_REJECTION:'1'} : {})}});
  let output='', nativeLog='';
  native.stdout.on('data',chunk=>{ output+=chunk; if(output.includes('ROUNDTRIP')) store.revoke(created.user.id); });
  native.stderr.on('data',x=>nativeLog+=x);
  const timer=setTimeout(()=>native.kill('SIGKILL'),45000);
  const [code,signal]=await once(native,'exit'); clearTimeout(timer);
  assert.equal(code,0,`Native test failed (${signal}):\n${nativeLog}\n${proxyLog}`);
  const exit = once(proxy,'exit'); proxy.kill('SIGTERM'); await exit;
  const access = await readFile(join(directory,'access.log'),'utf8');
  if (reject) {
    assert.ok(output.includes('REJECTED'));
    assert.ok(!access.includes('/xpn/vpn|'), 'Rejected certificate must prevent the HTTP upgrade');
  } else {
    assert.ok(output.includes('ROUNDTRIP') && output.includes('REVOCATION'));
    assert.ok(access.includes(`/xpn/vpn|${customSNI || 'localhost'}|localhost|101`), access);
  }
  const benchmark = output.match(/^BENCHMARK .+$/m); if (benchmark) console.log(benchmark[0]);
  console.log(`PASS: ${pinning}, ${process.env.XPN_TEST_MODE || 'psk'}: ${reject ? 'certificate rejected before WebSocket upgrade' : 'encrypted enrollment, verified SNI and HTTP Host, WSS packets and revocation'}`);
} finally {
  if(native && native.exitCode===null) native.kill('SIGTERM');
  if(proxy && proxy.exitCode===null) { const exit=once(proxy,'exit'); proxy.kill('SIGTERM'); await exit; }
  for(const service of [app,internal]) if(service) { service.closeAllConnections(); await new Promise(r=>service.close(r)); }
  store?.close(); await rm(directory,{recursive:true,force:true});
}
