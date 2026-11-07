/* Meningitis line list: dashboard, line list, case form, upload, reports, sub-districts and thresholds.
   Every figure comes from the server (/api/men/...); this page only lays it out. */
let DATA = JSON.parse(document.getElementById('page-data').textContent);
const VIEWS = { dashboard: 'Dashboard', list: 'Line list', case: 'New case', upload: 'Upload', reports: 'Reports', setup: 'Sub-districts and thresholds' };
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const num = n => n == null || n === '' ? '' : Number(n).toLocaleString('en-GB');
const pc = v => v == null ? '—' : v.toFixed(1);
const plural = (n, w, p) => num(n) + ' ' + (n === 1 ? w : (p || w + 's'));
const dmy = s => s ? s.slice(8, 10) + '/' + s.slice(5, 7) + '/' + s.slice(0, 4) : '';
const pad = n => String(n).padStart(2, '0');
const todayIso = (() => { const d = new Date(); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); })();
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 4200); }
const AREA = DATA.national ? 'Region' : 'District';
const CLS = { '1': ['Confirmed', '#8b1a1a'], '2': ['Probable', '#e07b00'], '3': ['Suspect', '#8c8c8c'], '': ['Not classified', '#c9c9c9'] };
const LISTS = DATA.schema.lists;
const FIELDS = DATA.schema.fields;
const BYF = Object.fromEntries(FIELDS.map(f => [f.name, f]));

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { 'X-CSRFToken': csrfToken(), ...(opts.headers || {}) } });
  let body = null; try { body = await r.json(); } catch (_) {}
  if (!r.ok) throw Object.assign(new Error((body && body.error) || 'Something went wrong (' + r.status + ').'), { status: r.status, body });
  return body;
}
const postJson = (path, obj) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(obj) });
const query = obj => Object.entries(obj).filter(([, v]) => v !== '' && v != null).map(([k, v]) => k + '=' + encodeURIComponent(v)).join('&');
function options(sel, list, blank) {
  sel.replaceChildren(...(blank != null ? [Object.assign(el('option', null, blank), { value: '' })] : []),
    ...list.map(([v, t]) => Object.assign(el('option', null, t), { value: v })));
}

/* ---------- header ---------- */
function renderStatus() {
  $('#regionSlug').textContent = DATA.regionLabel.toUpperCase();
  $('#navRegion').textContent = DATA.regionLabel.toUpperCase();
  $('#statusText').textContent = plural(DATA.count, 'case') + ' in the line list';
}
renderStatus();
$('#readOnly').hidden = DATA.canWrite;
document.querySelectorAll('.adminlink').forEach(a => a.hidden = !DATA.support);
document.querySelectorAll('.year').forEach(e => e.textContent = new Date().getFullYear());
if (!DATA.canWrite) document.querySelectorAll('[data-v="case"], [data-v="upload"], #lNew').forEach(b => b.hidden = true);

/* ---------- sections ---------- */
let current = null;
function showView(v) {
  if (!VIEWS[v] || (!DATA.canWrite && (v === 'case' || v === 'upload'))) v = 'dashboard';
  current = v;
  document.querySelectorAll('.view-tab').forEach(b => b.setAttribute('aria-selected', b.dataset.v === v));
  for (const k in VIEWS) $('#v-' + k).hidden = k !== v;
  $('#filters').hidden = !(v === 'dashboard' || v === 'reports');
  $('#title').textContent = v === 'case' && caseId ? 'Edit case' : VIEWS[v];
  if (location.hash.slice(1) !== v) history.replaceState(null, '', '#' + v);
  ({ dashboard: loadDashboard, list: loadList, case: openCase, upload: () => {}, reports: loadReport, setup: renderSetup })[v]();
}
document.querySelector('.views').addEventListener('click', e => { const b = e.target.closest('.view-tab'); if (b) showView(b.dataset.v); });
window.addEventListener('hashchange', () => { if (location.hash.slice(1) !== current) showView(location.hash.slice(1)); });

/* ---------- period and place filters ---------- */
const F = { year: String(DATA.today.year), season: '1', from: '', to: '', district: '' };
function fillFilters() {
  options($('#fYear'), DATA.years.slice().reverse().map(y => [String(y), String(y)]));
  $('#fYear').value = F.year;
  $('#fSeason').options[0].textContent = 'Season (from week ' + DATA.cfg.seasonStart + ' of the year before)';
  $('#fDistLabel').textContent = AREA;
  options($('#fDistrict'), DATA.districts.map(([, n]) => [n, n]), DATA.national ? 'All regions' : 'All districts');
}
fillFilters();
['fYear', 'fSeason', 'fFrom', 'fTo', 'fDistrict'].forEach(id => $('#' + id).addEventListener('change', () => {
  Object.assign(F, { year: $('#fYear').value, season: $('#fSeason').value, from: $('#fFrom').value, to: $('#fTo').value, district: $('#fDistrict').value });
  if (current === 'dashboard') loadDashboard(); else if (current === 'reports') loadReport();
}));
const periodQuery = extra => query({ ...F, ...extra });

/* ---------- charts (inline SVG, so they print and export as drawn) ---------- */
function niceMax(v) { if (v <= 5) return 5; const p = 10 ** Math.floor(Math.log10(v)), m = v / p; return (m <= 2 ? 2 : m <= 5 ? 5 : 10) * p; }
function axes(W, H, L, T, R, B, max, weeks, every) {
  let s = '';
  for (let k = 0; k <= 5; k++) {
    const v = max * k / 5, y = H - B - (H - B - T) * k / 5;
    s += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="currentColor" stroke-opacity="${k ? .12 : .5}"/>`;
    s += `<text x="${L - 6}" y="${y + 4}" text-anchor="end">${num(Math.round(v * 10) / 10)}</text>`;
  }
  const step = (W - L - R) / weeks.length;
  weeks.forEach((w, i) => { if (i % every === 0) s += `<text x="${L + step * (i + .5)}" y="${H - B + 14}" text-anchor="middle">${w.w}</text>`; });
  const firsts = weeks.map((w, i) => [w, i]).filter(([w, i]) => i === 0 || weeks[i - 1].y !== w.y);
  firsts.forEach(([w, i]) => { s += `<text x="${L + step * i}" y="${H - B + 28}" font-weight="700">${w.y}</text>`; if (i) s += `<line x1="${L + step * i}" x2="${L + step * i}" y1="${T}" y2="${H - B + 18}" stroke="currentColor" stroke-opacity=".35" stroke-dasharray="3 3"/>`; });
  return s;
}
function epiCurve(box, weeks, series) {
  const W = Math.max(640, weeks.length * 13 + 70), H = 260, L = 40, T = 12, R = 10, B = 40;
  const tot = weeks.map((_, i) => series.reduce((a, s) => a + s.values[i], 0));
  const max = niceMax(Math.max(1, ...tot)), step = (W - L - R) / weeks.length, sy = (H - B - T) / max;
  let s = axes(W, H, L, T, R, B, max, weeks, weeks.length > 40 ? 4 : weeks.length > 20 ? 2 : 1);
  weeks.forEach((w, i) => {
    let y = H - B;
    series.forEach(se => { const v = se.values[i]; if (!v) return; const h = v * sy; y -= h;
      s += `<rect x="${L + step * i + 1}" y="${y}" width="${Math.max(1, step - 2)}" height="${h}" fill="${CLS[se.code][1]}"><title>Week ${w.w} of ${w.y}: ${v} ${esc(se.label.toLowerCase())}</title></rect>`; });
  });
  s += `<text x="${L - 30}" y="${T + (H - B) / 2}" transform="rotate(-90 ${L - 30} ${T + (H - B) / 2})" text-anchor="middle">Cases</text>`;
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cases by epi week">${s}</svg>`;
  const lg = el('div', 'legend-row');
  series.forEach(se => { const sp = el('span'); const i = el('i'); i.style.background = CLS[se.code][1]; sp.append(i, se.label + ' (' + num(se.total) + ')'); lg.append(sp); });
  box.append(lg);
}
function thresholdChart(box, weeks, c) {
  const W = 380, H = 190, L = 30, T = 8, R = 8, B = 34;
  const max = niceMax(Math.max(1, c.epidemic || 0, ...c.c)), step = (W - L - R) / weeks.length, sy = (H - B - T) / max;
  const x = i => L + step * (i + .5), y = v => H - B - v * sy;
  let s = axes(W, H, L, T, R, B, max, weeks, weeks.length > 30 ? 6 : 3);
  const line = (vals, color, extra = '') => `<polyline fill="none" stroke="${color}" stroke-width="1.6" ${extra} points="${vals.map((v, i) => x(i) + ',' + y(v)).join(' ')}"/>`;
  s += `<line x1="${L}" x2="${W - R}" y1="${y(c.alert)}" y2="${y(c.alert)}" stroke="#e0a000" stroke-width="1.6" stroke-dasharray="5 3"/>`;
  s += `<line x1="${L}" x2="${W - R}" y1="${y(c.epidemic)}" y2="${y(c.epidemic)}" stroke="#e00000" stroke-width="1.6" stroke-dasharray="5 3"/>`;
  s += line(c.d, '#c00000') + line(c.c, '#1f3864');
  c.c.forEach((v, i) => { if (v) s += `<circle cx="${x(i)}" cy="${y(v)}" r="2.6" fill="${c.status[i] === 'epidemic' ? '#e00000' : c.status[i] === 'alert' ? '#e0a000' : '#1f3864'}"><title>Week ${weeks[i].w}: ${v} cases, ${c.d[i]} deaths</title></circle>`; });
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Weekly cases and deaths against the thresholds">${s}</svg>`;
}
function chartLegend() {
  const lg = el('div', 'legend-row');
  [['line', '#1f3864', 'Cases'], ['line', '#c00000', 'Deaths'], ['dash', '#e0a000', 'Alert threshold'], ['dash', '#e00000', 'Epidemic threshold']].forEach(([k, c, t]) => {
    const sp = el('span'), i = el('i', k); if (k === 'dash') i.style.borderColor = c; else i.style.background = c; sp.append(i, t); lg.append(sp);
  });
  return lg;
}

/* ---------- dashboard ---------- */
async function loadDashboard() {
  let r;
  try { r = await api('/api/men/report?' + periodQuery({ kind: 'dashboard' })); } catch (e) { toast(e.message); return; }
  const t = r.total;
  const k = [['', num(t.cases), 'Cases'], ['deaths', num(t.deaths), 'Deaths'], ['', pc(t.cfr) + (t.cfr == null ? '' : '%'), 'Case fatality rate'],
    ['', pc(r.confirmedPct) + (r.confirmedPct == null ? '' : '%'), 'Confirmed (' + num(r.confirmed) + ')'], ['week', num(r.weekCases), 'Cases in week ' + r.week.w]];
  $('#kpis').replaceChildren(...k.map(([c, v, l]) => { const d = el('div', 'stat ' + c); d.append(el('b', null, v), el('span', null, l)); return d; }));
  const box = $('#dashAlerts'); box.replaceChildren();
  const top = el('div', 'toolbar'); top.append(el('p', 'label', 'Sub-districts over a threshold in epi week ' + r.week.w + ' of ' + r.week.y), el('span', 'note', 'Thresholds: ' + thresholdText()));
  const grid = el('div', 'alerts');
  [['epidemic', 'Epidemic', r.epidemic], ['alert', 'Alert', r.alert]].forEach(([cls, name, list]) => {
    const col = el('div'); col.append(el('p', 'label', name + ' (' + list.length + ')'));
    const l = el('div', 'alist');
    if (!list.length) l.append(el('span', 'none', 'None this week.'));
    list.forEach(a => l.append(el('span', cls, a.label + ' · ' + a.area + ' · ' + a.cases)));
    col.append(l); grid.append(col);
  });
  box.append(top, grid);
  epiCurve($('#dashCurve'), r.weeks, r.curve);
  $('#dashCurveNote').textContent = r.period;
  $('#dashAreaLabel').textContent = 'By ' + AREA.toLowerCase();
  $('#dashAsOf').textContent = 'Data as of ' + r.asOf + (r.otherRegion ? ' · ' + plural(r.otherRegion, 'case') + ' living in other regions not included' : '');
  const tb = $('#dashAreas');
  tb.innerHTML = `<thead><tr><th>${AREA}</th><th class="n">Population</th><th class="n">Cases</th><th class="n">Deaths</th><th class="n">CFR %</th><th class="n">Week ${r.week.w}</th><th>Status</th></tr></thead>` +
    '<tbody>' + r.areas.map(a => `<tr><td>${esc(a.label)}</td><td class="n muted">${a.population ? num(a.population) : '—'}</td><td class="n">${num(a.cases)}</td><td class="n">${num(a.deaths)}</td><td class="n">${pc(a.cfr)}</td><td class="n">${num(a.week)}</td><td>${a.status ? `<span class="st ${a.status}">${a.status}</span>` : ''}</td></tr>`).join('') + '</tbody>' +
    `<tfoot><tr><td>Total</td><td></td><td class="n">${num(t.cases)}</td><td class="n">${num(t.deaths)}</td><td class="n">${pc(t.cfr)}</td><td class="n">${num(r.weekCases)}</td><td></td></tr></tfoot>`;
}
function thresholdText() {
  const c = DATA.cfg;
  return `alert ${c.alertRate}, epidemic ${c.epidemicRate} per 100,000 a week; at or under ${num(c.cutoff)} people, ${c.alertCases} and ${c.epidemicCases} cases`;
}

/* ---------- line list ---------- */
const L = { q: '', district: '', classification: '', outcome: '', year: '', other: '0', page: 1 };
options($('#lDistrict'), DATA.districts.map(([, n]) => [n, n]), DATA.national ? 'All regions' : 'All districts');
options($('#lClass'), [...LISTS.classification, ['none', 'Not classified']], 'All classifications');
options($('#lOutcome'), [...LISTS.outcome, ['none', 'Outcome not given']], 'All outcomes');
options($('#lYear'), DATA.years.slice().reverse().map(y => [String(y), 'Season ' + (y - 1) + '/' + y]), 'All years');
let qTimer;
$('#lQ').addEventListener('input', () => { clearTimeout(qTimer); qTimer = setTimeout(() => { L.q = $('#lQ').value.trim(); L.page = 1; loadList(); }, 300); });
[['lDistrict', 'district'], ['lClass', 'classification'], ['lOutcome', 'outcome'], ['lYear', 'year']].forEach(([id, k]) =>
  $('#' + id).addEventListener('change', () => { L[k] = $('#' + id).value; L.page = 1; loadList(); }));
$('#lOther').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; L.other = b.dataset.o; L.page = 1; loadList(); });
$('#lNew').addEventListener('click', () => { caseId = null; showView('case'); });
function listQuery(extra = {}) { const { page, year, ...rest } = L; return query({ ...rest, ...(year ? { year, season: 1 } : {}), ...extra }); }
async function loadList() {
  document.querySelectorAll('#lOther button').forEach(b => b.setAttribute('aria-pressed', b.dataset.o === L.other));
  $('#dlNames').href = '/api/men/linelist.xlsx?' + listQuery({ names: 1 });
  $('#dlNoNames').href = '/api/men/linelist.xlsx?' + listQuery();
  let r;
  try { r = await api('/api/men/cases?' + listQuery({ page: L.page })); } catch (e) { toast(e.message); return; }
  $('#lOtherN').textContent = '(' + num(r.other) + ')';
  $('#lCount').textContent = plural(r.total, 'case') + (r.pages > 1 ? ' · page ' + r.page + ' of ' + r.pages : '');
  const t = $('#lTable');
  t.innerHTML = `<thead><tr><th>EPID</th><th>Name</th><th class="n">Wk</th><th>${AREA === 'Region' ? 'District' : 'District'}</th><th>Sub-district</th><th>Age</th><th>Sex</th><th>Seen</th><th>Outcome</th><th>Final result</th><th>Class</th></tr></thead>`;
  const tb = el('tbody');
  if (!r.rows.length) { const tr = el('tr'), td = el('td', 'muted', 'No cases match.'); td.colSpan = 11; tr.append(td); tb.append(tr); }
  r.rows.forEach(c => {
    const tr = el('tr'); tr.dataset.id = c.id; tr.tabIndex = 0;
    const cls = c.classification ? `<span class="cls c${c.classification}"></span>${esc(CLS[c.classification][0])}` : '<span class="cls c"></span><span class="muted">—</span>';
    tr.innerHTML = `<td class="epid">${esc(c.epid)}${c.otherRegion ? ' <span class="tag away">other region</span>' : ''}</td><td>${esc(c.name)}</td><td class="n">${c.week ?? ''}</td><td>${esc(c.district)}</td><td>${esc(c.subdistrict)}</td><td>${esc(c.age)}</td><td>${esc(c.sex)}</td><td>${dmy(c.seen)}</td><td>${esc(c.outcome)}</td><td>${esc(c.result)}</td><td>${cls}</td>`;
    tb.append(tr);
  });
  t.append(tb);
  const pg = $('#lPager'); pg.replaceChildren();
  if (r.pages > 1) {
    const b = (label, p, dis) => { const x = el('button', 'btn', label); x.type = 'button'; x.disabled = dis; x.addEventListener('click', () => { L.page = p; loadList(); }); return x; };
    pg.append(b('‹ Previous', r.page - 1, r.page <= 1), el('span', null, r.page + ' / ' + r.pages), b('Next ›', r.page + 1, r.page >= r.pages));
  }
}
$('#lTable').addEventListener('click', e => { const tr = e.target.closest('tr[data-id]'); if (tr) openExisting(Number(tr.dataset.id)); });
$('#lTable').addEventListener('keydown', e => { const tr = e.target.closest('tr[data-id]'); if (tr && e.key === 'Enter') openExisting(Number(tr.dataset.id)); });
function openExisting(id) { caseId = id; showView('case'); }

/* ---------- case form ---------- */
let caseId = null, built = false, loadedFor = undefined, auto = {}, nextSeq = null;
const LAB = ['date_specimen', 'gram', 'rapid_test', 'latex', 'culture', 'pcr', 'final_result'];
const VACC = ['vaccine_1', 'vaccine_2', 'other_vaccine'];
const REQUIRED = ['district', 'date_seen'];
const input = name => $('#caseForm [name="' + name + '"]');
function buildForm() {
  const form = $('#caseForm'); form.replaceChildren();
  const groups = [...new Set(FIELDS.map(f => f.group))];
  groups.forEach((g, gi) => {
    const sec = el('section', 'step'); const head = el('div', 'step-head');
    head.append(el('span', 'step-num', gi + 1), el('h2', null, g), el('p', null, {
      'Patient': 'Names stay in the line list: downloads can leave them out.', 'EPID number': 'Country, region, district, year and number. Filled in from the district and the date seen; change them only to match a number already given.',
      'Place': 'Where the case was reported and where the patient lives.', 'Person': 'Age in months under 1 year, otherwise in years.', 'Time': 'The epi week is the week of the date seen.',
      'Signs and symptoms': '', 'Vaccination': 'Vaccines only when Vaccinated is 1-Yes.', 'Laboratory': 'Results only when a specimen was collected.',
      'Classification': 'Note “Updated [date]” in Observations when you change a case.' }[g] || ''));
    const grid = el('div', 'grid ' + (g === 'EPID number' ? 'five' : 'three'));
    FIELDS.filter(f => f.group === g).forEach(f => grid.append(fieldBox(f)));
    sec.append(head, grid); form.append(sec);
  });
  const dl = el('datalist'); dl.id = 'districtNames'; DATA.districts.forEach(([, n]) => dl.append(Object.assign(el('option'), { value: n }))); form.append(dl);
  built = true;
}
function fieldBox(f) {
  const box = el('div', 'field' + (f.kind === 'long' ? ' wide' : '')); box.dataset.f = f.name;
  const head = el('div', 'fhead'), lab = el('label', null, f.label); lab.htmlFor = 'f_' + f.name; head.append(lab);
  if (REQUIRED.includes(f.name)) lab.append(el('span', 'req', ' *'));
  if (f.kind === 'epid' || f.name === 'sequence_no') head.append(el('span', 'auto', 'auto'));
  let inp;
  if (f.kind === 'choice' || f.kind === 'district' || f.kind === 'subdistrict') {
    inp = el('select', 'in');
    if (f.kind === 'choice') options(inp, LISTS[f.list], '');
    if (f.kind === 'district') options(inp, DATA.districts.map(([, n]) => [n, n]), 'Choose…');
  } else if (f.kind === 'long') inp = el('textarea', 'in');
  else {
    inp = el('input', 'in' + (f.kind === 'epid' || f.kind === 'int' ? ' mono' : ''));
    inp.type = f.kind === 'date' ? 'date' : f.kind === 'int' ? 'number' : 'text';
    if (f.kind === 'date') inp.max = todayIso;
    if (f.kind === 'int') { inp.min = 0; inp.inputMode = 'numeric'; if (f.name === 'age_months') inp.max = 11; }
    if (f.kind === 'epid') { inp.maxLength = 3; inp.style.textTransform = 'uppercase'; }
    if (f.kind === 'anydistrict') inp.setAttribute('list', 'districtNames');
    if (f.kind === 'text') inp.maxLength = 120;
  }
  inp.name = f.name; inp.id = 'f_' + f.name;
  box.append(head, inp);
  if (f.help) box.append(el('p', 'help', f.help));
  return box;
}
function subOptions(name) {
  const sel = input(name), keep = sel.value;
  const d = name === 'reporting_subdistrict' ? input('district').value : (DATA.districts.some(([, n]) => n === input('residence_district').value) ? input('residence_district').value : input('district').value);
  const subs = DATA.subdistricts.filter(s => !d || s.district === d);
  options(sel, subs.map(s => [String(s.id), s.name + (d ? '' : ' (' + s.district + ')')]), subs.length ? '' : 'No sub-districts on file');
  sel.value = subs.some(s => String(s.id) === keep) ? keep : '';
}
function dependencies() {
  const off = (names, isOff) => names.forEach(n => { const i = input(n); i.disabled = isOff; i.closest('.field').classList.toggle('off', isOff); });
  off(VACC, input('vaccinated').value !== '1');
  off(LAB, input('specimen_collected').value !== '1');
  off(['age_years'], input('age_months').value !== '');
  off(['age_months'], input('age_years').value !== '');
  progress(); preview();
}
function setAuto(name, value) {
  const i = input(name);
  if (!i.value || i.value === auto[name]) { i.value = value; auto[name] = value; }
}
async function preview() {
  const p = ['country_code', 'region_code', 'district_code', 'year_code'].map(n => input(n).value.trim().toUpperCase());
  const seq = input('sequence_no').value || nextSeq;
  $('#cEpid').textContent = p.every(Boolean) ? [...p, String(seq || '?').padStart(5, '0')].join('-') : 'GHA-' + (p[1] || '…') + '-…';
  const chips = [input('district').value, input('date_seen').value && 'Seen ' + dmy(input('date_seen').value), input('final_classification').value && CLS[input('final_classification').value][0]].filter(Boolean);
  $('#cChips').replaceChildren(...chips.map(c => el('span', null, c)));
}
async function refreshSequence() {
  if (caseId) return;
  const p = { country: input('country_code').value, region: input('region_code').value, district: input('district_code').value, year: input('year_code').value };
  try { const r = await api('/api/men/next-epid?' + query(p)); nextSeq = r.sequence; input('sequence_no').placeholder = r.sequence ? 'next: ' + r.sequence : ''; } catch (_) { nextSeq = null; }
  preview();
}
function wireForm() {
  const form = $('#caseForm');
  form.addEventListener('input', e => { const f = e.target.closest('.field'); if (f) { f.classList.remove('invalid', 'warned'); f.querySelectorAll('.err,.warn').forEach(x => x.remove()); } dependencies(); });
  input('district').addEventListener('change', () => {
    const code = (DATA.districts.find(([, n]) => n === input('district').value) || [''])[0];
    setAuto('district_code', code); subOptions('reporting_subdistrict'); subOptions('residence_subdistrict'); refreshSequence();
  });
  input('residence_district').addEventListener('change', () => subOptions('residence_subdistrict'));
  input('date_seen').addEventListener('change', () => { const v = input('date_seen').value; if (v) { setAuto('year_code', v.slice(2, 4)); refreshSequence(); } });
  ['country_code', 'region_code', 'district_code', 'year_code'].forEach(n => input(n).addEventListener('change', refreshSequence));
  form.addEventListener('submit', e => { e.preventDefault(); saveCase(); });
}
function progress() {
  const live = FIELDS.filter(f => !input(f.name).disabled);
  const done = live.filter(f => input(f.name).value !== '').length;
  $('#cProg').textContent = done + ' of ' + live.length + ' filled' + (caseId ? '' : ' · * required');
  $('#cFill').style.width = (100 * done / Math.max(1, live.length)) + '%';
}
function fillForm(values) {
  auto = {};
  FIELDS.forEach(f => { if (f.kind !== 'subdistrict') input(f.name).value = values[f.name] ?? ''; });
  subOptions('reporting_subdistrict'); subOptions('residence_subdistrict');
  input('reporting_subdistrict').value = values.reporting_subdistrict ?? '';
  input('residence_subdistrict').value = values.residence_subdistrict ?? '';
  document.querySelectorAll('#caseForm .field').forEach(f => { f.classList.remove('invalid', 'warned'); f.querySelectorAll('.err,.warn').forEach(x => x.remove()); });
  dependencies();
}
async function openCase() {
  if (!built) { buildForm(); wireForm(); }
  $('#caseTabText').textContent = caseId ? 'Edit case' : 'New case';
  $('#title').textContent = caseId ? 'Edit case' : 'New case';
  if (loadedFor === caseId) return;  // switching tabs keeps what was typed
  loadedFor = caseId;
  $('#cHistory').hidden = true; $('#cDelete').hidden = true;
  if (!caseId) {
    $('#cMode').textContent = 'New case'; $('#cBadge').textContent = DATA.regionLabel;
    fillForm({ country_code: 'GHA', region_code: DATA.epidRegion });
    auto = { country_code: 'GHA', region_code: DATA.epidRegion };
    nextSeq = null; input('sequence_no').placeholder = ''; preview();
    return;
  }
  try {
    const r = await api('/api/men/case?id=' + caseId);
    fillForm(r.fields); input('sequence_no').placeholder = '';
    $('#cMode').textContent = 'Editing ' + r.epid; $('#cBadge').textContent = 'Entered by ' + (r.createdBy || 'import') + ' · ' + dmy(String(r.created).slice(0, 10));
    $('#cDelete').hidden = !r.canDelete;
    const h = $('#cHist'); h.replaceChildren();
    r.history.forEach(e => {
      const li = el('li'); li.append(el('b', null, dmy(String(e.at).slice(0, 10)) + ' ' + String(e.at).slice(11, 16) + ' · ' + e.action + ' by ' + (e.user || '—')));
      if (e.changes.length) li.append(el('div', 'muted', e.changes.slice(0, 12).map(([f, o, n]) => f + ': ' + (o || '∅') + ' → ' + (n || '∅')).join(' · ') + (e.changes.length > 12 ? ' …' : '')));
      h.append(li);
    });
    $('#cHistory').hidden = !r.history.length;
  } catch (e) { toast(e.message); caseId = null; loadedFor = undefined; showView('list'); }
}
function formValues() {
  const out = {};
  FIELDS.forEach(f => { const i = input(f.name); out[f.name] = i.disabled ? '' : (f.kind === 'epid' ? i.value.trim().toUpperCase() : i.value); });
  return out;
}
function mark(list, cls) {
  list.forEach(({ field, msg }) => {
    const box = document.querySelector('#caseForm .field[data-f="' + field + '"]');
    if (!box) { toast(msg); return; }
    box.classList.add(cls === 'err' ? 'invalid' : 'warned'); box.append(el('p', cls, msg));
  });
}
async function saveCase() {
  const missing = REQUIRED.filter(n => !input(n).value);
  document.querySelectorAll('#caseForm .err,#caseForm .warn').forEach(x => x.remove());
  document.querySelectorAll('#caseForm .field').forEach(f => f.classList.remove('invalid', 'warned'));
  if (missing.length) { mark(missing.map(n => ({ field: n, msg: 'Required.' })), 'err'); input(missing[0]).focus(); toast('Fill in the required fields.'); return; }
  const btn = $('#cSave'); btn.disabled = true;
  try {
    const r = await postJson('/api/men/case/save', { id: caseId, fields: formValues() });
    const wasNew = !caseId;
    caseId = r.id; loadedFor = undefined;
    await openCase();
    mark(r.warnings, 'warn');
    toast((wasNew ? 'Added ' : 'Saved ') + r.epid + (r.warnings.length ? ' · check the notes in yellow' : ''));
    refreshData();
  } catch (e) {
    if (e.body && e.body.errors) { mark(e.body.errors, 'err'); const first = document.querySelector('#caseForm .invalid'); if (first) first.scrollIntoView({ block: 'center' }); }
    toast(e.message);
  } finally { btn.disabled = false; }
}
$('#cReset').addEventListener('click', () => { caseId = null; loadedFor = undefined; openCase(); history.replaceState(null, '', '#case'); });
$('#cDelete').addEventListener('click', async () => {
  if (!caseId || !confirm('Delete ' + $('#cEpid').textContent + ' from the line list? This cannot be undone.')) return;
  try { const r = await postJson('/api/men/case/delete', { id: caseId }); toast('Deleted ' + r.deleted); caseId = null; loadedFor = undefined; refreshData(); showView('list'); }
  catch (e) { toast(e.message); }
});
async function refreshData() { try { DATA = { ...DATA, ...(await api('/api/men/data')) }; renderStatus(); fillFilters(); } catch (_) {} }

/* ---------- upload ---------- */
let upFile = null;
$('#uDrop').addEventListener('click', () => $('#uFile').click());
$('#uFile').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; if (f) upload(f, false); });
['dragover', 'dragenter'].forEach(t => $('#uDrop').addEventListener(t, e => { e.preventDefault(); $('#uDrop').classList.add('over'); }));
['dragleave', 'drop'].forEach(t => $('#uDrop').addEventListener(t, () => $('#uDrop').classList.remove('over')));
$('#uDrop').addEventListener('drop', e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) upload(f, false); });
async function upload(file, apply) {
  if (file.size > 10 * 1024 * 1024) { toast('That file is over 10 MB.'); return; }
  upFile = file;
  const box = $('#uPlan'); box.hidden = false; box.replaceChildren(el('p', 'label', apply ? 'Saving…' : 'Reading ' + file.name + '…'));
  try {
    const plan = await api('/api/men/import?' + query({ name: file.name, apply: apply ? 1 : 0 }), { method: 'POST', body: await file.arrayBuffer() });
    renderPlan(plan);
    if (apply) { toast('Line list updated'); refreshData(); }
  } catch (e) { box.replaceChildren(el('p', 'err', e.message)); }
}
function renderPlan(p) {
  const box = $('#uPlan'); box.replaceChildren();
  const top = el('div', 'toolbar'); top.append(el('p', 'label', (p.saved ? 'Saved from ' : 'Review: ') + upFile.name), el('span', 'note', 'Sheets read: ' + p.sheets.join(', ') + ' · ' + plural(p.rows, 'row')));
  const tally = el('div', 'tally');
  [['report', p.counts.added, p.saved ? 'Added' : 'New cases'], ['closed', p.counts.updated, p.saved ? 'Updated' : 'Cases to update'], ['', p.unchanged, 'Unchanged'], ['soon', p.skipped, 'No EPID: skipped'], ['past', p.counts.errors, 'Rows with errors']]
    .forEach(([c, n, l]) => { const d = el('div', 'stat ' + c); d.append(el('b', null, num(n)), el('span', null, l)); tally.append(d); });
  box.append(top, tally);
  const group = (title, items, render) => {
    if (!items.length) return;
    const g = el('div', 'plan-group'); g.append(el('p', 'label', title));
    const l = el('div', 'plan-list'); items.forEach(i => l.append(render(i))); g.append(l); box.append(g);
  };
  group('Errors: these rows are not saved', p.errors, e => { const d = el('div', 'problem'); d.append(el('b', null, e.sheet + ' row ' + e.row + ' · ' + e.epid + ' '), e.msgs.join(' · ')); return d; });
  group('Codes read another way', p.warnings, w => { const d = el('div', 'problem'); d.append(el('b', null, '×' + w.n + ' '), w.text); return d; });
  group('New sub-districts (add their populations under Sub-districts and thresholds)', p.newSubdistricts, s => el('div', 'problem', s));
  group('Updates' + (p.counts.updated > p.updated.length ? ' (first ' + p.updated.length + ')' : ''), p.updated, u => {
    const d = el('div', 'change'); d.append(el('b', 'epid', u.epid));
    u.changes.slice(0, 10).forEach(([f, o, n]) => { const c = el('div', 'cell'); c.append(el('span', 'tag', f), el('span', 'old', o || '∅'), el('span', 'arrow', '→'), el('span', 'new', n)); d.append(c); });
    return d;
  });
  group('New cases' + (p.counts.added > p.added.length ? ' (first ' + p.added.length + ')' : ''), p.added, a => el('div', 'problem', a.epid + ' · ' + a.sheet + ' row ' + a.row));
  const bar = el('div', 'toolbar');
  if (p.saved) { const b = el('button', 'btn solid', 'Open the line list'); b.type = 'button'; b.addEventListener('click', () => showView('list')); bar.append(el('span', 'note', plural(p.counts.inRegion, 'case') + ' in the line list now.'), b); }
  else {
    const cancel = el('button', 'btn', 'Cancel'), go = el('button', 'btn solid', 'Apply ' + plural(p.counts.added + p.counts.updated, 'change'));
    cancel.type = go.type = 'button'; go.disabled = !(p.counts.added + p.counts.updated);
    cancel.addEventListener('click', () => { box.hidden = true; });
    go.addEventListener('click', () => { go.disabled = true; upload(upFile, true); });
    const actions = el('div', 'dlrow'); actions.append(cancel, go);
    bar.append(el('span', 'note', p.counts.errors ? 'Rows with errors are left out. Correct them in the file and upload it again.' : ''), actions);
  }
  box.append(bar);
}

/* ---------- reports ---------- */
let RKIND = 'weekly';
const RLIST = Object.entries(DATA.reports).filter(([k]) => k !== 'dashboard');
$('#rKinds').replaceChildren(...RLIST.map(([k, name]) => { const b = el('button', null, name); b.type = 'button'; b.setAttribute('role', 'tab'); b.dataset.k = k; return b; }));
$('#rKinds').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { RKIND = b.dataset.k; loadReport(); } });
let REP = null;
async function loadReport() {
  document.querySelectorAll('#rKinds button').forEach(b => b.setAttribute('aria-selected', b.dataset.k === RKIND));
  const q = periodQuery({ kind: RKIND });
  $('#rXlsx').href = '/api/men/report.xlsx?' + q;
  const sheet = $('#rSheet'); sheet.replaceChildren(el('p', 'rempty', 'Working out the report…'));
  try { REP = await api('/api/men/report?' + q); } catch (e) { sheet.replaceChildren(el('p', 'rempty', e.message)); return; }
  sheet.innerHTML = `<h2>${esc(REP.title)}</h2><p class="sub">${esc(REP.period)} · ${plural(REP.cases, 'case')} with a valid EPID number</p>`;
  ({ weekly: rWeekly, district: rDistrict, regional: rRegional, epicurve: rEpicurve, vaccination: rCounts, laboratory: rCounts, thresholds: rThresholds })[REP.kind](sheet, REP);
  const foot = el('div', 'rfoot');
  foot.append(el('span', null, 'Source: meningitis line list, ' + REP.region + '. Data as of ' + REP.asOf + '.' + (REP.otherRegion ? ' ' + plural(REP.otherRegion, 'case') + ' living in other regions are not included.' : '')),
    el('span', null, 'Ghana Health Service · Disease Surveillance'));
  sheet.append(foot);
}
const yearRow = (weeks, lead, per = 1, tail = 1) => {
  const spans = []; weeks.forEach(w => { const l = spans[spans.length - 1]; if (l && l[0] === w.y) l[1]++; else spans.push([w.y, 1]); });
  return `<tr><th class="sticky l" colspan="${lead}"></th>${spans.map(([y, n]) => `<th colspan="${n * per}">${y}</th>`).join('')}<th colspan="${tail}"></th></tr>`;
};
const cells = (vals, status = []) => vals.map((v, i) => `<td class="${status[i] || ''}">${v || ''}</td>`).join('');
function rWeekly(sheet, r) {
  const wk = r.weeks.map(w => `<th>${w.w}</th>`).join('');
  let h = `<div class="rscroll"><table class="rtab"><thead>${yearRow(r.weeks, 6)}<tr><th class="sticky l">${r.areaLabel}</th><th class="l">Sub-district</th><th>Pop.</th><th>Alert</th><th>Epid.</th><th></th>${wk}<th>Total</th></tr></thead><tbody>`;
  r.groups.forEach(g => {
    g.rows.forEach((s, k) => {
      const lim = v => v == null ? '—' : num(v);
      h += `<tr><td class="sticky l">${k ? '' : esc(g.area)}</td><td class="l">${esc(s.label)}</td><td>${s.population ? num(s.population) : '—'}</td><td>${lim(s.alert)}</td><td>${lim(s.epidemic)}</td><td>C</td>${cells(s.c, s.status)}<td><b>${s.cases}</b></td></tr>`;
      h += `<tr><td class="sticky l"></td><td></td><td></td><td></td><td></td><td>D</td>${cells(s.d)}<td><b>${s.deaths}</b></td></tr>`;
    });
    if (!g.rows.length) h += `<tr><td class="sticky l">${esc(g.area)}</td><td class="l" colspan="${6 + r.weeks.length}"><i>No sub-districts on file</i></td></tr>`;
    h += `<tr class="grp"><td class="sticky l">${esc(g.area)} total</td><td></td><td></td><td></td><td></td><td>C</td>${cells(g.total.c)}<td>${g.total.cases}</td></tr><tr class="grp"><td class="sticky l"></td><td></td><td></td><td></td><td></td><td>D</td>${cells(g.total.d)}<td>${g.total.deaths}</td></tr>`;
  });
  h += `<tr class="tot"><td class="sticky l">${esc(r.region)}</td><td></td><td></td><td></td><td></td><td>C</td>${cells(r.total.c)}<td>${r.total.cases}</td></tr><tr class="tot"><td class="sticky l"></td><td></td><td></td><td></td><td></td><td>D</td>${cells(r.total.d)}<td>${r.total.deaths}</td></tr>`;
  sheet.insertAdjacentHTML('beforeend', h + '</tbody></table></div><div class="rlegend"><span class="a">Alert</span><span class="e">Epidemic</span><span>C cases · D deaths · Alert and Epid.: cases in a week</span></div>');
}
function rDistrict(sheet, r) {
  const n = r.weeks.length;
  let h = `<div class="rscroll"><table class="rtab"><thead>${yearRow(r.weeks, 1, 2, 2)}<tr><th class="sticky l" rowspan="2">${r.areaLabel}</th>${r.weeks.map(w => `<th colspan="2">${w.w}</th>`).join('')}<th colspan="2">Total</th></tr><tr>${'<th>C</th><th>D</th>'.repeat(n + 1)}</tr></thead><tbody>`;
  const row = (label, x, cls = '') => `<tr class="${cls}"><td class="sticky l">${esc(label)}</td>${x.c.map((c, i) => `<td class="${(x.status || [])[i] || ''}">${c || ''}</td><td>${x.d[i] || ''}</td>`).join('')}<td><b>${x.cases}</b></td><td><b>${x.deaths}</b></td></tr>`;
  r.rows.forEach(x => h += row(x.label, x));
  h += row(r.region + ' total', r.total, 'tot');
  sheet.insertAdjacentHTML('beforeend', h + '</tbody></table></div><div class="rlegend"><span class="a">Alert</span><span class="e">Epidemic</span><span>C cases · D deaths</span></div>');
}
function smallTable(title, head, rows, total) {
  return `<div><h3>${esc(title)}</h3><table class="rtab full"><thead><tr>${head.map((x, i) => `<th class="${i ? '' : 'l'}">${esc(x)}</th>`).join('')}</tr></thead><tbody>` +
    rows.map(r => `<tr>${r.map((v, i) => `<td class="${i ? '' : 'l'}">${esc(v)}</td>`).join('')}</tr>`).join('') +
    (total ? `<tr class="tot">${total.map((v, i) => `<td class="${i ? '' : 'l'}">${esc(v)}</td>`).join('')}</tr>` : '') + '</tbody></table></div>';
}
function rRegional(sheet, r) {
  const t = r.total, tot = ['Total', num(t.cases), num(t.deaths), pc(t.cfr)];
  const cdc = x => [x.label, num(x.cases), num(x.deaths), pc(x.cfr)];
  sheet.insertAdjacentHTML('beforeend', '<div class="rgrid">' +
    smallTable('By ' + r.areaLabel.toLowerCase(), [r.areaLabel, 'Cases', 'Deaths', 'CFR %'], r.areas.map(cdc), tot) +
    smallTable('By age group (years)', ['Age group', 'Cases', 'Deaths', 'CFR %'], r.ages.map(cdc), tot) +
    smallTable('By sex', ['Sex', 'Cases', 'Deaths'], r.sexes.map(x => [x.label, num(x.cases), num(x.deaths)]), tot.slice(0, 3)) +
    smallTable('By final lab result', ['Final lab result', 'Cases', 'Deaths'], r.pathogens.map(x => [x.label, num(x.cases), num(x.deaths)]), tot.slice(0, 3)) +
    '</div>' + smallTable('By sub-district', [r.areaLabel, 'Sub-district', 'Cases', 'Deaths', 'CFR %'], r.subdistricts.map(x => [x.area, x.label, num(x.cases), num(x.deaths), pc(x.cfr)]), ['Total', '', num(t.cases), num(t.deaths), pc(t.cfr)]));
}
function rEpicurve(sheet, r) {
  const box = el('div', 'chart'); sheet.append(box); epiCurve(box, r.weeks, r.series);
  let h = `<h3>Cases by epi week</h3><div class="rscroll"><table class="rtab"><thead>${yearRow(r.weeks, 1)}<tr><th class="sticky l">Final classification</th>${r.weeks.map(w => `<th>${w.w}</th>`).join('')}<th>Total</th></tr></thead><tbody>`;
  r.series.forEach(s => h += `<tr><td class="sticky l">${esc(s.label)}</td>${cells(s.values)}<td><b>${s.total}</b></td></tr>`);
  const tot = r.weeks.map((_, i) => r.series.reduce((a, s) => a + s.values[i], 0));
  h += `<tr class="tot"><td class="sticky l">Total</td>${cells(tot)}<td>${r.cases}</td></tr></tbody></table></div>`;
  sheet.insertAdjacentHTML('beforeend', h);
}
function rCounts(sheet, r) {
  let h = '';
  if (r.indicators) h += smallTable('Indicators', ['Indicator', 'Number', 'Of', '%', ''], r.indicators.map(i => [i.label, num(i.n), num(i.of), pc(i.pct), i.note]));
  h += '<div class="rgrid">' + r.tables.map(t => smallTable(t.title, [t.title, 'Cases', '%'], t.rows.map(x => [x.label, num(x.n), pc(x.pct)]), ['Total', num(t.total), t.total ? '100.0' : '—'])).join('');
  if (r.pathogens) h += smallTable('Pathogens found', ['Pathogen', 'Cases'], r.pathogens.map(p => [p.label, num(p.n)]), ['Total', num(r.pathogens.reduce((a, p) => a + p.n, 0))]);
  h += '</div>';
  if (r.completeness) h += smallTable('Data completeness', ['Field', 'Missing', '% complete'], r.completeness.map(c => [c.label, num(c.missing), pc(c.pct)]));
  sheet.insertAdjacentHTML('beforeend', h);
}
function rThresholds(sheet, r) {
  sheet.append(chartLegend());
  if (!r.charts.length) { sheet.append(el('p', 'rempty', 'No sub-districts on file. Add them under Sub-districts and thresholds, or upload the line list.')); return; }
  const grid = el('div', 'tcharts');
  r.charts.forEach(c => {
    const worst = c.status.includes('epidemic') ? 'epidemic' : c.status.includes('alert') ? 'alert' : '';
    const box = el('div', 'tchart ' + worst), body = el('div', 'chart');
    box.append(el('h4', null, c.title), el('p', 'meta', c.area + ' · ' + (c.population ? 'population ' + num(c.population) : 'no population on file') + ' · alert ' + c.alert + ', epidemic ' + c.epidemic + ' cases a week · ' + c.cases + ' cases, ' + c.deaths + ' deaths'), body);
    thresholdChart(body, r.weeks, c); grid.append(box);
  });
  sheet.append(grid);
}
$('#rPdf').addEventListener('click', () => {
  if (!REP) return;
  const title = document.title; document.title = 'Meningitis ' + REP.name + ' - ' + REP.region; document.body.classList.add('print-men');
  const done = () => { document.body.classList.remove('print-men'); document.title = title; window.removeEventListener('afterprint', done); };
  window.addEventListener('afterprint', done);
  toast('Choose “Save as PDF” as the printer');
  setTimeout(() => window.print(), 50);
});

/* ---------- sub-districts and thresholds ---------- */
let removed = [];
function renderSetup() {
  removed = [];
  const t = $('#sTable'), w = DATA.canWrite;
  $('#sCount').textContent = plural(DATA.subdistricts.length, 'sub-district');
  t.innerHTML = `<thead><tr>${DATA.national ? '<th>Region</th>' : ''}<th>District</th><th>Sub-district</th><th class="n">Population</th><th class="n">Alert</th><th class="n">Epidemic</th>${w ? '<th></th>' : ''}</tr></thead>`;
  const tb = el('tbody'); t.append(tb);
  DATA.subdistricts.slice().sort((a, b) => (a.district + a.name).localeCompare(b.district + b.name)).forEach(s => tb.append(subRow(s)));
  $('#sAdd').hidden = $('#sSave').hidden = !w; $('#sErr').textContent = '';
  const c = DATA.cfg;
  [['tAlert', c.alertRate], ['tEpi', c.epidemicRate], ['tCut', c.cutoff], ['tAc', c.alertCases], ['tEc', c.epidemicCases], ['tStart', c.seasonStart]].forEach(([id, v]) => { $('#' + id).value = v; $('#' + id).disabled = !w; });
  $('#tSave').hidden = !w;
  $('#tNote').textContent = c.saved ? 'Saved for ' + DATA.regionLabel : 'WHO defaults (not changed for ' + DATA.regionLabel + ')';
}
function limits(pop) {
  const c = DATA.cfg;
  return pop && pop > c.cutoff ? [Math.round(c.alertRate * pop / 1e4) / 10, Math.round(c.epidemicRate * pop / 1e4) / 10] : [c.alertCases, c.epidemicCases];
}
function subRow(s) {
  const tr = el('tr'); tr.dataset.id = s.id || '';
  const [a, e] = limits(s.population);
  if (!DATA.canWrite) {
    tr.innerHTML = `${DATA.national ? `<td>${esc(s.region)}</td>` : ''}<td>${esc(s.district)}</td><td>${esc(s.name)}</td><td class="n">${s.population ? num(s.population) : '—'}</td><td class="n">${a}</td><td class="n">${e}</td>`;
    return tr;
  }
  const d = el('select', 'in'); options(d, DATA.districts.map(([, n]) => [n, n]), 'Choose…'); d.value = s.district || ''; d.dataset.k = 'district';
  const n = el('input', 'in'); n.value = s.name || ''; n.maxLength = 80; n.dataset.k = 'name';
  const p = el('input', 'in mono'); p.type = 'number'; p.min = 0; p.value = s.population ?? ''; p.dataset.k = 'population';
  const al = el('td', 'n muted', a), ep = el('td', 'n muted', e);
  p.addEventListener('input', () => { const [x, y] = limits(Number(p.value) || null); al.textContent = x; ep.textContent = y; });
  const x = el('button', 'btn danger', 'Remove'); x.type = 'button';
  x.addEventListener('click', () => { if (s.id) removed.push(s.id); tr.remove(); });
  [d, n, p].forEach(i => { const td = el('td'); td.append(i); tr.append(td); });
  const xt = el('td', 'x'); xt.append(x); tr.append(al, ep, xt);
  return tr;
}
$('#sAdd').addEventListener('click', () => { const tr = subRow({}); $('#sTable tbody').prepend(tr); tr.querySelector('select').focus(); });
$('#sSave').addEventListener('click', async () => {
  const rows = [...document.querySelectorAll('#sTable tbody tr')].map(tr => {
    const o = { id: tr.dataset.id ? Number(tr.dataset.id) : null }; tr.querySelectorAll('[data-k]').forEach(i => o[i.dataset.k] = i.value); return o;
  }).filter(r => r.id || r.name);
  const btn = $('#sSave'); btn.disabled = true;
  try {
    const r = await postJson('/api/men/subdistricts', { rows, delete: removed });
    DATA.subdistricts = r.subdistricts; renderSetup();
    $('#sErr').textContent = r.problems.join(' ');
    toast(r.problems.length ? 'Saved, with problems: see below the table' : 'Sub-districts saved');
  } catch (e) { toast(e.message); } finally { btn.disabled = false; }
});
$('#tSave').addEventListener('click', async () => {
  const body = { alertRate: $('#tAlert').value, epidemicRate: $('#tEpi').value, cutoff: $('#tCut').value, alertCases: $('#tAc').value, epidemicCases: $('#tEc').value, seasonStart: $('#tStart').value };
  try { const r = await postJson('/api/men/thresholds', body); DATA.cfg = r.cfg; renderSetup(); fillFilters(); toast('Thresholds saved'); } catch (e) { toast(e.message); }
});

showView(location.hash.slice(1) || 'dashboard');
