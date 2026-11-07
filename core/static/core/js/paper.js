/* Report background colour, shared by the AFP district report and the IDSR bulletin. The choice is kept per
   report in this browser and is used on screen and in every export (PNG, PDF, Excel). */

const PAPERS = [['White', '#ffffff'], ['Cream', '#fff8e7'], ['Light yellow', '#fffbd6'], ['Light blue', '#e8f1fb'],
  ['Light green', '#e2f0d9'], ['Bulletin green', '#92d050'], ['Light grey', '#f0f0f0'], ['Light pink', '#fde9ec']];
function paperPicker(box, key, fallback, apply) {
  const pick = box.querySelector('input[type=color]'), note = box.querySelector('.paper-note');
  const list = [PAPERS.find(p => p[1] === fallback), ...PAPERS.filter(p => p[1] !== fallback)];
  let current = fallback;
  list.forEach(([name, hex]) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'swatch'; b.dataset.c = hex; b.style.setProperty('--c', hex);
    b.title = name + (hex === fallback ? ' (default)' : ''); b.setAttribute('aria-label', b.title);
    b.addEventListener('click', () => set(hex, true));
    box.querySelector('.swatches').append(b);
  });
  pick.addEventListener('input', () => set(pick.value, true));
  function set(hex, save) {
    hex = /^#[0-9a-f]{6}$/i.test(hex || '') ? hex.toLowerCase() : fallback;
    current = hex; pick.value = hex;
    box.querySelectorAll('.swatch').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.c === hex)));
    box.dataset.custom = String(!PAPERS.some(p => p[1] === hex));
    // Black text needs a light paper: warn below WCAG's 4.5:1 contrast against black.
    const lin = [1, 3, 5].map(i => { const c = parseInt(hex.slice(i, i + 2), 16) / 255; return c <= .03928 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; });
    const lum = .2126 * lin[0] + .7152 * lin[1] + .0722 * lin[2];
    note.textContent = (lum + .05) / .05 < 4.5 ? 'This colour is too dark for black text to read well. A lighter colour prints better.' : '';
    if (save) try { localStorage.setItem(key, hex); } catch (_) {}
    apply(hex);
  }
  let saved = null; try { saved = localStorage.getItem(key); } catch (_) {}
  set(saved, false);
  return () => current;
}
