let DATA = JSON.parse(document.getElementById('page-data').textContent);
const FUP = 60, SOON = 7, DAY = 864e5;
const STATUS = {
  past:   { rank: 0, label: 'Past due' },
  soon:   { rank: 1, label: 'Due soon' },
  report: { rank: 2, label: 'Report pending' },
  nodate: { rank: 3, label: 'No onset date' },
  open:   { rank: 4, label: 'On track' },
  closed: { rank: 5, label: 'Closed' },
};
const VIEWS = { alerts: 'Follow-up alerts', entry: 'New case', upload: 'Update from file', report: DATA.national ? 'Regional report' : 'District report' };
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
let filter = 'action', query = '', cases = [], districts = [];

function store(key, fallback) { try { return JSON.parse(localStorage.getItem('afpwo.' + key)) ?? fallback; } catch (_) { return fallback; } }
function keep(key, val) { try { localStorage.setItem('afpwo.' + key, JSON.stringify(val)); } catch (_) {} }
// In the national view (Ghana) the watchlist pins regions, kept apart from a region's pinned districts.
const WATCH_KEY = DATA.national ? 'watchRegions' : 'watch', PLACE = DATA.national ? 'region' : 'district';
const placeOf = c => DATA.national ? c.region : c.district;
let watch = store(WATCH_KEY, []), seen = new Set(store('seen', []));

function toast(msg) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 3600); }
function asDate(iso) { if (typeof iso !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return null; const [y, m, d] = iso.slice(0, 10).split('-').map(Number); return new Date(y, m - 1, d); }
function fmt(d, year) { return d ? d.toLocaleDateString('en-GB', year ? { day: '2-digit', month: 'short', year: 'numeric' } : { day: '2-digit', month: 'short' }) : ''; }
function norm(s) { return String(s ?? '').trim().toLowerCase(); }
function plural(n, w) { return n + ' ' + w + (n === 1 ? '' : 's'); }

const today = new Date(); today.setHours(0, 0, 0, 0);
const isoToday = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');

function classify(c) {
  const onset = asDate(c.onset);
  const done = norm(c.outcome) === 'fup done', report = norm(c.report) === 'yes';
  if (!onset) return { key: done && report ? 'closed' : 'nodate', onset: null };
  const days = Math.round((today - onset) / DAY), left = FUP - days;
  const fup = new Date(onset.getTime() + FUP * DAY);
  let key = 'open';
  if (!done && days > FUP) key = 'past';
  else if (!done && left <= SOON) key = 'soon';
  else if (done && !report) key = 'report';
  else if (done) key = 'closed';
  return { key, onset, days, left, fup };
}

function age(c, onset) {
  if (typeof c.dob === 'number') return c.dob + ' y';
  const dob = asDate(c.dob); if (!dob) return '';
  const ref = onset || today, months = (ref.getFullYear() - dob.getFullYear()) * 12 + ref.getMonth() - dob.getMonth() - (ref.getDate() < dob.getDate() ? 1 : 0);
  return months < 24 ? Math.max(months, 0) + ' mo' : Math.floor(months / 12) + ' y';
}

const seenKey = c => c.epid + '|' + c.key;
const watched = c => watch.some(w => norm(w) === norm(placeOf(c)));
const needsAction = c => c.key === 'past' || c.key === 'soon' || c.key === 'report' || c.key === 'nodate';

function setData(d) {
  DATA = d;
  // Most urgent first: by status, then longest overdue / soonest deadline, then newest onset.
  cases = DATA.cases.map(c => ({ ...c, ...classify(c) })).sort((a, b) =>
    STATUS[a.key].rank - STATUS[b.key].rank ||
    (a.onset && b.onset ? (a.key === 'past' || a.key === 'soon' ? a.onset - b.onset : b.onset - a.onset) : 0));
  // Suggestions: the region's own districts (or the regions, for Ghana), plus any other spelling used in its cases.
  districts = DATA.national ? DATA.districts.map(([, n]) => n)
    : [...new Set([...DATA.districts.map(([, n]) => n), ...cases.map(c => c.district).filter(Boolean)])].sort();
  $('#districtInput').placeholder = 'e.g. ' + DATA.districts.slice(0, 2).map(([, n]) => n).join(', ');
  renderStatus(); renderWatch(); renderList(); fillYears();
  if (!$('#v-report').hidden) renderReport();
}

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { 'X-CSRFToken': csrfToken(), ...(opts.headers || {}) } });
  let body = null; try { body = await r.json(); } catch (_) {}
  if (!r.ok) throw Object.assign(new Error((body && body.error) || 'Something went wrong (' + r.status + ').'), { status: r.status, body });
  return body;
}
async function refreshData() { try { setData(await api('/api/data')); } catch (_) {} }

/* ---------- Alerts ---------- */
function renderStatus() {
  const gen = new Date(DATA.generated), ageDays = Math.round((today - new Date(gen.getFullYear(), gen.getMonth(), gen.getDate())) / DAY);
  const when = ageDays === 0 ? 'today ' + gen.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ageDays === 1 ? 'yesterday' : ageDays + ' d ago';
  $('#dot').className = 'dot ' + (DATA.live || ageDays === 0 ? 'live' : 'err');
  $('#statusText').textContent = (DATA.live ? 'Live · ' : 'Register read ' + when + ' · ') + plural(cases.length, 'case');
  $('#footNote').textContent = 'Built from ' + DATA.source + '. Statuses are worked out against today\'s date each time this page opens, with the same rules as the desktop alerts: past due once 60 days from onset pass without follow-up, due soon within 7 days. Seen marks and the watchlist are kept in this browser only.'
    + (!DATA.live && ageDays > 0 ? ' This copy is ' + plural(ageDays, 'day') + ' old.' : '');
}

function renderWatch() {
  const box = $('#chips'); box.textContent = '';
  watch.forEach(w => {
    const c = el('span', 'chip'); c.append(w);
    const x = el('button', null, '×'); x.type = 'button'; x.setAttribute('aria-label', 'Remove ' + w);
    x.onclick = () => { watch = watch.filter(y => y !== w); keep(WATCH_KEY, watch); renderWatch(); renderList(); };
    c.append(x); box.append(c);
  });
  const open = cases.filter(c => watched(c) && needsAction(c)).length;
  $('#watchNote').textContent = watch.length ? plural(open, 'case') + ' needing action' : 'Nothing pinned: every ' + PLACE + ' is shown';
  const dl = $('#districtList'); dl.textContent = '';
  districts.filter(d => !watch.some(w => norm(w) === norm(d))).forEach(d => { const o = document.createElement('option'); o.value = d; dl.append(o); });
}

function inFilter(c) {
  if (filter === 'all') return true;
  if (filter === 'action') return needsAction(c);
  if (filter === 'watch') return watched(c);
  return c.key === filter;
}
function inQuery(c) { return !query || [c.name, c.epid, c.district, c.region].some(v => norm(v).includes(query)); }

function timeCell(c) {
  const t = el('div', 'time'), b = el('b'); let sub = '';
  if (!c.onset) { b.textContent = 'No date'; sub = 'check onset'; }
  else if (c.key === 'past') { b.textContent = fmt(c.fup); sub = (c.days - FUP) + ' d late'; }
  else if (c.key === 'soon') { b.textContent = fmt(c.fup); sub = c.left === 0 ? 'due today' : 'in ' + c.left + ' d'; }
  else if (c.key === 'open') { b.textContent = fmt(c.fup); sub = 'in ' + c.left + ' d'; }
  else { const r = asDate(c.reportDate); b.textContent = fmt(r || c.fup); sub = r ? 'report in' : 'FUP date'; }
  t.append(b, sub); return t;
}

function renderList() {
  const counts = { action: 0, past: 0, soon: 0, report: 0, closed: 0, watch: 0 };
  cases.forEach(c => { if (needsAction(c)) counts.action++; if (c.key in counts) counts[c.key]++; if (watched(c)) counts.watch++; });
  $('#nAction').textContent = counts.action; $('#nPast').textContent = counts.past; $('#nSoon').textContent = counts.soon;
  $('#nReport').textContent = counts.report; $('#nWatch').textContent = counts.watch; $('#nAll').textContent = cases.length;
  $('#tPast').textContent = counts.past; $('#tSoon').textContent = counts.soon; $('#tReport').textContent = counts.report; $('#tClosed').textContent = counts.closed;

  const list = cases.filter(c => inFilter(c) && inQuery(c));
  const feed = $('#feed'); feed.textContent = '';
  const empty = $('#empty'); empty.hidden = list.length > 0;
  if (!list.length) {
    const [head, body] = query ? ['No matching cases', 'Nothing in this tab matches “' + query + '”.']
      : filter === 'watch' ? (watch.length ? ['No cases in watched ' + PLACE + 's', 'Cases reported from your pinned ' + PLACE + 's will show here.'] : ['No ' + PLACE + 's pinned', 'Add a ' + PLACE + ' above to collect its cases here.'])
      : filter === 'action' ? ['All clear', 'No follow-ups are overdue, due within 7 days or waiting on a report.']
      : ['Nothing here', 'No cases have this status right now.'];
    empty.querySelector('strong').textContent = head; empty.querySelector('span').textContent = body;
  }
  for (const c of list) {
    const isSeen = c.key === 'closed' || c.key === 'open' || seen.has(seenKey(c));
    const li = el('li', 'item' + (isSeen ? ' seen' : ''));
    const main = el('div', 'main');
    const hl = el('p', 'hl', c.name || '(no name)');
    const ep = el('span', 'epid', [c.epid, c.week != null ? 'Epi wk ' + c.week : '', c.onset ? 'Onset ' + fmt(c.onset, true) : ''].filter(Boolean).join(' · '));
    const meta = el('div', 'meta');
    const badge = (cls, text) => meta.append(el('span', 'badge ' + cls, text));
    const tag = text => { if (text) meta.append(el('span', 'tag', text)); };
    badge(c.key, STATUS[c.key].label);
    if (watched(c)) badge('watch', 'Watched');
    if (DATA.national) tag(c.region); tag(c.district); tag(c.sex); tag(age(c, c.onset)); tag(c.outcome); tag(c.lab ? 'Lab: ' + c.lab : '');
    main.append(hl, ep, meta);
    if (c.remarks) main.append(el('p', 'remarks', c.remarks));
    if (c.editUntil && DATA.live) {
      // Entered from this region in the last 24 hours: it can still be corrected or removed here.
      const row = el('div', 'editrow'), until = new Date(c.editUntil);
      row.append(el('span', 'note', c.editUntil === 'always' ? 'Support: edit or delete'
        : 'Entered recently · edit or delete until ' + fmt(until, true) + ' ' + until.toTimeString().slice(0, 5)));
      const eb = el('button', 'btn', 'Edit'), db = el('button', 'btn danger', 'Delete');
      eb.type = db.type = 'button';
      eb.onclick = () => editCase(c.epid); db.onclick = () => deleteCase(c);
      row.append(eb, db); main.append(row);
    }
    const btn = el('button', 'mark', isSeen ? 'Mark unseen' : 'Mark seen'); btn.type = 'button';
    btn.hidden = !needsAction(c);
    btn.onclick = () => { const k = seenKey(c); seen.has(k) ? seen.delete(k) : seen.add(k); keep('seen', [...seen]); renderList(); };
    li.append(timeCell(c), main, btn); feed.append(li);
  }
  $('#seenAll').disabled = !list.some(c => needsAction(c) && !seen.has(seenKey(c)));
}

function setFilter(f) {
  filter = f;
  document.querySelectorAll('.tab').forEach(x => x.setAttribute('aria-selected', x.dataset.f === f));
  renderList();
}

$('#addForm').addEventListener('submit', e => {
  e.preventDefault();
  const v = $('#districtInput').value.trim(); if (!v) return;
  if (watch.some(w => norm(w) === norm(v))) { toast('Already on your watchlist'); return; }
  const match = districts.find(d => norm(d) === norm(v));
  if (!match && DATA.national) { toast(v + ' is not one of the regions.'); return; }
  if (!match) toast('No cases from ' + v + ' yet. Pinned anyway.');
  watch = [...watch, match || v]; keep(WATCH_KEY, watch);
  $('#districtInput').value = ''; renderWatch(); renderList();
});
if (DATA.national) {
  $('#watchLabel').textContent = 'Region watchlist';
  $('#watchLabel').closest('.panel').querySelector('.hint').textContent = 'Pin the regions you follow. Their cases get flagged in the feed and collected under the Watchlist tab.';
  $('label[for=districtInput]').textContent = 'Add a region';
  $('#districtInput').placeholder = 'e.g. Upper East, Volta';
}
$('#tabs').addEventListener('click', e => { const t = e.target.closest('.tab'); if (t) setFilter(t.dataset.f); });
$('#tally').addEventListener('click', e => { const t = e.target.closest('.stat'); if (t) setFilter(t.dataset.f); });
$('#search').addEventListener('input', e => { query = norm(e.target.value); renderList(); });
$('#seenAll').addEventListener('click', () => {
  const n = cases.filter(c => inFilter(c) && inQuery(c) && needsAction(c)).map(seenKey).filter(k => !seen.has(k));
  n.forEach(k => seen.add(k)); keep('seen', [...seen]); renderList(); toast('Marked ' + plural(n.length, 'case') + ' seen');
});
$('#reload').addEventListener('click', () => DATA.live ? refreshData().then(() => toast('Register read again')) : location.reload());

/* ---------- Section switcher ---------- */
function showView(v) {
  if (!VIEWS[v]) v = 'alerts';
  document.querySelectorAll('.view-tab').forEach(b => b.setAttribute('aria-selected', b.dataset.v === v));
  for (const k in VIEWS) $('#v-' + k).hidden = k !== v;
  $('#title').textContent = VIEWS[v];
  if (location.hash.slice(1) !== v) history.replaceState(null, '', '#' + v);
  if (v === 'entry') openEntry();
  if (v === 'upload') openUpload();
  if (v === 'report') renderReport();
}
document.querySelector('.views').addEventListener('click', e => { const b = e.target.closest('.view-tab'); if (b) showView(b.dataset.v); });
window.addEventListener('hashchange', () => showView(location.hash.slice(1)));

function offline(view, what) {
  const box = view.querySelector('.offline'); if (box.childElementCount) return;
  box.hidden = false;
  box.append(el('p', 'label', 'Needs the local app'),
    el('p', 'hl', what + ' writes to the register, so it only works in the copy opened by the local app.'));
  const p = el('p', 'hint'); p.append('Double-click ', el('code', null, 'Start AFP app.cmd'), ' in the project folder (or run ', el('code', null, 'python server.py'), '). It opens this page with ' + what.toLowerCase() + ' switched on.');
  const a = el('a', 'btn solid', 'Open the app'); a.href = DATA.appUrl + '#' + view.id.slice(2); a.style.justifySelf = 'start';
  box.append(p, a);
}

/* ---------- New case ---------- */
let schema = null, autoEpid = '';
const GROUPS = [
  { title: 'Patient', sub: 'Who the case is', match: l => /patient name|sex|birth|age/.test(l) },
  { title: 'Case & place', sub: 'Where it was reported and when paralysis began', match: l => /^sn$|epid|district|week|onset/.test(l) },
  { title: 'Follow-up & lab', sub: 'Optional now. Fill in later here or through Update from file.', match: () => true },
];
const fieldWrap = col => document.querySelector('.field[data-col="' + col + '"]');
const isAuto = f => f.col === schema.snCol || (f.col === schema.codeCol && Object.keys(schema.codeMap).length > 0);
const requiredFields = () => schema.fields.filter(f => f.kind !== 'formula' && f.required && !isAuto(f));

async function openEntry() {
  if (!DATA.live) { offline($('#v-entry'), 'Adding a case'); return; }
  if (editing) return;
  if (schema) return;
  $('#entryLoading').hidden = false;
  try { schema = await api('/api/schema'); buildEntry(); $('#entryBody').hidden = false; $('#saved').hidden = true; }
  catch (e) { toast(e.message); }
  finally { $('#entryLoading').hidden = true; }
}

function autoTag() { return el('span', 'auto', 'Auto'); }
function input(type, id) { const i = el('input', 'in'); i.type = type; i.id = id; return i; }

function fieldEl(f) {
  const id = 'f' + f.col, lc = f.label.toLowerCase();
  const wrap = el('div', 'field'); wrap.dataset.col = f.col;
  const head = el('div', 'fhead'), lab = el('label', null, f.label);
  lab.htmlFor = id; lab.id = id + 'l';
  if (f.required && !isAuto(f)) { const s = el('span', 'req', ' *'); s.setAttribute('aria-hidden', 'true'); lab.append(s); }
  head.append(lab); wrap.append(head);
  let control;
  if (isAuto(f)) {
    control = input('text', id); control.readOnly = true; control.classList.add('mono');
    if (f.col === schema.snCol) control.value = schema.nextSn; else control.placeholder = 'Filled from the district';
    head.append(autoTag());
  } else if (f.kind === 'dropdown' && f.options.length && f.options.length <= 4) {
    control = el('div', 'pills'); control.setAttribute('role', 'radiogroup'); control.setAttribute('aria-labelledby', id + 'l');
    lab.removeAttribute('for');
    f.options.forEach((o, i) => {
      const p = el('label', 'pill'), r = input('radio', id + '_' + i); r.className = ''; r.name = id; r.value = o;
      p.append(r, el('span', null, o)); control.append(p);
    });
  } else if (f.kind === 'dropdown' && f.strict) {
    control = el('select', 'in'); control.id = id;
    const ph = el('option', null, 'Choose…'); ph.value = ''; control.append(ph);
    f.options.forEach(o => { const opt = el('option', null, o); opt.value = o; control.append(opt); });
  } else if (f.kind === 'dropdown') {
    control = input('text', id); control.setAttribute('list', id + 'd'); control.placeholder = 'Type or pick';
    const dl = el('datalist'); dl.id = id + 'd'; f.options.forEach(o => { const opt = el('option'); opt.value = o; dl.append(opt); }); wrap.append(dl);
  } else if (f.kind === 'date' && f.allowAge) {
    control = el('div', 'dob'); control.dataset.mode = 'dob'; control.style.display = 'grid'; control.style.gap = '8px';
    const seg = el('div', 'seg'), bDob = el('button', null, 'Date of birth'), bAge = el('button', null, 'Age in years');
    bDob.type = bAge.type = 'button'; bDob.setAttribute('aria-pressed', 'true'); bAge.setAttribute('aria-pressed', 'false');
    const d = input('date', id); d.max = isoToday; d.classList.add('dobd');
    const a = input('number', id + 'a'); a.classList.add('age'); a.min = 0; a.max = 120; a.step = 'any'; a.placeholder = 'e.g. 4'; a.hidden = true; a.setAttribute('aria-labelledby', id + 'l');
    const mode = m => { control.dataset.mode = m; bDob.setAttribute('aria-pressed', m === 'dob'); bAge.setAttribute('aria-pressed', m === 'age'); d.hidden = m !== 'dob'; a.hidden = m !== 'age'; (m === 'dob' ? d : a).focus(); onEntryInput(); };
    bDob.onclick = () => mode('dob'); bAge.onclick = () => mode('age');
    seg.append(bDob, bAge); control.append(seg, d, a);
  } else if (f.kind === 'date') {
    control = input('date', id); control.max = isoToday;
  } else if (f.kind === 'number') {
    control = input('number', id); control.inputMode = 'numeric'; control.min = 0;
    if (/week/.test(lc)) { control.max = 53; control.placeholder = '1–53'; }
  } else if (/remark|comment/.test(lc)) {
    control = el('textarea', 'in'); control.id = id; control.placeholder = 'Anything the next person should know'; wrap.classList.add('wide');
  } else {
    control = input('text', id); control.maxLength = 200;
  }
  if (f.col === schema.nameCol || f.col === schema.districtCol) wrap.classList.add('wide');
  if (f.col === schema.epidCol) { control.classList.add('mono'); control.placeholder = 'Pick the district to suggest one'; const t = autoTag(); t.id = 'epidAuto'; t.hidden = true; head.append(t); }
  wrap.append(control);
  if (f.col === schema.epidCol) wrap.append(el('span', 'hint', 'Filled in from the district. You can type over it to correct it.'));
  const err = el('p', 'err'); err.id = id + 'e'; err.hidden = true; wrap.append(err);
  return wrap;
}

function buildEntry() {
  const form = $('#entryForm'); form.textContent = ''; autoEpid = '';
  const groups = GROUPS.map(g => ({ ...g, fields: [] }));
  schema.fields.filter(f => f.kind !== 'formula').forEach(f => groups.find(g => g.match(f.label.toLowerCase())).fields.push(f));
  groups.filter(g => g.fields.length).forEach((g, i) => {
    const s = el('section', 'step'), head = el('div', 'step-head');
    s.dataset.cols = g.fields.map(f => f.col).join(',');
    head.append(el('span', 'step-num', String(i + 1)), el('h2', null, g.title), el('p', null, g.sub));
    const grid = el('div', 'grid');
    g.fields.forEach(f => { if (f.col === schema.districtCol && hasRegions()) grid.append(regionEl()); grid.append(fieldEl(f)); });
    s.append(head, grid); form.append(s);
  });
  if (hasRegions()) fillDistricts();
  onEntryInput();
}

/* Org unit: the region picks which districts the Reporting District list offers. The register has no
   region column; the region shows in the EPID # (GHA-UPE-…). */
const hasRegions = () => schema.districtCol && (schema.regions || []).length > 0;
function regionEl() {
  const wrap = el('div', 'field'); wrap.dataset.col = 'region';
  const head = el('div', 'fhead'), lab = el('label', null, 'Region'); lab.htmlFor = 'fRegion';
  const s = el('span', 'req', ' *'); s.setAttribute('aria-hidden', 'true'); lab.append(s);
  head.append(lab, el('span', 'auto', 'Org unit'));
  const sel = el('select', 'in'); sel.id = 'fRegion';
  schema.regions.forEach(r => { const o = el('option', null, r.name + ' Region'); o.value = r.name; sel.append(o); });
  sel.value = schema.homeRegion || schema.regions[0].name;
  sel.disabled = schema.regions.length === 1;  // the region picked on the start page
  wrap.append(head, sel);
  return wrap;
}
function fillDistricts() {
  const r = schema.regions.find(x => x.name === $('#fRegion').value), sel = fieldWrap(schema.districtCol).querySelector('select');
  if (!r || !sel) return;
  const ph = el('option', null, 'Choose a district in ' + r.name + '…'); ph.value = '';
  sel.replaceChildren(ph, ...r.districts.map(([, n]) => { const o = el('option', null, n); o.value = n; return o; }));
}
function onRegion() {
  fillDistricts();
  if (schema.codeCol) setValue(schema.codeCol, '');
  if (schema.epidCol && valueOf(schema.epidCol) === autoEpid) { setValue(schema.epidCol, ''); autoEpid = ''; $('#epidAuto').hidden = true; }
}

function valueOf(col) {
  const w = col != null && fieldWrap(col); if (!w) return '';
  const dob = w.querySelector('.dob'); if (dob) return w.querySelector(dob.dataset.mode === 'age' ? '.age' : '.dobd').value.trim();
  if (w.querySelector('.pills')) { const r = w.querySelector('input:checked'); return r ? r.value : ''; }
  const c = w.querySelector('.in'); return c ? c.value.trim() : '';
}
function setValue(col, v) { const w = fieldWrap(col); const c = w && w.querySelector('.in'); if (c) c.value = v; }
function getRaw() { const raw = {}; schema.fields.forEach(f => { if (f.kind !== 'formula') raw[f.col] = valueOf(f.col); }); return raw; }

function showErr(col, msg) {
  const w = fieldWrap(col); if (!w) { toast(msg); return; }
  w.classList.add('invalid'); const e = w.querySelector('.err'); e.textContent = msg; e.hidden = false;
  const c = w.querySelector('.in, .pills'); if (c) c.setAttribute('aria-describedby', e.id);
}
function clearErr(w) { w.classList.remove('invalid'); const e = w.querySelector('.err'); if (e) e.hidden = true; }
function focusFirstErr() { const w = document.querySelector('.field.invalid'); if (w) { w.scrollIntoView({ behavior: 'smooth', block: 'center' }); const c = w.querySelector('.in:not([hidden]), input'); if (c) c.focus({ preventScroll: true }); } }

function onEntryInput() {
  if (!schema) return;
  const req = requiredFields(), filled = req.filter(f => valueOf(f.col)).length;
  $('#progText').textContent = filled === req.length ? 'All required fields filled' : filled + ' of ' + req.length + ' required fields';
  $('#progFill').style.width = (req.length ? filled / req.length * 100 : 100) + '%';
  document.querySelectorAll('.step').forEach(s => {
    const cols = s.dataset.cols.split(',').map(Number), fs = schema.fields.filter(f => cols.includes(f.col) && !isAuto(f));
    const need = fs.filter(f => f.required);
    s.classList.toggle('complete', need.length ? need.every(f => valueOf(f.col)) : fs.some(f => valueOf(f.col)));
  });
  updateTimeline();
}

function updateTimeline() {
  const c = classify({ onset: valueOf(schema.onsetCol), outcome: valueOf(schema.outcomeCol), report: valueOf(schema.reportCol) });
  const big = $('#tlBig'), badge = $('#tlBadge'), fill = $('#tlFill'), mark = $('#tlMark');
  let pct = 0, text, b = 'Not started', cls = '';
  if (!c.onset) text = 'Enter the date of onset to start the clock';
  else if (c.days < 0) { text = 'That onset date is in the future'; b = 'Check date'; cls = 'past'; }
  else {
    pct = Math.min(c.days / FUP, 1) * 100;
    cls = c.key; b = STATUS[c.key].label;
    text = c.key === 'closed' || c.key === 'report' ? 'Follow-up done · visit due ' + fmt(c.fup, true)
      : c.days > FUP ? 'Follow-up was due ' + fmt(c.fup, true) + ' · ' + plural(c.days - FUP, 'day') + ' ago'
      : 'Day ' + c.days + ' of 60 · follow-up visit ' + (c.left === 0 ? 'due today' : 'due ' + fmt(c.fup, true));
  }
  big.textContent = text; badge.textContent = b; badge.className = 'hero-badge ' + cls;
  fill.className = cls === 'past' || cls === 'soon' ? cls : ''; fill.style.width = pct + '%'; mark.style.left = pct + '%';
  $('#tlStart').textContent = c.onset ? 'Onset ' + fmt(c.onset, true) : 'Onset';
  $('#tlEnd').textContent = c.fup ? 'Day 60 · ' + fmt(c.fup, true) : 'Day 60 · follow-up visit';
  const chips = $('#tlChips'); chips.textContent = '';
  [['SN', valueOf(schema.snCol)], ['Row', schema.nextRow], ['', valueOf(schema.epidCol)], ['', valueOf(schema.districtCol)]]
    .forEach(([k, v]) => { if (v) chips.append(el('span', null, (k ? k + ' ' : '') + v)); });
}

async function onDistrict() {
  const code = schema.codeMap[valueOf(schema.districtCol)];
  if (!code) return;
  if (schema.codeCol) setValue(schema.codeCol, code);
  const cur = valueOf(schema.epidCol);
  if (schema.epidCol && (!cur || cur === autoEpid)) {
    try {
      const r = await api('/api/next-epid?code=' + encodeURIComponent(code) + (hasRegions() ? '&region=' + encodeURIComponent($('#fRegion').value) : ''));
      autoEpid = r.epid; setValue(schema.epidCol, autoEpid); $('#epidAuto').hidden = false; clearErr(fieldWrap(schema.epidCol));
    } catch (_) {}
  }
  onEntryInput();
}

$('#entryForm').addEventListener('input', e => {
  const w = e.target.closest('.field'); if (w) clearErr(w);
  if (w && Number(w.dataset.col) === schema.epidCol) $('#epidAuto').hidden = valueOf(schema.epidCol) !== autoEpid;
  onEntryInput();
});
$('#entryForm').addEventListener('change', e => {
  const w = e.target.closest('.field');
  if (w && w.dataset.col === 'region') onRegion();
  if (w && Number(w.dataset.col) === schema.districtCol) onDistrict();
  onEntryInput();
});

/* ---------- Editing or deleting a case within 24 hours of entering it (regional accounts) ---------- */
let editing = null;  // {epid, until} while the form holds a case being edited
function fillValue(col, v) {
  const w = fieldWrap(col); if (!w || v == null) return;
  const dob = w.querySelector('.dob');
  if (dob) {
    const isAge = !/^\d{4}-\d{2}-\d{2}$/.test(v);
    w.querySelector('.seg button:' + (isAge ? 'last-child' : 'first-child')).click();
    w.querySelector(isAge ? '.age' : '.dobd').value = v; return;
  }
  const pills = w.querySelector('.pills');
  if (pills) { pills.querySelectorAll('input').forEach(r => r.checked = r.value === v); return; }
  const c = w.querySelector('.in'); if (!c) return;
  if (c.tagName === 'SELECT' && ![...c.options].some(o => o.value === v)) { const o = el('option', null, v); o.value = v; c.append(o); }
  c.value = v;
}
function endEdit() {
  editing = null; $('#editBar').hidden = true; $('#saveBtn').textContent = 'Save case'; $('#clearBtn').hidden = false;
}
async function editCase(epid) {
  try {
    const r = await api('/api/case?epid=' + encodeURIComponent(epid));
    editing = { epid: r.epid, until: r.until ? new Date(r.until) : null };
    showView('entry');
    if (!schema) schema = await api('/api/schema');
    buildEntry(); $('#entryBody').hidden = false; $('#saved').hidden = true;
    if (hasRegions()) { $('#fRegion').value = r.region; fillDistricts(); }
    Object.entries(r.fields).forEach(([col, v]) => fillValue(Number(col), v));
    $('#editText').textContent = 'Editing ' + r.epid + (editing.until ? ' · changes allowed until ' + fmt(editing.until, true) + ' ' + editing.until.toTimeString().slice(0, 5) : ' · support');
    $('#editBar').hidden = false; $('#saveBtn').textContent = 'Save changes'; $('#clearBtn').hidden = true;
    onEntryInput(); window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) { editing = null; toast(e.message); }
}
async function deleteCase(c) {
  if (!confirm('Delete ' + (c.name ? c.name + ' · ' : '') + c.epid + ' from the register?\n\nThis removes its row. A backup of the register is kept next to it.')) return;
  try {
    await api('/api/case/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ epid: c.epid }) });
    toast(c.epid + ' deleted');
    if (editing && editing.epid === c.epid) { endEdit(); schema = null; showView('alerts'); }
    refreshData();
  } catch (e) { toast(e.message); }
}
$('#editCancel').addEventListener('click', () => { endEdit(); schema = null; showView('alerts'); });
$('#editDelete').addEventListener('click', () => { if (editing) deleteCase(cases.find(c => c.epid === editing.epid) || { epid: editing.epid }); });

$('#entryForm').addEventListener('submit', async e => {
  e.preventDefault();
  document.querySelectorAll('.field.invalid').forEach(clearErr);
  const missing = requiredFields().filter(f => !valueOf(f.col));
  if (missing.length) { missing.forEach(f => showErr(f.col, f.label + ' is required.')); focusFirstErr(); toast('Fill in the highlighted fields'); return; }
  const btn = $('#saveBtn'); btn.disabled = true; btn.textContent = 'Saving…';
  if (editing) {
    try {
      const r = await api('/api/case/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ epid: editing.epid, fields: getRaw() }) });
      toast(r.epid + ' updated'); endEdit(); schema = null; showView('alerts'); refreshData();
    } catch (err) {
      if (err.body && err.body.errors) { err.body.errors.forEach(x => showErr(x.col, x.msg)); focusFirstErr(); toast('Check the highlighted fields'); }
      else toast(err.message);
    } finally { btn.disabled = false; if (editing) btn.textContent = 'Save changes'; }
    return;
  }
  try {
    const r = await api('/api/cases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fields: getRaw() }) });
    $('#savedName').textContent = [r.name, r.epid].filter(Boolean).join(' · ');
    $('#savedNote').textContent = 'Added as row ' + r.row + ' of ' + DATA.source + '. A backup of the previous version was kept next to it.';
    $('#saved').dataset.epid = r.epid || '';
    $('#entryBody').hidden = true; $('#saved').hidden = false; window.scrollTo({ top: 0, behavior: 'smooth' });
    schema = null; refreshData();
  } catch (err) {
    if (err.body && err.body.errors) { err.body.errors.forEach(x => showErr(x.col, x.msg)); focusFirstErr(); toast('Check the highlighted fields'); }
    else toast(err.message);
  } finally { btn.disabled = false; btn.textContent = 'Save case'; }
});
$('#clearBtn').addEventListener('click', () => { buildEntry(); window.scrollTo({ top: 0, behavior: 'smooth' }); });
$('#addAnother').addEventListener('click', () => { $('#saved').hidden = true; openEntry(); });
$('#viewSaved').addEventListener('click', () => {
  const epid = $('#saved').dataset.epid;
  showView('alerts'); setFilter('all'); $('#search').value = epid; query = norm(epid); renderList();
});

/* ---------- Update from file ---------- */
let upFile = null;
function openUpload() { if (!DATA.live) { offline($('#v-upload'), 'Updating from a file'); return; } $('#uploadBody').hidden = false; }

const drop = $('#drop');
drop.addEventListener('click', () => $('#fileInput').click());
$('#fileInput').addEventListener('change', e => { if (e.target.files[0]) preview(e.target.files[0]); e.target.value = ''; });
['dragenter', 'dragover'].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach(t => drop.addEventListener(t, () => drop.classList.remove('over')));
drop.addEventListener('drop', e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) preview(f); });
$('#addNew').addEventListener('change', () => { if (upFile) preview(upFile); });
$('#planCancel').addEventListener('click', () => { upFile = null; $('#plan').hidden = true; });
$('#planApply').addEventListener('click', () => upFile && preview(upFile, true));

async function preview(file, apply = false) {
  if (!/\.(xlsx|xlsm|csv)$/i.test(file.name)) { toast('Choose an .xlsx or .csv file'); return; }
  if (file.size > 10 * 1024 * 1024) { toast('That file is over 10 MB'); return; }
  upFile = file;
  const btn = $('#planApply'), label = btn.textContent; btn.disabled = true; if (apply) btn.textContent = 'Applying…';
  try {
    const q = '?name=' + encodeURIComponent(file.name) + '&add=' + ($('#addNew').checked ? 1 : 0) + (apply ? '&apply=1' : '');
    const plan = await api('/api/import' + q, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
    if (apply) {
      toast('Updated ' + plural(plan.changes.length, 'case') + (plan.adds.length ? ' and added ' + plural(plan.adds.length, 'new case') : ''));
      upFile = null; $('#plan').hidden = true; schema = null; refreshData();
    } else renderPlan(file, plan);
  } catch (e) {
    toast(e.message);
    if (apply) { btn.disabled = false; btn.textContent = label; } else { upFile = null; $('#plan').hidden = true; }
  }
}

function renderPlan(file, p) {
  $('#plan').hidden = false;
  $('#planLabel').textContent = 'Review · ' + file.name;
  $('#planNote').textContent = plural(p.rows, 'row') + ' read, ' + p.matched + ' matched';
  const tally = $('#planTally'); tally.textContent = '';
  [['report', p.changes.length, 'Cases updated'], ['closed', p.cellCount, 'Cells changed'], ['soon', p.adds.length, 'New cases'], ['past', p.errors.length, 'Problems']]
    .forEach(([cls, n, t]) => { const s = el('div', 'stat ' + cls); s.append(el('b', null, String(n)), el('span', null, t)); tally.append(s); });
  const body = $('#planBody'); body.textContent = '';
  const group = (title, items) => { if (!items.length) return; const g = el('div', 'plan-group'); g.append(el('p', 'label', title), ...items); body.append(g); };
  group('Changes', p.changes.map(c => {
    const d = el('div', 'change'); d.append(el('p', 'hl', c.name || c.epid), el('span', 'epid', c.epid));
    c.cells.forEach(x => { const r = el('div', 'cell'); r.append(el('span', 'tag', x.field), el('span', 'old', x.old), el('span', 'arrow', '→'), el('span', 'new', x.new)); d.append(r); });
    return d;
  }));
  group('New cases', p.adds.map(a => { const d = el('div', 'change'); d.append(el('p', 'hl', a.name || a.epid), el('span', 'epid', a.epid)); return d; }));
  group('Problems · these cells or rows are skipped', p.errors.map(x => { const d = el('div', 'problem'); d.append(el('b', null, x.epid + ' · ' + x.field + ' '), x.msg); return d; }));
  if (p.unmatched.length) group('Not in the register · skipped', [el('p', 'hint', p.unmatched.join(', ') + '. Tick “Also add rows…” above to add them as new cases.')]);
  const notes = [];
  if (p.ignored.length) notes.push('Calculated columns ignored: ' + p.ignored.join(', ') + '.');
  if (p.unknown.length) notes.push('Columns not in the register, ignored: ' + p.unknown.join(', ') + '.');
  if (notes.length) group('Columns', notes.map(n => el('p', 'hint', n)));
  const n = p.cellCount + p.adds.length;
  if (!n) body.append(el('p', 'hint', p.errors.length || p.unmatched.length ? 'Nothing in this file can be applied yet.' : 'Every value in this file already matches the register. Nothing to change.'));
  const btn = $('#planApply');
  btn.disabled = !n;
  btn.textContent = n ? 'Apply ' + [p.cellCount ? plural(p.cellCount, 'change') : '', p.adds.length ? plural(p.adds.length, 'new case') : ''].filter(Boolean).join(' + ') : 'Nothing to apply';
  $('#planWarn').textContent = n ? 'The register is backed up before saving. Close it in Excel first.' : '';
  $('#plan').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ---------- District report ---------- */
// In the national view (Ghana) the rows are the regions instead of the districts.
const HEAD = ['SN.', DATA.national ? 'REGION' : 'DISTRICT/MUNICIPALITY', 'NUMBER OF CASES DETECTED', '60 DAY FOLLOW UP REPORTS RECEIVED'];
if (DATA.national) { $('#repUnitHead').textContent = 'Region'; $('#repTotalLabel').textContent = 'National total'; }
function caseYear(c) {
  if (c.onset) return c.onset.getFullYear();
  const m = /-(\d{2})-\d+$/.exec(c.epid || ''); return m ? 2000 + Number(m[1]) : null;
}
function caseCode(c) { return String(c.code || (c.epid || '').split('-')[2] || '').trim().toUpperCase(); }

function fillYears() {
  const sel = $('#repYear'), prev = sel.value;
  const years = [...new Set(cases.map(caseYear).filter(Boolean).concat(today.getFullYear()))].sort((a, b) => b - a);
  sel.textContent = ''; years.forEach(y => { const o = el('option', null, String(y)); o.value = y; sel.append(o); });
  const latest = years.find(y => cases.some(c => caseYear(c) === y)) || years[0];
  sel.value = prev && years.includes(Number(prev)) ? prev : String(latest);
}

function computeReport() {
  const year = Number($('#repYear').value), fromW = Number($('#repFrom').value) || 0, toW = Number($('#repTo').value) || 0;
  const byWeek = fromW || toW, lo = fromW || 1, hi = toW || 53;
  const rows = DATA.districts.map(([code, name], i) => ({ sn: i + 1, code, name, cases: 0, reports: 0 }));
  const other = { sn: '', name: DATA.national ? 'Other / region not matched' : 'Other / district not matched', cases: 0, reports: 0, other: true };
  cases.forEach(c => {
    if (caseYear(c) !== year) return;
    const w = Number(c.week);
    if (byWeek && !(w >= lo && w <= hi)) return;
    const r = rows.find(r => r.code === caseCode(c)) || other;
    r.cases++; if (norm(c.report) === 'yes') r.reports++;
  });
  if (other.cases) rows.push(other);
  const total = rows.reduce((t, r) => ({ cases: t.cases + r.cases, reports: t.reports + r.reports }), { cases: 0, reports: 0 });
  const period = byWeek ? ', EPI WEEKS ' + lo + '–' + hi : '';
  const title = 'NUMBER OF AFP CASES DETECTED BY ' + (DATA.national ? 'REGION, GHANA' : 'DISTRICT/MUNICIPALITY, ' + DATA.region.toUpperCase()) + ', ' + year + period;
  const pct = total.cases ? Math.round(total.reports / total.cases * 100) + '%' : '–';
  const foot = 'Source: AFP 60-day follow-up register (' + DATA.source + '). Cases are counted by year of onset of paralysis'
    + (byWeek ? ' and epi weeks ' + lo + ' to ' + hi : '') + '; a follow-up report counts as received where Report Availability is "Yes". '
    + 'Follow-up report completeness: ' + total.reports + ' of ' + total.cases + ' (' + pct + '). Generated ' + fmt(new Date(), true) + '.';
  const rights = '© ' + new Date().getFullYear() + ' ' + DATA.org + '. All rights reserved.';
  const file = 'AFP cases by ' + (DATA.national ? 'region ' : 'district ') + year + (byWeek ? ' wk' + lo + '-' + hi : '');
  return { year, title, rows, total, foot, rights, file, pct };
}

function renderReport() {
  if (!$('#repYear').options.length) fillYears();
  const r = computeReport();
  $('#repTitle').textContent = r.title;
  const body = $('#repBody'); body.textContent = '';
  r.rows.forEach(x => {
    const tr = el('tr', x.other ? 'other' : '');
    tr.append(el('td', 'sn', String(x.sn)), el('td', null, x.name), el('td', 'num', String(x.cases)), el('td', 'num', String(x.reports)));
    body.append(tr);
  });
  $('#repCases').textContent = r.total.cases; $('#repReports').textContent = r.total.reports;
  $('#repFoot').textContent = r.foot;
  $('#repRights').textContent = r.rights;
  $('#repNote').textContent = plural(r.total.cases, 'case') + ' · ' + r.pct + ' reports received';
  return r;
}
['#repYear', '#repFrom', '#repTo'].forEach(s => $(s).addEventListener('input', renderReport));
const paper = paperPicker($('#repPaper'), 'afpwo.reportPaper', '#ffffff', hex => $('#sheet').style.setProperty('--paper', hex));

function download(blob, name) {
  const a = el('a'); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
function wrapText(ctx, text, max) {
  const lines = []; let line = '';
  text.split(' ').forEach(w => { const t = line ? line + ' ' + w : w; if (ctx.measureText(t).width > max && line) { lines.push(line); line = w; } else line = t; });
  if (line) lines.push(line); return lines;
}

// Draws the report straight onto a canvas (no external library), at 2x for a sharp PNG.
function reportCanvas(r) {
  const COLS = [56, 470, 320, 340], TW = COLS.reduce((a, b) => a + b, 0), PAD = 44, S = 2;
  const font = (px, weight = 'bold', style = '') => (style + ' ' + weight + ' ' + px + 'px "Times New Roman", Times, serif').trim();
  const probe = document.createElement('canvas').getContext('2d');
  probe.font = font(25); const titleLines = wrapText(probe, r.title, TW - 40);
  probe.font = font(15, 'normal', 'italic'); const footLines = wrapText(probe, r.foot, TW);
  probe.font = font(20); const headLines = HEAD.map((h, i) => wrapText(probe, h, COLS[i] - 16));
  const TH = titleLines.length * 32 + 22, HH = Math.max(...headLines.map(l => l.length)) * 25 + 22, RH = 48;
  const logo = $('#repLogo'), LH = logo && logo.complete && logo.naturalWidth ? 104 : 0;
  const H = PAD + LH + TH + HH + RH * (r.rows.length + 1) + 18 + (footLines.length + 1) * 21 + 6 + PAD;
  const cv = document.createElement('canvas'); cv.width = (TW + PAD * 2) * S; cv.height = H * S;
  const ctx = cv.getContext('2d'); ctx.scale(S, S);
  ctx.fillStyle = paper(); ctx.fillRect(0, 0, TW + PAD * 2, H);
  ctx.fillStyle = '#000'; ctx.strokeStyle = '#000'; ctx.lineWidth = 1.2;
  if (LH) { const lh = LH - 18, lw = lh * logo.naturalWidth / logo.naturalHeight; ctx.drawImage(logo, PAD + (TW - lw) / 2, PAD - 6, lw, lh); }
  let y = PAD + LH + 26; ctx.font = font(25); ctx.textAlign = 'center';
  titleLines.forEach(l => { ctx.fillText(l, PAD + TW / 2, y); y += 32; });
  const top = PAD + LH + TH, xs = COLS.reduce((a, w) => (a.push(a[a.length - 1] + w), a), [PAD]);
  const cell = (text, col, rowTop, align, f) => {
    ctx.font = f; ctx.textAlign = align;
    ctx.fillText(text, align === 'center' ? (xs[col] + xs[col + 1]) / 2 : xs[col] + 8, rowTop + RH - 13);
  };
  headLines.forEach((lines, i) => {
    ctx.font = font(20); ctx.textAlign = i > 1 ? 'center' : 'left';
    const x = i > 1 ? (xs[i] + xs[i + 1]) / 2 : xs[i] + 8;
    lines.forEach((l, k) => ctx.fillText(l, x, top + HH - 13 - (lines.length - 1 - k) * 25));
  });
  r.rows.forEach((row, k) => {
    const t = top + HH + k * RH;
    cell(String(row.sn), 0, t, 'left', font(20));
    cell(row.name.toUpperCase(), 1, t, 'left', font(20, 'bold', row.other ? 'italic' : ''));
    cell(String(row.cases), 2, t, 'center', font(21, 'normal'));
    cell(String(row.reports), 3, t, 'center', font(21, 'normal'));
  });
  const tt = top + HH + r.rows.length * RH, bottom = tt + RH;
  cell(DATA.national ? 'NATIONAL TOTAL' : 'REGIONAL TOTAL', 0, tt, 'left', font(20));
  cell(String(r.total.cases), 2, tt, 'center', font(21));
  cell(String(r.total.reports), 3, tt, 'center', font(21));
  ctx.beginPath();
  ctx.rect(PAD, top, TW, bottom - top);
  for (let k = 0; k <= r.rows.length; k++) { const ly = top + HH + k * RH; ctx.moveTo(PAD, ly); ctx.lineTo(PAD + TW, ly); }
  xs.slice(1, -1).forEach((x, i) => { ctx.moveTo(x, top); ctx.lineTo(x, i === 0 ? tt : bottom); });
  ctx.stroke();
  ctx.fillStyle = '#333'; ctx.font = font(15, 'normal', 'italic'); ctx.textAlign = 'left';
  footLines.forEach((l, k) => ctx.fillText(l, PAD, bottom + 26 + k * 21));
  ctx.fillStyle = '#555'; ctx.font = font(14, 'normal'); ctx.fillText(r.rights, PAD, bottom + 32 + footLines.length * 21);
  return cv;
}

$('#expPng').addEventListener('click', () => {
  const r = renderReport();
  reportCanvas(r).toBlob(b => { download(b, r.file + '.png'); toast('Image saved'); }, 'image/png');
});
$('#expPdf').addEventListener('click', () => {
  const r = renderReport(), title = document.title;
  document.title = r.file; document.body.classList.add('print-report');
  const done = () => { document.body.classList.remove('print-report'); document.title = title; window.removeEventListener('afterprint', done); };
  window.addEventListener('afterprint', done);
  toast('Choose “Save as PDF” as the printer');
  setTimeout(() => window.print(), 50);
});
$('#expXlsx').addEventListener('click', async () => {
  const r = renderReport();
  const rows = r.rows.map(x => [x.sn, x.name.toUpperCase(), x.cases, x.reports]);
  if (!DATA.live) {
    const q = v => '"' + String(v).replace(/"/g, '""') + '"';
    const csv = [[r.title], HEAD, ...rows, [DATA.national ? 'NATIONAL TOTAL' : 'REGIONAL TOTAL', '', r.total.cases, r.total.reports], [], [r.foot], [r.rights]].map(l => l.map(q).join(',')).join('\r\n');
    download(new Blob(['﻿' + csv], { type: 'text/csv' }), r.file + '.csv');
    toast('Saved as CSV, which opens in Excel. Start the local app for a formatted .xlsx.');
    return;
  }
  const btn = $('#expXlsx'); btn.disabled = true;
  try {
    const res = await fetch('/api/report.xlsx', { method: 'POST', headers: { 'X-CSRFToken': csrfToken(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: r.title, header: HEAD, rows, totalLabel: DATA.national ? 'NATIONAL TOTAL' : 'REGIONAL TOTAL', foot: r.foot, rights: r.rights, paper: paper() }) });
    if (!res.ok) throw new Error('Excel export failed (' + res.status + ').');
    download(await res.blob(), r.file + '.xlsx'); toast('Excel file saved');
  } catch (e) { toast(e.message); } finally { btn.disabled = false; }
});

// In the app, the region link goes back to the start page to pick another region.
document.querySelectorAll('.modules a').forEach(a => { if (DATA.live) a.href = { afp: '/', idsr: '/idsr', men: '/meningitis', sms: '/reminders', start: '/start', admin: '/admin', profile: '/profile?next=' + encodeURIComponent('/'), logout: '/logout' }[a.dataset.m]; else if (['start', 'admin', 'profile', 'logout', 'men', 'sms'].includes(a.dataset.m)) a.remove(); });
document.querySelectorAll('.region-link, .signout').forEach(a => a.hidden = false);

// The support account gets its Accounts page link (and, on these pages, its extra tools).
let ROLE = 'regional';
if (DATA.live) fetch('/api/me', { headers: { 'X-CSRFToken': csrfToken() } }).then(r => r.ok ? r.json() : null).then(me => {
  if (!me) return;
  ROLE = me.role;
  document.querySelectorAll('.adminlink').forEach(a => a.hidden = ROLE !== 'support');
  if (typeof onRole === 'function') onRole();
}).catch(() => {});
document.querySelectorAll('.year').forEach(e => e.textContent = new Date().getFullYear());
setData(DATA);
showView(location.hash.slice(1));
