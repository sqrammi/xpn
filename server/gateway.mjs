import net from 'node:net';

// No shell commands or root credentials in Node. The helper owns validation,
// persistence and the atomic replacement of the two dedicated firewall chains.
export function gatewayRequest(message, socketPath = '/run/xpn-gateway/control.sock') {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(socketPath);
    let text = '', settled = false;
    const finish = (error, value) => {
      if (settled) return;
      settled = true; socket.destroy(); error ? reject(error) : resolve(value);
    };
    socket.setTimeout(8000, () => finish(new Error('Gateway helper unavailable')));
    socket.on('error', () => finish(new Error('Gateway helper unavailable')));
    socket.on('connect', () => socket.write(JSON.stringify(message) + '\n'));
    socket.on('data', chunk => {
      text += chunk.toString('utf8');
      if (Buffer.byteLength(text) > 16384) return finish(new Error('Invalid gateway response'));
      if (text.includes('\n')) {
        try { finish(null, JSON.parse(text)); } catch { finish(new Error('Invalid gateway response')); }
      }
    });
    socket.on('end', () => { if (!settled) finish(new Error('Gateway helper unavailable')); });
  });
}

export function gatewayTargetsReady(users, targets) {
  if (!Array.isArray(targets)) return false;
  // Replies are SNATed to the server gateway. Both the device and server policy
  // must already route that /32; changing a firewall cannot push client routes.
  const ip = value => value.split('.').reduce((a, b) => (a * 256 + Number(b)) >>> 0, 0);
  return targets.every(address => {
    const user = users.find(x => x.ip === address && !x.revoked);
    return user && (user.policy.fullTunnel || user.policy.routes.some(route => {
      const [network, bits] = route.split('/');
      const mask = Number(bits) === 0 ? 0 : (0xffffffff << (32 - Number(bits))) >>> 0;
      return (ip('10.77.0.1') & mask) === (ip(network) & mask);
    }));
  });
}
