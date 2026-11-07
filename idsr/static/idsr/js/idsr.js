let DATA = JSON.parse(document.getElementById('page-data').textContent);
const VIEWS = { entry: 'Data entry', upload: 'Upload Excel/CSV', dhims2: 'Fetch data from DHIMS2', report: 'Weekly bulletin' };
const DAY = 864e5;
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 3600); }
function norm(s) { return String(s ?? '').trim().toLowerCase(); }
function plural(n, w, p) { return n + ' ' + (n === 1 ? w : (p || w + 's')); }
const pad = (n, k = 2) => String(n).padStart(k, '0');
const pad3 = w => pad(w, 3);
function asDate(s) { if (typeof s !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(s)) return null; const [y, m, d] = s.slice(0, 10).split('-').map(Number); return new Date(y, m - 1, d); }
const isoOf = d => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
const dmy = d => d ? pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + '/' + d.getFullYear() : '';
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
function ordinal(n) { const s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
function span(a, b) {  // 19–25 October 2026, or 28 September – 4 October 2026
  if (!a || !b) return '';
  if (a.getMonth() === b.getMonth()) return a.getDate() + '–' + b.getDate() + ' ' + MONTHS[b.getMonth()] + ' ' + b.getFullYear();
  return a.getDate() + ' ' + MONTHS[a.getMonth()] + (a.getFullYear() !== b.getFullYear() ? ' ' + a.getFullYear() : '') + ' – ' + b.getDate() + ' ' + MONTHS[b.getMonth()] + ' ' + b.getFullYear();
}
const today = new Date(); today.setHours(0, 0, 0, 0);

// ISO epi weeks: Monday to Sunday, week 1 holds the year's first Thursday.
function weekStart(y, w) { const jan4 = new Date(y, 0, 4); return new Date(y, 0, 4 - (jan4.getDay() + 6) % 7 + (w - 1) * 7); }
function weekOf(d) {
  const t = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 3 - (d.getDay() + 6) % 7), jan4 = new Date(t.getFullYear(), 0, 4);
  return [t.getFullYear(), 1 + Math.round(((t - jan4) / DAY - 3 + (jan4.getDay() + 6) % 7) / 7)];
}
const weeksIn = y => weekOf(new Date(y, 11, 28))[1];
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
// Dates of an epi week, worked out from the year and week: Monday to Sunday, and the bulletin is published
// on the Thursday after the week ends, as the regional bulletins are.
function weekDates(y, w) { const start = weekStart(y, w); return { start, end: addDays(start, 6), pub: addDays(start, 10) }; }

let D = [], COLS = [], BYKEY = {}, WEEKS = new Map();
function setData(d) {
  DATA = d;
  D = DATA.diseases; COLS = D.flatMap(x => x.measures.map(m => x.key + '.' + m));
  BYKEY = Object.fromEntries(D.map(x => [x.key, x]));
  WEEKS = new Map(DATA.weeks.map(w => [w.year + '-' + w.week, w]));
  renderStatus(); renderOrgUnit(); fillWeekPickers();
  if (!$('#v-report').hidden) renderBulletin();
}
// Every call carries the region picked in the org unit bar, so it reads and saves that region's file.
const withRegion = path => path + (path.includes('?') ? '&' : '?') + 'region=' + encodeURIComponent(DATA.region || '');
async function api(path, opts = {}) {
  const r = await fetch(withRegion(path), { ...opts, headers: { 'X-CSRFToken': csrfToken(), ...(opts.headers || {}) } });
  let body = null; try { body = await r.json(); } catch (_) {}
  if (!r.ok) throw Object.assign(new Error((body && body.error) || 'Something went wrong (' + r.status + ').'), { status: r.status, body });
  return body;
}
const postJson = (path, obj) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(obj) });
const regionName = () => DATA.national ? DATA.region + ' (all regions)' : DATA.region ? (/region$/i.test(DATA.region) ? DATA.region : DATA.region + ' Region') : 'Region';
// The national view (Ghana) has the regions as its rows, where a region's pages have its districts.
const UNIT = DATA.national ? 'region' : 'district';
const grid = (y, w) => DATA.counts[y + '-' + w] || {};
function sum(g, col) { let t = 0; for (const code in g) t += (g[code] || {})[col] || 0; return t; }

function renderStatus() {
  const n = DATA.weeks.length, last = DATA.weeks[n - 1];
  $('#dot').className = 'dot ' + (DATA.live ? 'live' : '');
  $('#statusText').textContent = (DATA.live ? 'Live · ' : 'Read-only copy · ') + plural(n, 'week') + ' on file' + (last ? ' · latest wk ' + pad3(last.week) + ' ' + last.year : '');
  $('#regionSlug').textContent = (DATA.region || 'REGION').toUpperCase();
}

/* ---------- Sections ---------- */
function showView(v) {
  if (!VIEWS[v]) v = 'report';
  document.querySelectorAll('.view-tab').forEach(b => b.setAttribute('aria-selected', b.dataset.v === v));
  for (const k in VIEWS) $('#v-' + k).hidden = k !== v;
  $('#title').textContent = VIEWS[v];
  if (location.hash.slice(1) !== v) history.replaceState(null, '', '#' + v);
  if (v === 'entry') openEntry();
  if (v === 'upload') openUpload();
  if (v === 'dhims2') openDhims();
  if (v === 'report') renderBulletin();
}
document.querySelector('.views').addEventListener('click', e => { const b = e.target.closest('.view-tab'); if (b) showView(b.dataset.v); });
window.addEventListener('hashchange', () => showView(location.hash.slice(1)));
function offline(view, what) {
  const box = view.querySelector('.offline'); if (box.childElementCount) return;
  box.hidden = false;
  box.append(el('p', 'label', 'Needs the local app'), el('p', 'hl', what + ' saves to ' + DATA.source + ', so it only works in the copy opened by the local app.'));
  const p = el('p', 'hint'); p.append('Double-click ', el('code', null, 'Start Weekly IDSR.cmd'), ' in the project folder (or run ', el('code', null, 'python server.py --idsr'), ').');
  const a = el('a', 'btn solid', 'Open the app'); a.href = DATA.appUrl + 'idsr#' + view.id.slice(2); a.style.justifySelf = 'start';
  box.append(p, a);
}

/* ---------- Data entry ---------- */
let entryBuilt = false, dirty = false, cur = null;
const metaInputs = () => [...document.querySelectorAll('#weekForm [data-k]')];
function defaultWeek() { const [y, w] = weekOf(new Date(today.getTime() - 7 * DAY)); return [y, w]; }

function buildGrids() {
  const box = $('#grids'); box.textContent = '';
  [0, 1, 2, 3].forEach(b => {
    const ds = D.filter(x => x.block === b);
    const wrap = el('div', 'cblock'), title = el('div', 'cblock-title');
    title.append(el('b', null, 'Table ' + (b + 1)), el('span', 'note', ds.map(x => x.short).join(' · ')));
    const tw = el('div', 'cgrid-wrap'), t = el('table', 'cgrid'); t.dataset.b = b;
    const thead = el('thead'), h1 = el('tr'), h2 = el('tr');
    const dh = el('th', 'dcol', DATA.national ? 'Region' : 'District'); dh.rowSpan = 2; h1.append(dh);
    ds.forEach((x, i) => {
      const th = el('th', i % 2 ? 'g1' : '', x.short); th.colSpan = x.measures.length; th.title = x.name; h1.append(th);
      x.measures.forEach(m => { const s = el('th', i % 2 ? 'g1' : '', m === 'Rumour' ? 'RUM' : m); s.title = DATA.measures[m]; h2.append(s); });
    });
    thead.append(h1, h2);
    const tb = el('tbody');
    DATA.districts.forEach(([code, name], r) => {
      const tr = el('tr'); tr.append(el('th', 'dcol', name));
      let i = 0;
      ds.forEach((x, k) => x.measures.forEach(m => {
        const td = el('td', k % 2 ? 'g1' : ''), inp = el('input', 'cnt');
        inp.inputMode = 'numeric'; inp.placeholder = '0'; inp.maxLength = 5; inp.autocomplete = 'off';
        inp.dataset.d = code; inp.dataset.c = x.key + '.' + m; inp.dataset.r = r; inp.dataset.i = i++;
        inp.setAttribute('aria-label', name + ', ' + x.short + ' ' + DATA.measures[m]);
        td.append(inp); tr.append(td);
      }));
      tb.append(tr);
    });
    const tf = el('tfoot'), fr = el('tr'); fr.append(el('th', 'dcol', 'Total'));
    ds.forEach((x, k) => x.measures.forEach(m => { const td = el('td', k % 2 ? 'g1' : '', '0'); td.dataset.tot = x.key + '.' + m; fr.append(td); }));
    tf.append(fr);
    t.append(thead, tb, tf); tw.append(t); wrap.append(title, tw); box.append(wrap);
  });
}

function readGrid() {
  const out = {};
  document.querySelectorAll('.cnt').forEach(i => { (out[i.dataset.d] ||= {})[i.dataset.c] = Number(i.value) || 0; });
  return out;
}
function readMeta() {
  const m = {};
  metaInputs().forEach(i => m[i.dataset.k] = i.value.trim());
  return m;
}

function loadWeek(y, w) {
  cur = [y, w];
  $('#fYear').value = y; $('#fWeek').value = w;
  const saved = WEEKS.get(y + '-' + w), g = grid(y, w), wd = weekDates(y, w);
  const auto = { start: isoOf(wd.start), end: isoOf(wd.end), published: isoOf(wd.pub) };
  metaInputs().forEach(i => { const k = i.dataset.k, v = k in auto ? auto[k] : saved ? saved[k] : ''; i.value = v == null ? '' : v; });
  document.querySelectorAll('.cnt').forEach(i => { const v = (g[i.dataset.d] || {})[i.dataset.c]; i.value = v ? v : ''; });
  if (!saved && !$('#fExpected').value) $('#fExpected').value = DATA.districts.length || '';
  $('#wkBadge').textContent = saved ? 'On file · editing' : 'New week';
  $('#saveBtn').textContent = saved ? 'Update week ' + pad3(w) : 'Save week ' + pad3(w);
  $('#delWeekBtn').hidden = !(saved && ROLE === 'support');
  dirty = false; refreshEntry();
}

function refreshEntry() {
  const y = Number($('#fYear').value), w = Number($('#fWeek').value);
  $('#wkBig').textContent = 'Week ' + pad3(w || 0) + ' · ' + (y || '');
  $('#wkSub').textContent = span(asDate($('#fStart').value), asDate($('#fEnd').value));
  const e = Number($('#fExpected').value), r = $('#fReceived').value === '' ? null : Number($('#fReceived').value), t = $('#fOntime').value === '' ? null : Number($('#fOntime').value);
  const pct = (n) => e && n != null ? Math.round(n / e * 100) : null;
  [['#hsComp', '#hsCompBar', pct(r)], ['#hsTime', '#hsTimeBar', pct(t)]].forEach(([b, bar, p]) => {
    $(b).textContent = p == null ? '–' : p + '%'; $(bar).style.setProperty('--p', Math.min(p || 0, 100) + '%'); $(bar).classList.toggle('none', p == null);
  });
  let cases = 0, deaths = 0; const tot = {};
  document.querySelectorAll('.cnt').forEach(i => {
    const v = Number(i.value) || 0, m = i.dataset.c.split('.')[1];
    i.classList.toggle('hot', v > 0); i.classList.toggle('dead', v > 0 && m === 'D');
    tot[i.dataset.c] = (tot[i.dataset.c] || 0) + v;
    if (m === 'CS') cases += v; if (m === 'D') deaths += v;
  });
  document.querySelectorAll('[data-tot]').forEach(td => { const v = tot[td.dataset.tot] || 0; td.textContent = v; td.classList.toggle('hot', v > 0); });
  $('#hsCases').textContent = cases; $('#hsDeaths').textContent = deaths;
  const chips = $('#wkChips'); chips.textContent = '';
  D.map(x => [x, tot[x.key + '.CS'] || tot[x.key + '.D'] || 0]).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).slice(0, 8)
    .forEach(([x, v]) => chips.append(el('span', null, x.short + ' ' + v)));
  if (!chips.childElementCount) chips.append(el('span', null, 'No cases entered yet'));
  const filled = DATA.districts.filter(([code]) => [...document.querySelectorAll('.cnt[data-d="' + code + '"]')].some(i => i.value !== '')).length;
  $('#progText').textContent = plural(filled, 'district') + ' with cases · ' + plural(cases, 'suspected case') + (dirty ? ' · unsaved' : '');
  $('#progFill').style.width = (DATA.districts.length ? filled / DATA.districts.length * 100 : 0) + '%';
}

function openEntry() {
  if (!DATA.live) { offline($('#v-entry'), 'Entering a week'); return; }
  if (!DATA.districts.length) { offline($('#v-entry'), 'Entering a week'); return; }
  if (!entryBuilt) { buildGrids(); entryBuilt = true; $('#entryBody').hidden = false; loadWeek(...(cur || defaultWeek())); }
}
function goWeek(y, w) {
  if (!(y >= 2000 && y <= 2100) || !(w >= 1)) return;
  if (w > weeksIn(y)) { y++; w = 1; }
  if (cur && dirty && (cur[0] !== y || cur[1] !== w) && !confirm('Week ' + pad3(cur[1]) + ' has unsaved changes. Discard them?')) {
    $('#fYear').value = cur[0]; $('#fWeek').value = cur[1]; return;
  }
  loadWeek(y, w);
}
$('#fYear').addEventListener('change', () => goWeek(Number($('#fYear').value), Number($('#fWeek').value)));
$('#fWeek').addEventListener('change', () => goWeek(Number($('#fYear').value), Number($('#fWeek').value)));
$('#wkPrev').addEventListener('click', () => { let [y, w] = cur; if (--w < 1) { y--; w = weeksIn(y); } goWeek(y, w); });
$('#wkNext').addEventListener('click', () => { const [y, w] = cur; goWeek(y, w + 1); });
$('#weekForm').addEventListener('input', e => {
  if (e.target.id === 'fYear' || e.target.id === 'fWeek') return;
  if (e.target.classList.contains('cnt')) e.target.value = e.target.value.replace(/\D/g, '');
  dirty = true; refreshEntry();
});
$('#grids').addEventListener('keydown', e => {
  const i = e.target; if (!i.classList.contains('cnt')) return;
  const t = i.closest('table'), r = Number(i.dataset.r), c = Number(i.dataset.i);
  const go = (rr, cc) => { const n = t.querySelector('.cnt[data-r="' + rr + '"][data-i="' + cc + '"]'); if (n) { e.preventDefault(); n.focus(); n.select(); } };
  if (e.key === 'ArrowDown' || (e.key === 'Enter' && !e.shiftKey)) go(r + 1, c);
  else if (e.key === 'ArrowUp' || (e.key === 'Enter' && e.shiftKey)) go(r - 1, c);
  else if (e.key === 'ArrowRight' && i.selectionStart === i.value.length) go(r, c + 1);
  else if (e.key === 'ArrowLeft' && i.selectionStart === 0) go(r, c - 1);
});
$('#grids').addEventListener('focusin', e => { if (e.target.classList.contains('cnt')) e.target.select(); });
$('#resetBtn').addEventListener('click', () => { if (!dirty || confirm('Undo the changes to this week?')) loadWeek(...cur); });
window.addEventListener('beforeunload', e => { if (dirty) e.preventDefault(); });

const ALWAYS = ['mpox', 'cholera', 'afp', 'measles', 'matdeath', 'yf', 'shigella', 'ili', 'sari', 'awd_u5', 'awd_o5', 'bu'];
const valueOf = (g, key) => sum(g, key + (BYKEY[key].measures.includes('CS') ? '.CS' : '.D'));
function listed(g) { return ALWAYS.concat(D.map(x => x.key).filter(k => !ALWAYS.includes(k) && (valueOf(g, k) || sum(g, k + '.D')))); }
$('#epiGen').addEventListener('click', () => {
  const g = readGrid();
  $('#fEpi').value = listed(g).map(k => BYKEY[k].name + ' = ' + valueOf(g, k) + (BYKEY[k].measures.includes('CS') && sum(g, k + '.D') ? ' (' + plural(sum(g, k + '.D'), 'death') + ')' : '')).join('; ');
  dirty = true; refreshEntry();
});

$('#weekForm').addEventListener('submit', async e => {
  e.preventDefault();
  const y = Number($('#fYear').value), w = Number($('#fWeek').value);
  const btn = $('#saveBtn'); btn.disabled = true;
  try {
    const r = await postJson('/api/idsr/week', { year: y, week: w, meta: readMeta(), counts: readGrid() });
    setData(r.data); dirty = false; loadWeek(y, w);
    toast('Week ' + pad3(w) + ', ' + y + ' saved');
  } catch (err) { toast(err.message); btn.disabled = false; }
  finally { btn.disabled = false; }
});

// Support: delete a saved week (its details and every row's counts).
$('#delWeekBtn').addEventListener('click', async () => {
  const [y, w] = cur || []; if (!y) return;
  if (!confirm('Delete week ' + pad3(w) + ' of ' + y + ' for ' + regionName() + '?\n\nIts details and all its counts are removed. The previous file is kept as a backup.')) return;
  try { const r = await postJson('/api/idsr/week/delete', { year: y, week: w }); setData(r.data); loadWeek(y, w); toast('Week ' + pad3(w) + ', ' + y + ' deleted'); }
  catch (err) { toast(err.message); }
});
function onRole() { if (cur) $('#delWeekBtn').hidden = !(WEEKS.has(cur[0] + '-' + cur[1]) && ROLE === 'support'); }

/* ---------- Upload ---------- */
let pending = null;
function openUpload() {
  if (!DATA.live) { offline($('#v-upload'), 'Uploading a file'); return; }
  $('#uploadBody').hidden = false;
}
function fillWeekPickers() {
  // Download picker: weeks on file (newest first) plus last week if it is not on file yet.
  const sel = $('#dlWeek'), prev = sel.value; sel.textContent = '';
  const [ly, lw] = defaultWeek(), list = [...DATA.weeks].reverse().map(w => [w.year, w.week]);
  if (!WEEKS.has(ly + '-' + lw)) list.unshift([ly, lw]);
  list.forEach(([y, w]) => { const o = el('option', null, 'Week ' + pad3(w) + ', ' + y + (WEEKS.has(y + '-' + w) ? '' : ' (blank)')); o.value = y + '-' + w; sel.append(o); });
  if ([...sel.options].some(o => o.value === prev)) sel.value = prev;
  dlLinks();
  // Bulletin pickers: years with IDSR weeks or AFP cases, and always the current year.
  const ys = [...new Set([weekOf(today)[0], ...DATA.weeks.map(w => w.year), ...DATA.afp.map(c => afpWeek(c)[0]).filter(Boolean)])].sort((a, b) => b - a);
  const ysel = $('#repYear'), py = ysel.value;
  ysel.textContent = ''; ys.forEach(y => { const o = el('option', null, String(y)); o.value = y; ysel.append(o); });
  if (ys.includes(Number(py))) ysel.value = py;
  else { const latest = DATA.weeks.length ? DATA.weeks[DATA.weeks.length - 1].year : defaultWeek()[0]; if (ys.includes(latest)) ysel.value = latest; }
  fillRepWeeks();
}
function dlLinks() {
  const [y, w] = ($('#dlWeek').value || '').split('-');
  $('#dlForm').href = withRegion('/api/idsr/form.xlsx?year=' + y + '&week=' + w); $('#dlForm').download = 'IDSR weekly form ' + DATA.code + ' wk' + pad3(w) + ' ' + y + '.xlsx';
  $('#dlCsv').href = withRegion('/api/idsr/week.csv?year=' + y + '&week=' + w); $('#dlCsv').download = 'IDSR week ' + pad3(w) + ' ' + y + ' ' + DATA.code + '.csv';
  $('#dlAll').href = withRegion('/api/idsr/store.xlsx'); $('#dlAll').download = DATA.source;
}
$('#dlWeek').addEventListener('change', dlLinks);

async function preview(file, apply) {
  if (file.size > 10 * 1024 * 1024) { toast('That file is over 10 MB.'); return; }
  const btn = $('#planApply'); btn.disabled = true; $('#drop').disabled = true;
  try {
    const r = await api('/api/idsr/import?name=' + encodeURIComponent(file.name) + (apply ? '&apply=1' : ''), { method: 'POST', body: await file.arrayBuffer() });
    if (apply) {
      setData(r.data); $('#plan').hidden = true; pending = null; entryBuilt && cur && !dirty && loadWeek(...cur);
      toast(plural(r.summary.weeks, 'week') + ' updated from ' + file.name); return;
    }
    pending = file; renderPlan(r, file.name, $('#plan'));
  } catch (e) { toast(e.message); }
  finally { btn.disabled = !pending; $('#drop').disabled = false; }
}
// The review of an upload or a DHIMS2 fetch, in its panel (#plan or #dPlan).
function renderPlan(p, title, box) {
  const q = k => box.querySelector('[data-p="' + k + '"]');
  const s = p.summary, any = s.cells + s.meta + p.newDistricts.length > 0;
  box.hidden = false;
  q('label').textContent = 'Review: ' + title;
  q('note').textContent = plural(s.weeks, 'week') + (p.source ? ' from DHIMS2' : ' in the file');
  const tally = q('tally'); tally.textContent = '';
  [['report', s.newWeeks, 'New weeks'], ['soon', s.weeks - s.newWeeks, 'Weeks updated'], ['closed', s.cells, 'Numbers changed'], ['past', p.problems.length, 'Problems']]
    .forEach(([cls, n, label]) => { const d = el('div', 'stat ' + cls); d.append(el('b', null, String(n)), el('span', null, label)); tally.append(d); });
  const body = q('body'); body.textContent = '';
  const group = (title, items) => { const g = el('div', 'plan-group'); g.append(el('p', 'label', title)); items.forEach(i => g.append(i)); body.append(g); };
  const show = v => v == null || v === '' ? 'blank' : String(v);
  p.weeks.forEach(w => {
    const items = [];
    const head = el('div', 'change'); head.append(el('p', 'hl', 'Week ' + pad3(w.week) + ', ' + w.year));
    head.append(el('span', 'epid', w.new ? 'New week · ' + plural(w.districts, 'district') + ' · ' + plural(w.cases, 'suspected case')
      : (w.changeCount ? plural(w.changeCount, 'number') + ' change' : 'No count changes') + (w.meta.length ? ' · ' + plural(w.meta.length, 'detail') + ' change' : '')));
    items.push(head);
    if (!w.new) w.changes.slice(0, 80).forEach(c => {
      const row = el('div', 'cell'); row.append(el('b', null, c.district + ' · ' + c.field), el('span', 'old', show(c.old)), el('span', 'arrow', '→'), el('span', 'new', show(c.new))); items.push(row);
    });
    if (!w.new && w.changeCount > 80) items.push(el('p', 'note', '…and ' + (w.changeCount - 80) + ' more'));
    w.meta.forEach(c => { const row = el('div', 'cell'); row.append(el('b', null, c.field), el('span', 'old', show(c.old).slice(0, 60)), el('span', 'arrow', '→'), el('span', 'new', show(c.new).slice(0, 80))); items.push(row); });
    group(w.new ? 'New week' : 'Update', items);
  });
  if (p.newDistricts.length) group('New districts', p.newDistricts.map(([c, n]) => el('div', 'problem', c + ' · ' + n)));
  if (p.problems.length) group('Problems (these rows are skipped)', p.problems.map(t => el('div', 'problem', t)));
  if (p.notes.length) group('Notes', p.notes.map(t => el('div', 'problem', t)));
  q('warn').textContent = any ? (DATA.saved ? 'Saving keeps the previous version as ' + DATA.source.replace(/[.]xlsx$/, '.bak.xlsx') + '.' : 'Saving creates ' + DATA.source + '.')
    : 'Nothing to change: ' + (p.source ? 'DHIMS2 matches' : 'the file matches') + ' what is on file.';
  q('apply').hidden = !any;
  box.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
$('#drop').addEventListener('click', () => $('#fileInput').click());
$('#fileInput').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; if (f) preview(f, false); });
['dragover', 'dragenter'].forEach(t => $('#drop').addEventListener(t, e => { e.preventDefault(); $('#drop').classList.add('over'); }));
['dragleave', 'drop'].forEach(t => $('#drop').addEventListener(t, () => $('#drop').classList.remove('over')));
$('#drop').addEventListener('drop', e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) preview(f, false); });
$('#planCancel').addEventListener('click', () => { pending = null; $('#plan').hidden = true; });
$('#planApply').addEventListener('click', () => pending && preview(pending, true));

/* ---------- Fetch data from DHIMS2 ---------- */
// The local app talks to DHIMS2: the page sends the token once to connect and never gets it back.
let dCfg = null, dSet = null, dOpened = false, mapDirty = false;
const MEAS_COLS = ['CS', 'D', 'LC', 'Rumour'];
async function openDhims() {
  if (!DATA.live) { offline($('#v-dhims2'), 'Fetching from DHIMS2'); return; }
  $('#dBody').hidden = false;
  if (dOpened) return;
  dOpened = true;
  const [y, w] = defaultWeek(); $('#dYear').value = y; $('#dFrom').value = w; $('#dTo').value = w;
  try {
    showConn(await api('/api/idsr/dhims2'));
    if (dCfg.hasToken) loadSets(await api('/api/idsr/dhims2/datasets'));
  } catch (e) { $('#dWho').textContent = e.message; }
}
function showConn(cfg) {
  dCfg = cfg;
  $('#dUrl').value = cfg.url; $('#dCfgFile').textContent = cfg.configFile; $('#dRemember').checked = cfg.remembered;
  $('#dToken').value = '';
  $('#dToken').placeholder = cfg.hasToken ? 'Token ending …' + cfg.tokenEnd + ' is in use. Paste a new one to replace it.' : 'd2pat_…';
  $('#dForget').hidden = !cfg.hasToken;
  $('#dWho').textContent = cfg.hasToken ? 'Connected' + (cfg.user ? ' as ' + cfg.user : '') + (cfg.remembered ? ' · token remembered on this computer' : ' · token kept until the app is closed') : 'Not connected';
  $('#dSetStep').hidden = $('#dFetchStep').hidden = !cfg.hasToken;
  if (!cfg.hasToken) $('#dPlan').hidden = true;
}
$('#dConnect').addEventListener('click', async () => {
  const btn = $('#dConnect'); btn.disabled = true; btn.textContent = 'Connecting…';
  try {
    const r = await postJson('/api/idsr/dhims2/connect', { url: $('#dUrl').value, token: $('#dToken').value, remember: $('#dRemember').checked });
    showConn(r); loadSets(r); toast('Connected to DHIMS2' + (r.user ? ' as ' + r.user : ''));
  } catch (e) { $('#dWho').textContent = e.message; toast(e.message); }
  finally { btn.disabled = false; btn.textContent = 'Connect'; }
});
$('#dForget').addEventListener('click', async () => {
  try { showConn(await postJson('/api/idsr/dhims2/forget', {})); toast('Token removed from this computer'); } catch (e) { toast(e.message); }
});

function loadSets(r) {
  const sel = $('#dSet'); sel.textContent = '';
  sel.append(new Option('Choose a data set…', ''));
  r.dataSets.forEach(d => sel.append(new Option(d.name + (d.period ? ' · ' + d.period : ''), d.id)));
  $('#dSetHint').textContent = plural(r.dataSets.length, 'data set') + ' your account can read';
  if (dCfg.dataSet && r.dataSets.some(d => d.id === dCfg.dataSet)) { sel.value = dCfg.dataSet; loadElements(); }
}
$('#dSet').addEventListener('change', loadElements);
async function loadElements() {
  const ds = $('#dSet').value;
  dSet = null; $('#dMap').hidden = $('#dSaveMap').hidden = true; $('#dMap').textContent = '';
  if (!ds) { $('#dMapNote').textContent = ''; return; }
  $('#dMapNote').textContent = 'Reading the data set from DHIMS2…';
  try { const r = await api('/api/idsr/dhims2/elements?ds=' + encodeURIComponent(ds)); dCfg.dataSet = ds; dSet = r; buildMap(r); }
  catch (e) { $('#dMapNote').textContent = e.message; }
}
function buildMap(r) {
  // One list of DHIMS2 items, copied into every cell: each element's total, and each category option of it.
  const tpl = el('select', 'in'); tpl.append(new Option('— not fetched —', ''));
  r.elements.forEach(e => {
    if (!e.combos.length) { tpl.append(new Option(e.name, e.id)); return; }
    const g = document.createElement('optgroup'); g.label = e.name;
    g.append(new Option(e.name + ' · total', e.id), ...e.combos.map(c => new Option(e.name + ' · ' + c.name, e.id + '.' + c.id)));
    tpl.append(g);
  });
  const t = el('table', 'dmap'), head = el('tr'), body = el('tbody');
  head.append(el('th', null, 'Disease'), ...MEAS_COLS.map(m => el('th', null, DATA.measures[m])));
  D.forEach(x => {
    const tr = el('tr'), th = el('th', null, x.short); th.title = x.name; tr.append(th);
    MEAS_COLS.forEach(m => {
      if (!x.measures.includes(m)) { tr.append(el('td', 'na', '–')); return; }
      const col = x.key + '.' + m, s = tpl.cloneNode(true), want = r.mapping[col] || '';
      s.dataset.col = col; s.value = want; s.setAttribute('aria-label', x.name + ' · ' + DATA.measures[m]);
      if (s.value !== want) s.value = '';  // matched to an item the data set no longer has
      s.classList.toggle('sugg', r.suggested && !!s.value);
      const td = el('td'); td.append(s); tr.append(td);
    });
    body.append(tr);
  });
  const th = el('thead'); th.append(head); t.append(th, body);
  $('#dMap').replaceChildren(t); $('#dMap').hidden = $('#dSaveMap').hidden = false;
  mapDirty = false; mapNote();
}
function readMapping() { return Object.fromEntries([...$('#dMap').querySelectorAll('select')].filter(s => s.value).map(s => [s.dataset.col, s.value])); }
function mapNote() {
  const all = $('#dMap').querySelectorAll('select'), n = [...all].filter(s => s.value).length;
  $('#dMapNote').textContent = n + ' of ' + all.length + ' IDSR columns matched'
    + (dSet && dSet.suggested ? ' · suggested from the names (green): check them, then save' : '') + (mapDirty ? ' · not saved yet' : '');
}
$('#dMap').addEventListener('change', e => { if (e.target.matches('select')) { e.target.classList.remove('sugg'); mapDirty = true; mapNote(); } });
function mapSaved() { mapDirty = false; if (dSet) dSet.suggested = false; $('#dMap').querySelectorAll('.sugg').forEach(s => s.classList.remove('sugg')); mapNote(); }
$('#dSaveMap').addEventListener('click', async () => {
  try { await postJson('/api/idsr/dhims2/mapping', { ds: $('#dSet').value, mapping: readMapping() }); mapSaved(); toast('Column matches saved'); }
  catch (e) { toast(e.message); }
});

document.querySelectorAll('#dFetchStep [data-span]').forEach(b => b.addEventListener('click', () => {
  const [y, w] = defaultWeek(), k = b.dataset.span;
  $('#dYear').value = y; $('#dTo').value = w; $('#dFrom').value = k === 'ytd' ? 1 : Math.max(1, w - Number(k) + 1);
}));
async function dFetch(apply) {
  if (!dSet) { toast('Choose the DHIMS2 data set first.'); return; }
  const btn = apply ? $('#dApply') : $('#dFetch'), label = btn.textContent;
  btn.disabled = true; btn.textContent = apply ? 'Saving…' : 'Fetching from DHIMS2…'; $('#dErr').textContent = '';
  try {
    const r = await postJson('/api/idsr/dhims2/fetch', { ds: $('#dSet').value, mapping: readMapping(), year: $('#dYear').value, from: $('#dFrom').value, to: $('#dTo').value, apply });
    mapSaved();  // the server keeps the matches used for a fetch
    if (apply) {
      setData(r.data); $('#dPlan').hidden = true; entryBuilt && cur && !dirty && loadWeek(...cur);
      toast(plural(r.summary.weeks, 'week') + ' saved from DHIMS2'); return;
    }
    const [a, b] = r.source.weeks;
    renderPlan(r, 'DHIMS2 · ' + (a === b ? 'week ' + pad3(a) : 'weeks ' + pad3(a) + '–' + pad3(b)) + ', ' + r.source.year, $('#dPlan'));
  } catch (e) { $('#dErr').textContent = e.message; toast(e.message); }
  finally { btn.disabled = false; btn.textContent = label; }
}
$('#dFetch').addEventListener('click', () => dFetch(false));
$('#dApply').addEventListener('click', () => dFetch(true));
$('#dCancel').addEventListener('click', () => { $('#dPlan').hidden = true; });


/* ---------- Bulletin ---------- */
const T1 = [['AFP', 'afp.CS'], ['Measles', 'measles.CS'], ['YF', 'yf.CS'], ['CSM', 'mening.CS'], ['Cholera', 'cholera.CS'], ['Mpox', 'mpox.CS'], ["Mat'l Deaths", 'matdeath.D']];
const T2 = [['AFP', 'afp'], ['Cholera', 'cholera'], ['ILI', 'ili'], ['SARI', 'sari'], ['Dengue fever', 'dengue'], ['Measles', 'measles'], ['YF', 'yf'], ['CSM', 'mening'], ['Mpox', 'mpox'], ['COVID-19', 'covid'], ['Maternal mortality', 'matdeath'], ['BU', 'bu']];
const PHRASE = {
  mpox: ['suspected Mpox case'], cholera: ['suspected cholera case'], afp: ['suspected polio (AFP) case'], measles: ['suspected measles case'],
  matdeath: ['maternal death'], yf: ['suspected yellow fever case'], shigella: ['case of diarrhoea with blood', 'cases of diarrhoea with blood'],
  ili: ['suspected ILI case'], sari: ['suspected SARI case'], awd_u5: ['reported case of acute watery diarrhoea < 5 years', 'reported cases of acute watery diarrhoea < 5 years'],
  awd_o5: ['reported case of acute watery diarrhoea > 5 years', 'reported cases of acute watery diarrhoea > 5 years'], bu: ['suspected Buruli ulcer case'],
  ahf: ['suspected acute haemorrhagic fever case'], aefi: ['AEFI case'], anthrax: ['suspected anthrax case'], dengue: ['suspected dengue fever case'],
  guinea: ['guinea worm case'], mening: ['suspected meningitis (CSM) case'], nnt: ['suspected neonatal tetanus case'], plague: ['suspected plague case'],
  rabies: ['dog bite case'], covid: ['suspected COVID-19 case'], zika: ['suspected Zika virus disease case'], pheic: ['public health event of concern', 'public health events of concern'],
};
const phrase = (k, n) => n + ' ' + (n === 1 ? PHRASE[k][0] : PHRASE[k][1] || PHRASE[k][0] + 's');

// Every epi week of the year up to the current one; a week with no IDSR report still gives a bulletin
// (AFP from the AFP register, other diseases 0), and says so.
function fillRepWeeks() {
  const y = Number($('#repYear').value), sel = $('#repWeek'), prev = sel.value; sel.textContent = '';
  if (!y) return;
  const [cy, cw] = weekOf(today), last = y === cy ? cw : y > cy ? 0 : weeksIn(y);
  for (let w = last; w >= 1; w--) {
    const { start, end } = weekDates(y, w);
    const o = el('option', null, 'Week ' + pad3(w) + ' · ' + span(start, end) + (WEEKS.has(y + '-' + w) ? '' : ' · no IDSR report')); o.value = w; sel.append(o);
  }
  const onFile = DATA.weeks.filter(w => w.year === y), [dy, dw] = defaultWeek();
  const pick = [prev, onFile.length && onFile[onFile.length - 1].week, dy === y && dw].map(String).find(v => [...sel.options].some(o => o.value === v));
  if (pick) sel.value = pick;
}
$('#repYear').addEventListener('change', () => { fillRepWeeks(); renderBulletin(); });
$('#repWeek').addEventListener('change', renderBulletin);
$('#repAfp').addEventListener('change', renderBulletin);
// Publication dates picked on the report page, by year-week; a week with none uses the Thursday after it.
const pubPick = new Map();
$('#repPub').addEventListener('change', e => {
  const key = $('#repYear').value + '-' + $('#repWeek').value;
  if (asDate(e.target.value)) pubPick.set(key, e.target.value); else pubPick.delete(key);
  renderBulletin();
});
// Set on each page (not a parent) so the page copies drawn for the PNG keep the colour.
paperPicker($('#repPaper'), 'idsr.bulletinPaper', '#92d050', hex => document.querySelectorAll('.bpage').forEach(p => p.style.setProperty('--paper', hex)));

function tableRows(tab, head, rows, cls) {
  tab.textContent = '';
  const th = el('thead'), hr = el('tr'); head.forEach(h => hr.append(el('th', null, h))); th.append(hr);
  const tb = el('tbody');
  rows.forEach(r => {
    const tr = el('tr', r.cls || '');
    r.cells.forEach((c, i) => { const td = el('td', (i === 0 && cls !== false ? 'k ' : '') + (c && c.cls || '')); if (c && c.nodes) td.append(...c.nodes); else td.textContent = c && typeof c === 'object' ? c.text : c; tr.append(td); });
    tb.append(tr);
  });
  tab.append(th, tb);
}
// Epi year and week of an AFP case: the register's Epid. week, in the year of onset (or of the EPID number).
function afpWeek(c) {
  const o = asDate(c.onset), [oy, ow] = o ? weekOf(o) : [afpYear(c), null], wk = Number(c.week);
  return [oy, wk >= 1 && wk <= 53 ? wk : ow];
}
function afpCounts(y, w) {
  const out = {};
  DATA.afp.forEach(c => { const [cy, cw] = afpWeek(c); if (cy === y && cw === w && c.dcode) out[c.dcode] = (out[c.dcode] || 0) + 1; });
  return out;
}
// The bulletin's counts for a week: the weekly IDSR report, with AFP never below the cases notified on the
// AFP register for that district and week (the register lists each case, so the count is at least that).
function bulletinGrid(y, w) {
  const g = {}, idsr = grid(y, w), afp = afpCounts(y, w);
  for (const code in idsr) g[code] = { ...idsr[code] };
  let filled = 0;
  for (const code in afp) {
    const had = (g[code] || {})['afp.CS'] || 0;
    if (afp[code] > had) { (g[code] ||= {})['afp.CS'] = afp[code]; filled += afp[code] - had; }
  }
  return { g, filled };
}
function cumulative(y, w) {
  const out = {}; let n = 0, filled = 0;
  for (let k = 1; k <= w; k++) {
    if (WEEKS.has(y + '-' + k)) n++;
    const b = bulletinGrid(y, k); filled += b.filled;
    for (const code in b.g) { const t = out[code] ||= {}; for (const c in b.g[code]) t[c] = (t[c] || 0) + b.g[code][c]; }
  }
  return { g: out, n, filled };
}
function cumCell(row, key) {
  if (key === 'matdeath') return String(row['matdeath.D'] || 0);
  const cs = row[key + '.CS'] || 0, lc = row[key + '.LC'] || 0, d = row[key + '.D'] || 0;
  if (!lc && !d) return String(cs);
  const extra = [lc ? lc + '+' : '', d ? plural(d, 'death') : ''].filter(Boolean).join(', ');
  return { nodes: [String(cs) + ' ', el('span', 'red', '(' + extra + ')')] };
}
function afpYear(c) { const m = /-(\d{2})-\d+$/.exec(c.epid || ''); if (m) return 2000 + Number(m[1]); const o = asDate(c.onset); return o ? o.getFullYear() : null; }
function trackerRows(y, asOf) {
  // Only cases still needing action are listed: done but no report yet, overdue, or due. Cases with the report in,
  // other recorded outcomes (e.g. lost to follow-up) and cases without an onset date are left off.
  return DATA.afp.filter(c => afpYear(c) === y).map(c => ({ c, onset: asDate(c.onset) })).sort((a, b) => (a.onset || 0) - (b.onset || 0)).map(({ c, onset }) => {
    const fup = onset && new Date(onset.getTime() + 60 * DAY), o = norm(c.outcome), rep = norm(c.report) === 'yes';
    const [text, cls] = o === 'fup done' ? (rep ? [] : ['Done, report not yet received', 'pend'])
      : o && o !== 'fup pending' ? [] : !onset ? []
      : asOf > fup ? ['Follow-up overdue (due ' + dmy(fup) + ')', 'late'] : ['Follow-up due ' + dmy(fup), 'pend'];
    return text && { c, onset, fup, text, cls };
  }).filter(Boolean).map(({ c, onset, fup, text, cls }, i) =>
    ({ cells: [String(i + 1), String((DATA.national ? c.dcode : c.code) || c.district || '').toUpperCase(), dmy(onset), dmy(fup), { text, cls: 'rem ' + cls }] }));
}

function renderBulletin() {
  const y = Number($('#repYear').value), w = Number($('#repWeek').value);
  const empty = !y || !w;
  $('#bulletin').hidden = empty; $('#expPng').disabled = $('#expPdf').disabled = empty;
  renderSettings();
  if (empty) { $('#repNote').textContent = 'Choose a year and epi week.'; return; }
  const onFile = WEEKS.has(y + '-' + w), meta = WEEKS.get(y + '-' + w) || {}, { g, filled } = bulletinGrid(y, w), region = regionName();
  const { start, end, pub } = weekDates(y, w);  // header dates follow the chosen week, never typed
  const fromAfp = filled ? ' · ' + plural(filled, 'AFP case') + ' added from the AFP register' : '';
  $('#repNote').textContent = 'Week ' + pad3(w) + ' · ' + (onFile ? plural(Object.keys(grid(y, w)).length, UNIT) + ' reported' : 'no weekly IDSR report entered') + fromAfp;
  $('#bSub').textContent = 'Ghana Health Service – ' + region + ' • Week No: ' + pad3(w) + ', ' + y;
  $('#bRhd').style.visibility = /upper\s*east/i.test(DATA.region) ? 'visible' : 'hidden';
  $('#bNo').textContent = 'Weekly Epidemiological Bulletin No: ' + pad3(w);
  const pubDate = asDate(pubPick.get(y + '-' + w)) || pub;
  $('#repPub').value = isoOf(pubDate);
  $('#bPub').textContent = 'Publication date: ' + dmy(pubDate);
  $('#bWeeks').replaceChildren(el('span', null, 'Week-Starting: ' + dmy(start)), el('span', null, 'Ending: ' + dmy(end)));

  // Highlights
  const hl = $('#bHigh'); hl.textContent = '';
  if (!onFile) hl.append(el('li', null, 'No weekly IDSR report has been entered for Week ' + pad3(w) + ' yet; ' + (filled ? 'AFP cases are taken from the AFP notification register and ' : '') + 'other diseases show 0.'));
  if (meta.expected) {
    const c = meta.received != null ? Math.round(meta.received / meta.expected * 100) : null, t = meta.ontime != null ? Math.round(meta.ontime / meta.expected * 100) : null;
    const asof = ' as of ' + ordinal(pub.getDate()) + ' ' + MONTHS[pub.getMonth()] + ' ' + pub.getFullYear();
    if (c != null) hl.append(el('li', null, (DATA.national ? 'The country' : 'The region') + ' achieved DHIMS-2 IDSR ' + (t == null ? 'completeness of ' + c + '%' : c === t ? 'completeness and timeliness rates of ' + c + '%' : 'completeness of ' + c + '% and timeliness of ' + t + '%') + ' for Week ' + pad3(w) + asof + '.'));
  }
  listed(g).forEach(k => {
    const x = BYKEY[k], n = valueOf(g, k), d = x.measures.includes('CS') ? sum(g, k + '.D') : 0, lc = sum(g, k + '.LC');
    hl.append(el('li', null, phrase(k, n) + (d || lc ? ' (' + [lc ? lc + ' lab-confirmed' : '', d ? plural(d, 'death') : ''].filter(Boolean).join(', ') + ')' : '')));
  });
  String(meta.highlights || '').split('\n').map(s => s.trim()).filter(Boolean).forEach(s => hl.append(el('li', null, s)));

  // Table 1: this week
  $('#bCap1').textContent = 'Table 1. Surveillance feedback on cases of priority diseases (WK ' + pad3(w) + ' suspected cases)';
  const r1 = DATA.districts.map(([code]) => ({ cells: [code, ...T1.map(([, c]) => String((g[code] || {})[c] || 0))] }));
  r1.push({ cls: 'total', cells: ['TOTAL', ...T1.map(([, c]) => String(sum(g, c)))] });
  tableRows($('#bTab1'), [DATA.national ? 'Reg.' : 'M/D', ...T1.map(t => t[0])], r1);

  // Table 2: year to date
  const cum = cumulative(y, w), tot = {};
  for (const code in cum.g) for (const c in cum.g[code]) tot[c] = (tot[c] || 0) + cum.g[code][c];
  $('#bBar2').textContent = 'Table 2: Cumulative cases of priority diseases by ' + (DATA.national ? 'region' : 'M/District') + ' – ' + y;
  const r2 = DATA.districts.map(([code]) => ({ cells: [code, ...T2.map(([, k]) => cumCell(cum.g[code] || {}, k))] }));
  r2.push({ cls: 'total', cells: [DATA.code || 'TOTAL', ...T2.map(([, k]) => cumCell(tot, k))] });
  tableRows($('#bTab2'), [DATA.national ? 'Reg.' : 'M/Dist.', ...T2.map(t => t[0].toUpperCase())], r2);
  $('#bNote2').textContent = (DATA.national ? 'Regions by code; each region is the sum of its districts • ' + DATA.code + ' = Ghana (national total) • '
    : 'M/D = Municipality / District • ' + (DATA.code ? DATA.code + ' = ' + region + ' (regional total) • ' : '')) + 'Figures in brackets: + lab-confirmed, deaths. • '
    + 'Cumulative from ' + plural(cum.n, 'weekly report') + ' on file for weeks 1–' + w + (cum.n < w ? ' (' + (w - cum.n) + ' not entered)' : '') + '.'
    + (cum.filled ? ' AFP includes ' + plural(cum.filled, 'case') + ' from the AFP notification register not counted in the weekly IDSR reports.' : '');

  // AFP tracker
  const showAfp = $('#repAfp').checked; $('#bAfp').hidden = !showAfp;
  if (showAfp) {
    $('#bBarAfp').textContent = 'Polio – AFP 60-day follow-up tracker (as of ' + dmy(pubDate) + ')';
    const rows = trackerRows(y, pubDate);
    if (rows.length) tableRows($('#bTabAfp'), ['S/N', DATA.national ? 'Region' : 'District', 'Date of onset', 'Date of follow-up', 'Remarks'], rows, false);
    else { const t = $('#bTabAfp'); t.textContent = ''; const tr = el('tr'), td = el('td', 'bempty', 'No AFP cases awaiting follow-up or a follow-up report for ' + y + '.'); td.colSpan = 5; tr.append(td); t.append(tr); }
  }

  // The tracker sits on page 1 like the regional PDF, and moves to the top of page 2 when page 1 would run past A4.
  const p1 = $('#bp1'), p2 = $('#bp2'), afp = $('#bAfp');
  p1.insertBefore(afp, p1.querySelector('.bfoot'));
  if (showAfp && p1.offsetHeight > 1123) p2.insertBefore(afp, p2.firstElementChild);

  // Page 2
  const acts = $('#bActions'); acts.textContent = '';
  const own = [meta.decisions, meta.recommendations].join('\n').split('\n').map(s => s.trim().replace(/^[-*•\d.)\s]+/, '')).filter(Boolean);
  (own.length ? own : DATA.actions).forEach(a => acts.append(el('li', null, a)));
  [['map', '#bMap'], ['sormas', '#bSormas']].forEach(([slot, sel]) => { const f = $(sel), src = DATA.images[slot]; f.hidden = !src; f.querySelector('img').src = src || ''; });
  $('#bMapCap').textContent = DATA.national ? 'Ghana – Regions' : region + ' – Municipalities & Districts';
  $('#bMapSrc').textContent = DATA.national ? 'Source: Ghana Health Service' : 'Source: GHS ' + region + 'al Directorate';
  const b = $('#bBoard'); b.textContent = '';
  const people = DATA.board.map(([n, r]) => [{ text: n }, { text: r ? '– ' + r : '', cls: 'role' }]);
  people.push([{ text: (DATA.national ? 'Compiled from the regional weekly IDSR reports, GHS – Ghana' : 'Compiled by the Regional Surveillance Unit, GHS – ' + (DATA.region || region)), cls: 'comp' }]);
  for (let i = 0; i < people.length; i += 2) {
    const tr = el('tr');
    [people[i], people[i + 1]].forEach(p => {
      if (!p) return;
      p.forEach((c, k) => { const td = el('td', c.cls || '', c.text); if (p.length === 1) td.colSpan = 2; tr.append(td); });
    });
    b.append(tr);
  }
  document.querySelectorAll('.bfoot').forEach(f => {
    f.textContent = '';
    f.append('Ghana Health Service – ' + region + '  |  Weekly Epidemiological Bulletin No. ' + pad3(w) + '  |  Week ' + pad3(w) + ': ' + span(start, end) + '  |  Page ',
      el('b', null, f.dataset.page), ' of 2', el('br'), '© ' + y + ' Ghana Health Service – ' + region + '. All rights reserved.');
  });
}

/* Exports: the page as an image (each A4 page drawn through an SVG foreignObject), or the browser's Save as PDF. */
const fileName = () => 'Weekly Epidemiological Bulletin wk' + pad3($('#repWeek').value) + ' ' + $('#repYear').value;
async function pageImage(page) {
  const w = page.offsetWidth, h = page.offsetHeight;
  const css = $('#bulletinCss').textContent.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const clone = page.cloneNode(true); clone.style.boxShadow = 'none'; clone.style.margin = '0';
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h + '"><foreignObject x="0" y="0" width="100%" height="100%">'
    + '<div xmlns="http://www.w3.org/1999/xhtml"><style>' + css + '</style>' + new XMLSerializer().serializeToString(clone) + '</div></foreignObject></svg>';
  const img = new Image(); img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  await img.decode();
  return { img, w, h };
}
async function bulletinCanvas() {
  const shots = [];
  for (const p of document.querySelectorAll('.bpage')) shots.push(await pageImage(p));
  const S = 2, W = Math.max(...shots.map(s => s.w)), H = shots.reduce((a, s) => a + s.h, 0);
  const cv = document.createElement('canvas'); cv.width = W * S; cv.height = H * S;
  const ctx = cv.getContext('2d'); ctx.scale(S, S); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, W, H);
  let y = 0; for (const s of shots) { ctx.drawImage(s.img, 0, y, s.w, s.h); y += s.h; }
  return cv;
}
function download(blob, name) {
  const a = el('a'); a.href = URL.createObjectURL(blob); a.download = name;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
$('#expPng').addEventListener('click', async () => {
  const btn = $('#expPng'); btn.disabled = true;
  try {
    renderBulletin();
    const cv = await bulletinCanvas();
    await new Promise((ok, fail) => cv.toBlob(b => b ? (download(b, fileName() + '.png'), ok()) : fail(new Error('empty')), 'image/png'));
    toast('Image saved');
  } catch (e) { toast('This browser could not draw the image. Use PDF instead.'); }
  finally { btn.disabled = false; }
});
$('#expPdf').addEventListener('click', () => {
  renderBulletin();
  const title = document.title; document.title = fileName(); document.body.classList.add('print-bulletin');
  const done = () => { document.body.classList.remove('print-bulletin'); document.title = title; window.removeEventListener('afterprint', done); };
  window.addEventListener('afterprint', done);
  toast('Choose “Save as PDF” as the printer');
  setTimeout(() => window.print(), 50);
});

/* Bulletin details (live app only) */
let settingsShown = false;
function renderSettings() {
  $('#setPanel').hidden = !DATA.live;
  if (!DATA.live) return;
  document.querySelectorAll('.pic').forEach(p => { const src = DATA.images[p.dataset.slot], img = p.querySelector('img'); img.hidden = !src; img.src = src || ''; p.querySelector('[data-act="remove"]').disabled = !src; });
  if (settingsShown) return;
  settingsShown = true;
  $('#sRegion').value = regionName();
  $('#sCode').value = DATA.code;
  $('#sDistricts').value = DATA.districts.map(([c, n]) => c + '  ' + n).join('\n');
  distHint();
  $('#sBoard').value = DATA.board.map(([n, r]) => r ? n + ' – ' + r : n).join('\n');
  $('#sActions').value = DATA.actions.join('\n');
}
const lines = id => $(id).value.split('\n').map(s => s.trim()).filter(Boolean);
function distHint() { $('#sDistHint').textContent = plural(lines('#sDistricts').length, 'district'); }
$('#sReset').addEventListener('click', () => {
  const u = orgUnit(); if (!u) return;
  $('#sCode').value = u.code;
  $('#sDistricts').value = u.districts.map(([c, n]) => c + '  ' + n).join('\n');
  distHint(); toast(plural(u.districts.length, 'district') + ' from the org unit list · press Save details to keep them');
});
$('#sDistricts').addEventListener('input', distHint);
$('#setSave').addEventListener('click', async () => {
  const districts = lines('#sDistricts').map(l => { const m = /^(\S+)\s+[-–—:]?\s*(.+)$/.exec(l); return m ? [m[1], m[2]] : [l, '']; });
  const board = lines('#sBoard').map(l => { const m = /^(.*\S)\s+[-–—]\s+(.+)$/.exec(l); return m ? [m[1], m[2]] : [l, '']; });
  const btn = $('#setSave'); btn.disabled = true;
  try {
    const r = await postJson('/api/idsr/settings', { region: DATA.region, code: $('#sCode').value, districts, board, actions: lines('#sActions') });
    settingsShown = false; entryBuilt = false; setData(r.data); toast('Bulletin details saved');
  } catch (e) { toast(e.message); } finally { btn.disabled = false; }
});
let picSlot = null;
document.querySelector('.pics').addEventListener('click', async e => {
  const b = e.target.closest('button'); if (!b) return;
  picSlot = b.closest('.pic').dataset.slot;
  if (b.dataset.act === 'pick') { $('#picInput').click(); return; }
  try { const r = await api('/api/idsr/image?slot=' + picSlot, { method: 'POST', body: new Uint8Array(0) }); setData(r.data); toast('Picture removed'); } catch (err) { toast(err.message); }
});
$('#picInput').addEventListener('change', async e => {
  const f = e.target.files[0]; e.target.value = ''; if (!f) return;
  if (f.size > 10 * 1024 * 1024) { toast('That picture is over 10 MB.'); return; }
  try { const r = await api('/api/idsr/image?slot=' + picSlot, { method: 'POST', body: await f.arrayBuffer() }); setData(r.data); toast('Picture saved'); } catch (err) { toast(err.message); }
});

/* Org unit: the region picks the districts for entry, upload and the bulletin */
const orgUnit = (name = DATA.region) => DATA.national && name === DATA.region
  ? { name: DATA.region, districts: (DATA.orgUnits || []).map(u => [u.code, u.name]) }  // Ghana: its rows are the regions
  : (DATA.orgUnits || []).find(u => norm(u.name) === norm(name).replace(/\s*region$/, ''));
function renderOrgUnit() {
  $('#orgRegion').textContent = regionName();
  const nav = $('#navRegion'); if (nav) nav.textContent = regionName().toUpperCase();  // removed in the read-only copy
  $('#orgChange').hidden = !DATA.live;
  $('#orgDistLabel').textContent = plural(DATA.districts.length, UNIT) + (DATA.code ? ' · ' + DATA.code : '');
  $('#orgDists').replaceChildren(...DATA.districts.map(([c, n]) => { const s = el('span'); s.append(el('b', null, c), n); return s; }));
  const note = $('#orgNote');
  note.hidden = DATA.live && DATA.saved;
  note.textContent = DATA.national && DATA.live ? 'No weeks saved for Ghana yet. Its rows are the 16 regions: enter each region’s figures here, upload them or fetch them from DHIMS2. Its file (' + DATA.source + ') is created when you save the first week, separate from the regions’ files.'
    : !DATA.live ? 'This copy shows ' + regionName() + '. Open the local app to switch regions.'
    : 'No weeks saved for ' + regionName() + ' yet. Its districts come from the org unit list, and its file (' + DATA.source + ') is created when you save the first week.';
}

// The region is picked on the start page; in the app, the region link goes back there to change it.
document.querySelectorAll('.modules a').forEach(a => { if (DATA.live) a.href = { afp: '/', idsr: withRegion('/idsr'), men: '/meningitis', start: '/start', admin: '/admin', profile: '/profile?next=' + encodeURIComponent('/idsr'), logout: '/logout' }[a.dataset.m]; else if (['start', 'admin', 'profile', 'logout', 'men'].includes(a.dataset.m)) a.remove(); });
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
// The AFP register belongs to one region: show its tracker by default only on that region's bulletin.
// The tracker lists the AFP register's cases from this region's districts.
$('#repAfp').checked = DATA.afp.length > 0;
$('#repAfp').nextElementSibling.textContent = 'AFP 60-day tracker (' + plural(DATA.afp.length, 'case') + ' from ' + regionName() + ')';
setData(DATA);
showView(location.hash.slice(1));
