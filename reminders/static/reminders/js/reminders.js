/* SMS reminders: district officers, today's reminders (preview, Send now), a test SMS and the log. */
let DATA = JSON.parse(document.getElementById('page-data').textContent);
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const plural = (n, w, p) => n + ' ' + (n === 1 ? w : (p || w + 's'));
const dmy = s => s ? String(s).slice(8, 10) + '/' + String(s).slice(5, 7) + '/' + String(s).slice(0, 4) : '';
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 5000); }
async function post(path, obj) {
  const r = await fetch(path, { method: 'POST', headers: { 'X-CSRFToken': csrfToken(), 'Content-Type': 'application/json' }, body: JSON.stringify(obj || {}) });
  let body = null; try { body = await r.json(); } catch (_) {}
  if (!r.ok) throw new Error((body && body.error) || 'Something went wrong (' + r.status + ').');
  return body;
}
const canWrite = () => !DATA.national;  // officers are added for one region (a regional account's own)
const canSend = () => DATA.support && !DATA.national;  // sending from the page and the SMS settings: support only
let removed = [];

function render(results) {
  $('#regionSlug').textContent = $('#navRegion').textContent = DATA.regionLabel.toUpperCase();
  $('#readOnly').hidden = canWrite();
  const s = DATA.sms;
  $('#smsDot').className = 'dot ' + (s.configured ? 'live' : 'err');
  $('#smsText').textContent = s.configured ? (DATA.support ? 'Fish Africa · sender ' + s.sender : 'SMS switched on') : 'SMS not set up';
  const note = $('#setupNote'); note.hidden = s.configured; note.replaceChildren();
  if (!s.configured) {
    note.append(el('p', 'label', 'SMS is not set up yet'), el('p', 'hint', DATA.support
      ? 'Enter the Fish Africa App ID, App Secret and sender ID in the settings below. Until then, reminders can be previewed but not sent.'
      : 'The support team has not switched SMS on yet. You can already add your district officers: their reminders start as soon as it is on.'));
  }
  const ro = $('#readOnly'); ro.querySelector('.trow').hidden = !DATA.support;
  ro.querySelector('.hint').textContent = DATA.support
    ? 'This view shows every region’s officers, reminders and log. Officers are added, and reminders sent, for one region: choose it here. Every region’s reminders also go out with the daily job.'
    : 'This view shows every region’s officers, reminders and log, and changes nothing. Each region’s officers are added by its regional surveillance team.';
  const sentToday = DATA.log.filter(l => String(l.at).slice(0, 10) === String(DATA.today) && l.ok).length;
  const tiles = [['report', DATA.due, 'Cases due soon or overdue'], ['soon', DATA.preview.length, 'Messages to send now'],
    ['closed', sentToday, 'Case reminders sent today'], ['', DATA.contacts.filter(c => c.active).length, 'Officers getting SMS']];
  $('#tally').replaceChildren(...tiles.map(([c, n, l]) => { const d = el('div', 'stat ' + c); d.append(el('b', null, n), el('span', null, l)); return d; }));
  $('#rules').textContent = 'One SMS when a case enters its last ' + DATA.rules.soon + ' days before day 60, then once overdue and every ' + DATA.rules.repeat + ' days until follow-up is done. EPID numbers only, never names.';
  renderPreview(results); renderContacts(); renderLog(); renderSettings();
}

function renderSettings() {
  if (!DATA.support) return;
  const s = DATA.sms;
  $('#sAppId').value = ''; $('#sSecret').value = ''; $('#sSender').value = s.sender || '';
  $('#sAppId').placeholder = s.appIdEnd ? 'saved: …' + s.appIdEnd + ' (type to replace)' : 'App ID';
  $('#sSecret').placeholder = s.hasSecret ? 'saved (type to replace)' : 'App Secret';
  $('#sSource').textContent = s.source === 'page' ? 'Saved on this page' : s.source === 'env' ? 'From the .env file' : 'Not set';
  $('#sClear').hidden = s.source !== 'page';
  if (DATA.national && !$('#regionPick').options.length) {
    const ph = el('option', null, 'Choose a region…'); ph.value = ''; $('#regionPick').append(ph);
    DATA.regions.forEach(n => { const o = el('option', null, n + ' Region'); o.value = n; $('#regionPick').append(o); });
  }
}

function renderPreview(results) {
  const box = $('#preview'); box.replaceChildren();
  const list = results || DATA.preview;
  if (!list.length) {
    box.append(el('p', 'empty-msg', DATA.due ? 'Every case due today has already been reminded, or no officer is set for its district.' : 'No case is due within ' + DATA.rules.soon + ' days or overdue. Nothing to send.'));
  } else {
    const grid = el('div', 'msgs');
    list.forEach(m => {
      const card = el('div', 'msg' + (m.ok === true ? ' sent' : m.ok === false ? ' failed' : ''));
      const to = el('div', 'to'); to.append(el('b', null, m.name + ' · ' + m.place), el('span', null, m.to));
      card.append(to, el('div', 'bubble', m.text), el('span', 'meta', plural(m.cases.length, 'case') + ' · ' + m.text.length + ' characters (' + Math.ceil(m.text.length / 153) + ' SMS)' + (m.ok === true ? ' · sent' : '')));
      if (m.error) card.append(el('p', 'fail', m.error));
      grid.append(card);
    });
    box.append(grid);
  }
  const btn = $('#sendNow');
  btn.hidden = !canSend(); btn.disabled = !DATA.sms.configured || !DATA.preview.length;
  $('#sendNote').textContent = results ? '' : !DATA.preview.length ? ''
    : !canSend() ? 'These go out automatically with the daily job, once per case and stage.'
    : DATA.sms.configured ? 'The daily job sends these too; sending now just sends them earlier. Each case is sent once per stage.' : 'Set up SMS to send.';
}

function contactRow(c) {
  const tr = el('tr'); tr.dataset.id = c.id || '';
  if (!canWrite()) {
    tr.append(el('td', null, c.region), el('td', null, c.district || 'Whole region'), el('td', null, c.name), el('td', 'mono', c.phone), el('td', null, c.active ? 'Yes' : 'No'));
    return tr;
  }
  const d = el('select', 'in'); d.dataset.k = 'district';
  [['', 'Whole region'], ...DATA.districts.map(([, n]) => [n, n])].forEach(([v, t]) => { const o = el('option', null, t); o.value = v; d.append(o); });
  d.value = c.district || '';
  const n = el('input', 'in'); n.value = c.name || ''; n.maxLength = 80; n.dataset.k = 'name'; n.placeholder = 'Full name';
  const p = el('input', 'in mono'); p.value = c.phone ? '0' + c.phone.slice(3) : ''; p.inputMode = 'tel'; p.dataset.k = 'phone'; p.placeholder = '0244123456';
  const a = el('input'); a.type = 'checkbox'; a.checked = c.active !== false; a.dataset.k = 'active'; a.setAttribute('aria-label', 'Gets SMS');
  const x = el('button', 'btn danger', 'Remove'); x.type = 'button';
  x.addEventListener('click', () => { if (c.id) removed.push(c.id); tr.remove(); });
  [d, n, p, a].forEach(i => { const td = el('td'); td.append(i); tr.append(td); });
  const xt = el('td', 'x'); xt.append(x); tr.append(xt);
  return tr;
}
function renderContacts() {
  removed = [];
  const t = $('#cTable'), w = canWrite();
  t.innerHTML = `<thead><tr>${w ? '' : '<th>Region</th>'}<th>District</th><th>Name</th><th>Phone</th><th>Gets SMS</th>${w ? '<th></th>' : ''}</tr></thead>`;
  const tb = el('tbody'); DATA.contacts.forEach(c => tb.append(contactRow(c))); t.append(tb);
  if (!DATA.contacts.length && !w) { const tr = el('tr'), td = el('td', 'muted', 'No officers yet.'); td.colSpan = 5; tr.append(td); tb.append(tr); }
  $('#cCount').textContent = plural(DATA.contacts.length, 'officer');
  $('#cAdd').hidden = $('#cSave').hidden = !w;
  if ($('#testPanel')) $('#testPanel').hidden = !canSend();
}
function renderLog() {
  const t = $('#logTable');
  t.innerHTML = '<thead><tr><th>When</th><th>EPID</th><th>Reminder</th><th>District</th><th>To</th><th>Result</th><th>By</th></tr></thead>';
  const tb = el('tbody');
  if (!DATA.log.length) { const tr = el('tr'), td = el('td', 'muted', 'Nothing sent yet.'); td.colSpan = 7; tr.append(td); tb.append(tr); }
  DATA.log.forEach(l => {
    const tr = el('tr'), res = el('td', l.ok ? 'okk' : 'bad', l.ok ? 'Sent' : 'Failed'); if (l.error) res.title = l.error;
    const stage = l.stage === 'soon' ? 'Due soon' : 'Overdue (week ' + l.stage.split('-')[1] + ')';
    tr.append(el('td', null, dmy(l.at) + ' ' + String(l.at).slice(11, 16)), el('td', 'mono', l.epid), el('td', null, stage), el('td', null, l.district), el('td', null, l.name + ' · ' + l.to), res, el('td', 'muted', l.by));
    tb.append(tr);
  });
  t.append(tb);
}

$('#sSave')?.addEventListener('click', async () => {
  const btn = $('#sSave'); btn.disabled = true;
  const appId = $('#sAppId').value.trim();
  try {
    if (!appId && !DATA.sms.appIdEnd) throw new Error('Enter the App ID.');
    // blank App ID and secret boxes keep the saved values
    DATA = await post('/api/sms/settings', { appId, appSecret: $('#sSecret').value, senderId: $('#sSender').value }); render();
    toast(DATA.sms.configured ? 'Settings saved. Send a test SMS to check them.' : 'Saved. Still missing: ' + DATA.sms.missing.join(', '));
  } catch (e) { toast(e.message); } finally { btn.disabled = false; }
});
$('#sClear')?.addEventListener('click', async () => {
  if (!confirm('Remove the saved Fish Africa settings? SMS stops until they are entered again.')) return;
  try { DATA = await post('/api/sms/settings', { clear: true }); render(); toast('Settings removed'); } catch (e) { toast(e.message); }
});
$('#regionGo').addEventListener('click', async () => {
  const name = $('#regionPick').value; if (!name) { toast('Choose a region.'); return; }
  try { await post('/api/region', { region: name }); location.reload(); } catch (e) { toast(e.message); }
});
$('#cAdd').addEventListener('click', () => { const tr = contactRow({}); $('#cTable tbody').prepend(tr); tr.querySelector('input').focus(); });
$('#cSave').addEventListener('click', async () => {
  const rows = [...document.querySelectorAll('#cTable tbody tr')].map(tr => {
    const o = { id: tr.dataset.id ? Number(tr.dataset.id) : null };
    tr.querySelectorAll('[data-k]').forEach(i => o[i.dataset.k] = i.type === 'checkbox' ? i.checked : i.value);
    return o;
  }).filter(r => r.id || r.name || r.phone);
  const btn = $('#cSave'); btn.disabled = true;
  try {
    const r = await post('/api/sms/contacts', { rows, delete: removed });
    DATA = r; render(); $('#cErr').textContent = r.problems.join(' ');
    toast(r.problems.length ? 'Saved, with problems: see below the table' : 'Officers saved');
  } catch (e) { toast(e.message); } finally { btn.disabled = false; }
});
$('#sendNow').addEventListener('click', async () => {
  if (!confirm('Send ' + plural(DATA.preview.length, 'SMS', 'SMS') + ' now?')) return;
  const btn = $('#sendNow'); btn.disabled = true;
  try {
    const r = await post('/api/sms/send');
    const ok = r.results.filter(x => x.ok).length, bad = r.results.length - ok;
    DATA = r; render(r.results);
    toast(bad ? ok + ' sent, ' + bad + ' failed: they will be tried again on the next run' : plural(ok, 'SMS', 'SMS') + ' sent');
  } catch (e) { toast(e.message); btn.disabled = false; }
});
$('#testSend')?.addEventListener('click', async () => {
  const btn = $('#testSend'); btn.disabled = true;
  try { const r = await post('/api/sms/test', { phone: $('#testPhone').value }); toast('Test SMS sent to ' + r.sent); }
  catch (e) { toast(e.message); } finally { btn.disabled = false; }
});
document.querySelectorAll('.year').forEach(e => e.textContent = new Date().getFullYear());
render();
