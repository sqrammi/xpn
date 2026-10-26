// Obtain a public certificate pin from an independently trusted local PEM file.
import { readFile } from 'node:fs/promises';
import { X509Certificate } from 'node:crypto';
if (process.argv.length !== 3) {
  console.error('Usage: node server/cert-pin.mjs /path/to/nginx-leaf-certificate.pem');
  process.exit(2);
}
const certificate = new X509Certificate(await readFile(process.argv[2]));
console.log(certificate.fingerprint256.replaceAll(':', '').toLowerCase());
