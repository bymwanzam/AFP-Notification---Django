const DATA = JSON.parse(document.getElementById('page-data').textContent);
const $ = s => document.querySelector(s);
const setup = DATA.mode === 'setup', forced = DATA.mode === 'change', change = forced || DATA.mode === 'password';
if (change) {
  $('#slug').textContent = 'SECURITY';
  $('#title').textContent = forced ? 'Set a new password' : 'Change your password';
  $('#lede').textContent = forced ? 'This account must set its own password before going on.' : 'Enter your current password, then the new one.';
  $('#fUser').hidden = true;
  $('#passLabel').textContent = 'Current password';
  $('#fNew').hidden = $('#fConfirm').hidden = false;
  $('#confirmLabel').textContent = 'New password again';
  $('#go').textContent = forced ? 'Save new password and continue' : 'Save new password';
  $('#form').append(Object.assign(document.createElement('a'), forced
    ? { href: '/logout', className: 'out', textContent: 'Sign out instead' }
    : { href: DATA.next, className: 'out', textContent: 'Cancel' }));
}
if (setup) {
  $('#slug').textContent = 'FIRST-TIME SET-UP';
  $('#title').textContent = 'Create your account';
  $('#lede').textContent = 'No accounts exist yet. Choose your region: this account signs in to both modules for that region.';
  $('#fName').hidden = $('#fRegion').hidden = $('#fConfirm').hidden = $('#setupNote').hidden = false;
  const sel = $('#region'), ph = new Option('Choose your region…', '');
  sel.append(ph, new Option('Ghana (national administrator: all regions)', 'Ghana'), ...DATA.regions.map(n => new Option(n + ' Region', n)));
  sel.addEventListener('change', () => $('#regionHint').textContent = sel.value === 'Ghana'
    ? 'A national account works with every region: Ghana’s figures by region, and any region’s own data.'
    : 'The account works for this region and its districts only.');
  $('#pass').autocomplete = 'new-password';
  $('#go').textContent = 'Create account and sign in';
}
document.querySelectorAll('.reveal').forEach(b => b.addEventListener('click', () => {
  const i = document.getElementById(b.dataset.for), show = i.type === 'password';
  i.type = show ? 'text' : 'password'; b.textContent = show ? 'Hide' : 'Show'; b.setAttribute('aria-pressed', show);
}));
(setup ? $('#name') : change ? $('#pass') : $('#user')).focus();

async function post(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'X-CSRFToken': csrfToken(), 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const res = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(res.error || 'Something went wrong (' + r.status + ').');
  return res;
}

$('#form').addEventListener('submit', async e => {
  e.preventDefault();
  const go = $('#go'), label = go.textContent, err = $('#err');
  if (change) {
    const body = { current: $('#pass').value, password: $('#newpass').value, confirm: $('#confirm').value, next: DATA.next };
    if (!body.current || !body.password) { err.textContent = 'Enter your current and new passwords.'; return; }
    err.textContent = ''; go.disabled = true; go.replaceChildren(Object.assign(document.createElement('span'), { className: 'spin' }), 'Saving…');
    try { location.replace((await post('/api/password', body)).go || '/start'); }
    catch (ex) { err.textContent = ex.message; go.disabled = false; go.textContent = label; }
    return;
  }
  const body = { username: $('#user').value.trim(), password: $('#pass').value, next: DATA.next };
  if (!body.username || !body.password) { err.textContent = 'Enter your username and password.'; return; }
  if (setup && !$('#region').value) { err.textContent = 'Choose your region.'; $('#region').focus(); return; }
  if (setup) Object.assign(body, { name: $('#name').value.trim(), region: $('#region').value, confirm: $('#confirm').value });
  err.textContent = ''; go.disabled = true; go.replaceChildren(Object.assign(document.createElement('span'), { className: 'spin' }), setup ? 'Creating account…' : 'Signing in…');
  try {
    location.replace((await post(setup ? '/api/setup' : '/api/login', body)).go || '/start');
  } catch (ex) {
    err.textContent = ex.message; go.disabled = false; go.textContent = label;
    if (!setup) { $('#pass').value = ''; $('#pass').focus(); }
  }
});
document.querySelectorAll('.year').forEach(e => e.textContent = new Date().getFullYear());
