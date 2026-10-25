const fragment = location.hash;
history.replaceState(null, '', location.pathname);
document.getElementById('redeem').onclick = async function () {
  this.disabled = true;
  try {
    const values = new URLSearchParams(fragment.slice(1));
    if (!values.get('key') || !values.get('token')) throw new Error('Paste the complete invitation link into your client.');
    const response = await fetch('api/enroll', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: values.get('token') }) });
    const result = await response.json(); if (!response.ok) throw new Error(result.error);
    const decode = s => Uint8Array.from(atob(s.replaceAll('-', '+').replaceAll('_', '/')), c => c.charCodeAt(0));
    const key = await crypto.subtle.importKey('raw', decode(values.get('key')), 'AES-GCM', false, ['decrypt']);
    const bytes = decode(result.ciphertext), clear = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: bytes.slice(0, 12) }, key, bytes.slice(12));
    const url = URL.createObjectURL(new Blob([clear], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = 'xpn-profile.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    document.getElementById('status').textContent = 'Profile downloaded. Keep this credential private.';
  } catch (e) { document.getElementById('status').textContent = e.message; this.disabled = false; }
};
