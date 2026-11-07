const DATA = JSON.parse(document.getElementById('page-data').textContent);
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 3600); }
const initials = n => (n || DATA.username).split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');

function showAvatar() {
  const a = $('#avatar'); a.textContent = '';
  if (DATA.photo) { const i = el('img'); i.alt = ''; i.src = '/api/profile/photo?v=' + Date.now(); a.append(i); }
  else a.textContent = initials($('#name').value);
  $('#dropBtn').hidden = !DATA.photo;
}
$('#name').value = DATA.name;
const sel = $('#cadre'), ph = el('option', null, 'Choose your cadre…'); ph.value = ''; sel.append(ph);
DATA.cadres.forEach(c => { const o = el('option', null, c); o.value = c; sel.append(o); });
sel.value = DATA.cadre || '';
$('#user').textContent = DATA.username;
$('#region').textContent = DATA.role === 'support' ? 'Support (all regions)' : DATA.role === 'national' ? 'Ghana (national)' : DATA.region + ' Region';
$('#navAdmin').hidden = DATA.role !== 'support';
$('#back').href = DATA.next;
showAvatar();
$('#name').addEventListener('input', () => { if (!DATA.photo) showAvatar(); });

async function post(path, body, type) {
  const r = await fetch(path, { method: 'POST', headers: { 'X-CSRFToken': csrfToken(), 'Content-Type': type || 'application/json' }, body });
  const res = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(res.error || 'Something went wrong (' + r.status + ').');
  return res;
}
$('#form').addEventListener('submit', async e => {
  e.preventDefault();
  const b = $('#save'); b.disabled = true;
  try { await post('/api/profile', JSON.stringify({ name: $('#name').value, cadre: sel.value })); toast('Profile saved'); }
  catch (ex) { toast(ex.message); } finally { b.disabled = false; }
});
$('#pickBtn').onclick = () => $('#file').click();
$('#file').addEventListener('change', async () => {
  const f = $('#file').files[0]; $('#file').value = ''; if (!f) return;
  if (f.size > 3 * 1024 * 1024) { toast('Choose a picture under 3 MB.'); return; }
  try { await post('/api/profile/photo', await f.arrayBuffer(), 'application/octet-stream'); DATA.photo = true; showAvatar(); toast('Picture saved'); }
  catch (ex) { toast(ex.message); }
});
$('#dropBtn').onclick = async () => {
  if (!confirm('Remove your profile picture?')) return;
  try { await post('/api/profile/photo', new ArrayBuffer(0), 'application/octet-stream'); DATA.photo = false; showAvatar(); toast('Picture removed'); }
  catch (ex) { toast(ex.message); }
};
