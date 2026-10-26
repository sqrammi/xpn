let token = '';
let editingUser = null;
const $ = id => document.getElementById(id);
async function api(path, value) {
  const response = await fetch('api/' + path, { method: value ? 'POST' : 'GET', headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }, body: value ? JSON.stringify(value) : undefined });
  const data = await response.json(); if (!response.ok) throw new Error(data.error); return data;
}
function show(invite) { $('invite-empty').hidden = true; $('invite').hidden = false; $('qr').src = invite.qr; $('invite-uri').value = invite.uri; $('expiry').textContent = 'Expires ' + new Date(invite.expires).toLocaleTimeString(); }
async function run(button, fn) { button.disabled = true; $('status').textContent = ''; try { await fn(); } catch(e) { $('status').textContent = e.message; } finally { button.disabled = false; } }
async function refresh() {
  const users = await api('users'); $('users').replaceChildren();
  if (!users.length) { const tr = document.createElement('tr'), td = document.createElement('td'); td.colSpan = 5; td.textContent = 'No identities yet. Add your first device above.'; tr.append(td); $('users').append(tr); }
  for (const user of users) {
    const tr = document.createElement('tr');
    for (const text of [user.name, user.ip, user.policy.mode + ' · ' + (user.policy.fullTunnel ? 'All IPv4' : user.policy.routes.join(', ')), user.revoked ? 'Revoked' : 'Enabled']) { const td = document.createElement('td'); td.textContent = text; tr.append(td); }
    if (user.policy.certificatePins?.length) { const detail = document.createElement('small'); detail.textContent = `Pinned certificate${user.policy.sni ? ' · SNI ' + user.policy.sni : ''}`; tr.children[2].append(detail); }
    const actions = document.createElement('td');
    if (!user.revoked) {
      const edit = document.createElement('button'); edit.textContent = 'Certificate / SNI'; edit.className = 'secondary';
      edit.onclick = () => {
        editingUser = user.id; $('transport-title').textContent = 'Server trust · ' + user.name;
        $('transport-sni').value = user.policy.sni || '';
        $('transport-pins').value = (user.policy.certificatePins || []).join('\n');
        $('transport-error').textContent = ''; $('transport-dialog').showModal();
      };
      actions.append(edit);
    }
    if (!user.revoked) for (const [action, label] of [['invite','New QR'], ['rotate','Rotate key'], ...(user.email ? [['email','Email QR']] : []), ['revoke','Revoke']]) {
      const button = document.createElement('button'); button.textContent = label; button.className = action === 'revoke' ? 'danger' : 'secondary';
      button.onclick = () => run(button, async () => { const result = await api(`users/${user.id}/${action}`, {}); if (result.invitation) show(result.invitation); if (action === 'revoke') { $('invite').hidden = true; $('qr').removeAttribute('src'); $('invite-uri').value = ''; } $('status').textContent = action === 'email' ? 'Invitation sent.' : ''; await refresh(); });
      actions.append(button);
    }
    tr.append(actions); $('users').append(tr);
  }
}
$('login-form').onsubmit = e => { e.preventDefault(); run(e.submitter, async () => { token = $('token').value; await refresh(); $('token').value = ''; $('login').hidden = true; $('workspace').hidden = false; }); };
$('create-form').onsubmit = e => { e.preventDefault(); run(e.submitter, async () => { const data = Object.fromEntries(new FormData(e.target)); data.fullTunnel = data.routing === 'full'; data.routes = data.routes.split(',').map(x => x.trim()).filter(Boolean); data.dns = data.dns.split(',').map(x => x.trim()); data.sni = data.sni.trim(); if (!data.sni) delete data.sni; const pins = data.certificatePins.split(/[\s,]+/).filter(Boolean); if (pins.length) data.certificatePins = pins; else delete data.certificatePins; const result = await api('users', data); show(result.invitation); await refresh(); }); };
$('refresh').onclick = e => run(e.target, refresh);
$('transport-cancel').onclick = () => { $('transport-dialog').close(); editingUser = null; };
$('transport-form').onsubmit = async e => {
  e.preventDefault(); const button = e.submitter; button.disabled = true; $('transport-error').textContent = '';
  try {
    const result = await api(`users/${editingUser}/transport`, {
      sni: $('transport-sni').value.trim(), certificatePins: $('transport-pins').value.split(/[\s,]+/).filter(Boolean)
    });
    $('transport-dialog').close(); editingUser = null; show(result.invitation); await refresh();
    $('status').textContent = 'Server trust saved. Import the new QR profile on this device; an active session may disconnect.';
  } catch (error) { $('transport-error').textContent = error.message; }
  finally { button.disabled = false; }
};
$('lock').onclick = () => { token = ''; $('workspace').hidden = true; $('login').hidden = false; $('qr').removeAttribute('src'); $('invite-uri').value = ''; $('invite').hidden = true; $('invite-empty').hidden = false; $('users').replaceChildren(); };
