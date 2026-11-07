const DATA = JSON.parse(document.getElementById('page-data').textContent);
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 3600); }
const regionLabel = r => r === DATA.national || r === 'National' ? 'Ghana (national administrator)' : r ? r + ' Region' : 'Region not set';
function regionSelect(value) {
  const s = el('select', 'in');
  [DATA.national, ...DATA.regions].forEach(r => { const o = el('option', null, regionLabel(r)); o.value = r; s.append(o); });
  s.value = value === 'National' ? DATA.national : value;
  return s;
}
$('#aRegion').replaceWith(Object.assign(regionSelect(DATA.regions[0]), { id: 'aRegion' }));
$('#aRegion').insertBefore(Object.assign(el('option', null, 'Choose a region…'), { value: '' }), $('#aRegion').firstChild);
$('#aRegion').value = '';

async function act(body) {
  const r = await fetch('/api/admin/users', { method: 'POST', headers: { 'X-CSRFToken': csrfToken(), 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const res = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(res.error || 'Something went wrong (' + r.status + ').');
  if (res.users) render(res.users);
  return res;
}
function showSecret(user, pw) {
  $('#secretLabel').textContent = 'Password for ' + user; $('#secretPw').textContent = pw; $('#secret').hidden = false;
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
$('#copyPw').onclick = () => navigator.clipboard.writeText($('#secretPw').textContent).then(() => toast('Copied'), () => toast('Select the password and copy it'));
$('#hidePw').onclick = () => { $('#secret').hidden = true; $('#secretPw').textContent = ''; };

function render(users) {
  const list = $('#users'); list.textContent = '';
  $('#none').hidden = users.length > 0;
  $('#count').textContent = users.length + (users.length === 1 ? ' account' : ' accounts');
  users.forEach(u => {
    const li = el('li', 'user'), who = el('div', 'who'), name = el('b', null, u.username);
    if (u.mustChange) name.append(el('span', 'badge', 'Must set password'));
    if (u.region === DATA.national || u.region === 'National') name.append(el('span', 'badge nat', 'National'));
    const full = el('span', null, u.name || '(no name) '), rn = el('button', 'nm', u.name ? ' · rename' : 'add name'); rn.type = 'button';
    rn.onclick = async () => {
      const n = prompt('Full name for ' + u.username, u.name || ''); if (n == null) return;
      try { await act({ action: 'rename', username: u.username, name: n }); toast('Name saved'); } catch (e) { toast(e.message); }
    };
    const pic = el('span', 'pic');
    if (u.photo) { const i = el('img'); i.alt = ''; i.src = '/api/profile/photo?u=' + encodeURIComponent(u.username); pic.append(i); }
    else pic.textContent = (u.name || u.username).split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
    const line = el('span'); line.append(full, rn);
    who.append(pic, name, line, el('span', null, u.cadre || 'Cadre not set'));
    // Moving an account to another region: for a wrong region picked at sign-up. It is signed out and works for the new region from its next sign-in.
    const reg = regionSelect(u.region); reg.setAttribute('aria-label', 'Region of ' + u.username);
    reg.onchange = async () => {
      if (!confirm('Move ' + u.username + ' to ' + regionLabel(reg.value) + '?\n\nIt will be signed out and see only that region from its next sign-in.')) { reg.value = u.region; return; }
      try { await act({ action: 'region', username: u.username, region: reg.value }); toast(u.username + ' moved to ' + regionLabel(reg.value)); } catch (e) { toast(e.message); reg.value = u.region; }
    };
    const acts = el('div', 'acts'), reset = el('button', 'btn', 'Reset password'), del = el('button', 'btn danger', 'Delete');
    reset.type = del.type = 'button';
    reset.onclick = async () => {
      const pw = prompt('New password for ' + u.username + ' (at least 8 characters).\nLeave blank to make one.', ''); if (pw == null) return;
      try { const r = await act({ action: 'reset', username: u.username, password: pw }); showSecret(u.username, r.password); } catch (e) { toast(e.message); }
    };
    del.onclick = async () => {
      if (!confirm('Delete the account ' + u.username + '?\n\nIt is signed out and can no longer sign in. The data it entered stays.')) return;
      try { await act({ action: 'remove', username: u.username }); toast(u.username + ' deleted'); } catch (e) { toast(e.message); }
    };
    acts.append(reset, del);
    li.append(who, reg, acts); list.append(li);
  });
}

$('#addForm').addEventListener('submit', async e => {
  e.preventDefault();
  const body = { action: 'add', name: $('#aName').value.trim(), username: $('#aUser').value.trim(), region: $('#aRegion').value, password: $('#aPass').value };
  if (!body.username) { toast('Enter a username.'); $('#aUser').focus(); return; }
  if (!body.region) { toast('Choose a region.'); $('#aRegion').focus(); return; }
  const b = $('#addBtn'); b.disabled = true;
  try {
    const r = await act(body);
    showSecret(body.username.toLowerCase(), r.password); $('#addForm').reset(); $('#aRegion').value = '';
  } catch (ex) { toast(ex.message); } finally { b.disabled = false; }
});

fetch('/api/admin/users', { headers: { 'X-CSRFToken': csrfToken() } }).then(r => r.json()).then(r => render(r.users || [])).catch(() => toast('Could not load the accounts.'));
