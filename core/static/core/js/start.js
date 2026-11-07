const DATA = JSON.parse(document.getElementById('page-data').textContent);
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, 3600); }

const sel = $('#region');
const ph = el('option', null, 'Choose a region…'); ph.value = ''; sel.append(ph);
DATA.regions.forEach(r => { const o = el('option', null, r.name + (r.national ? ' (national, all regions)' : ' Region')); o.value = r.name; sel.append(o); });
sel.value = DATA.selected || '';
$('#adminBtn').hidden = !DATA.support;
if (DATA.profile) {
  const p = DATA.profile, todo = !p.name || !p.cadre;
  $('#me').hidden = false; $('#me').classList.toggle('todo', todo);
  $('#meName').textContent = p.name || p.username;
  $('#meCadre').textContent = todo ? 'Add your full name, cadre and picture to complete your profile.' : p.cadre;
  $('#meGo').textContent = todo ? 'Complete profile' : 'Edit profile';
  if (p.photo) { const i = document.createElement('img'); i.alt = ''; i.src = '/api/profile/photo'; $('#mePic').append(i); }
  else $('#mePic').textContent = (p.name || p.username).split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
}
if (DATA.locked) {
  ph.remove(); sel.disabled = true;
  $('#pageTitle').textContent = 'Your region';
  $('#pickHint').textContent = 'Your account works for this region only: its districts in data entry, its cases in the alerts, and its figures in the reports.';
}

function show() {
  const r = DATA.regions.find(x => x.name === sel.value);
  $('#about').hidden = !r;
  document.querySelectorAll('.mod').forEach(b => b.disabled = !r);
  if (!r) return;
  $('#fDistLabel').textContent = r.national ? 'Regions' : 'Districts';
  $('#fDist').textContent = r.districts.length; $('#fAfp').textContent = r.afp; $('#fWeeks').textContent = r.weeks; $('#fMen').textContent = r.men;
  $('#chips').replaceChildren(...r.districts.map(([c, n]) => { const s = el('span'); s.append(el('b', null, c), n); return s; }));
}
sel.addEventListener('change', show);
show();
if (DATA.next) { const m = $({ idsr: '#goIdsr', meningitis: '#goMen' }[DATA.next] || '#goAfp'); m.classList.add('next'); }

// Opening a module saves the region first, so every page and alert after this uses it.
document.querySelectorAll('.mod').forEach(b => b.addEventListener('click', async () => {
  if (!sel.value) return;
  b.disabled = true;
  try {
    const r = await fetch('/api/region', { method: 'POST', headers: { 'X-CSRFToken': csrfToken(), 'Content-Type': 'application/json' }, body: JSON.stringify({ region: sel.value }) });
    if (!r.ok) throw new Error(((await r.json().catch(() => ({}))).error) || 'Could not save the region.');
    location.href = b.dataset.go;
  } catch (e) { toast(e.message); b.disabled = false; }
}));
document.querySelectorAll('.year').forEach(e => e.textContent = new Date().getFullYear());
