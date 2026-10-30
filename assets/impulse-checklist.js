// Impulse Spending Checklist. Runs entirely in the browser; nothing is sent anywhere.
// The waiting rule from "Why ADHD brains overspend": anything over a threshold
// goes on a dated list and may be bought once a fixed wait has passed. Each
// item keeps the wait that applied when it was added, so shortening the wait
// later cannot release something early.
(function () {
  const form = document.getElementById('imp-form');
  if (!form) return;

  const field = (id) => document.getElementById(id);
  const currency = field('imp-currency');
  const threshold = field('imp-threshold');
  const wait = field('imp-wait');
  const list = field('imp-list');
  const out = {
    saved: field('imp-saved'), waiting: field('imp-waiting'), bought: field('imp-bought'),
    summary: field('imp-summary'), verdict: field('imp-verdict'), note: field('imp-note'),
  };
  const STORE = 'adhd-impulse-checklist';
  const DAY = 86400000;
  let items = [];

  const load = () => {
    try { return JSON.parse(localStorage.getItem(STORE) || '{}'); } catch (e) { return {}; }
  };
  const save = () => {
    try {
      localStorage.setItem(STORE, JSON.stringify({
        currency: currency.value, threshold: threshold.value, wait: wait.value, items: items,
      }));
    } catch (e) { /* unavailable */ }
  };

  const money = (value, digits) => {
    try {
      return new Intl.NumberFormat(undefined, {
        style: 'currency', currency: currency.value,
        minimumFractionDigits: digits, maximumFractionDigits: digits,
      }).format(value);
    } catch (e) {
      return value.toFixed(digits);
    }
  };
  const day = (ms) => {
    try { return new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' }).format(new Date(ms)); }
    catch (e) { return new Date(ms).toDateString(); }
  };

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const amount = (v) => {
    const n = parseFloat(String(v).replace(/[^0-9.]/g, ''));
    return Number.isFinite(n) && n > 0 ? n : 0;
  };
  const readyAt = (item) => item.added + item.wait * DAY;

  function button(label, cls, onClick) {
    const b = el('button', cls, label);
    b.type = 'button';
    b.addEventListener('click', onClick);
    return b;
  }

  function renderList() {
    list.replaceChildren();
    if (!items.length) {
      list.appendChild(el('p', 'calc-blurb', 'Nothing waiting. Add the next thing you are about to buy.'));
      return;
    }
    const now = Date.now();
    const order = { waiting: 0, skipped: 1, bought: 2 };
    items.slice().sort((a, b) => order[a.status] - order[b.status] || a.added - b.added).forEach(item => {
      const row = el('div', 'imp-row is-' + item.status);
      const main = el('div', 'imp-main');
      main.appendChild(el('span', 'imp-item', item.name || 'Something'));
      const meta = [money(item.price, 2), 'added ' + day(item.added)];
      if (item.situation) meta.push(item.situation);
      main.appendChild(el('span', 'imp-meta', meta.join(' · ')));
      row.appendChild(main);

      const side = el('div', 'imp-side');
      if (item.status === 'waiting' && now < readyAt(item)) {
        side.appendChild(el('span', 'imp-when', 'Decide on ' + day(readyAt(item))));
      } else if (item.status === 'waiting') {
        side.appendChild(button('Still want it', 'imp-pick', () => decide(item, 'bought')));
        side.appendChild(button('Not any more', 'imp-pick is-skip', () => decide(item, 'skipped')));
      } else {
        side.appendChild(el('span', 'imp-when', item.status === 'skipped' ? 'Not bought' : 'Bought'));
      }
      const remove = button('×', 'sub-remove', () => {
        items = items.filter(i => i !== item);
        update();
      });
      remove.setAttribute('aria-label', 'Remove ' + (item.name || 'this item'));
      side.appendChild(remove);
      row.appendChild(side);
      list.appendChild(row);
    });
  }

  function decide(item, status) {
    item.status = status;
    item.decided = Date.now();
    update();
  }

  function renderSummary() {
    const sum = (s) => items.filter(i => i.status === s).reduce((t, i) => t + i.price, 0);
    const waitingItems = items.filter(i => i.status === 'waiting');
    out.saved.textContent = money(sum('skipped'), 0);
    out.waiting.textContent = waitingItems.length ? waitingItems.length + ' · ' + money(sum('waiting'), 0) : '0';
    out.bought.textContent = money(sum('bought'), 0);

    out.summary.replaceChildren();
    const counts = {};
    items.forEach(i => { if (i.situation) counts[i.situation] = (counts[i.situation] || 0) + 1; });
    const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 4);
    if (!top.length) {
      out.summary.appendChild(el('p', 'calc-empty', 'Your situations will show here as the list grows. ' +
        'Most people find four or five that account for most of it.'));
      return;
    }
    out.summary.appendChild(el('div', 'calc-label', 'Your situations'));
    const ul = el('ul', 'sub-summary-list');
    top.forEach(([name, n]) => ul.appendChild(el('li', null, name + ': ' + n + (n === 1 ? ' item' : ' items'))));
    out.summary.appendChild(ul);
    out.summary.appendChild(el('p', 'sub-nudge', 'Each one can be designed around on its own terms: a different route home, the phone in another room after ten.'));
  }

  function renderVerdict() {
    const ticked = form.querySelectorAll('#imp-checks input:checked').length;
    out.verdict.classList.toggle('is-flagged', ticked > 0);
    out.verdict.textContent = !ticked
      ? 'Nothing ticked. If it is over your limit, the wait still applies.'
      : ticked + (ticked === 1 ? ' sign' : ' signs') + ' of the state impulse buys tend to happen in. ' +
        'This is the moment to put it on the list instead.';
  }

  function update() {
    renderList();
    renderSummary();
    save();
  }

  field('imp-add').addEventListener('click', () => {
    const name = field('imp-name').value.trim();
    const price = amount(field('imp-price').value);
    if (!name && !price) {
      out.note.textContent = 'Add what it is and roughly what it costs.';
      return;
    }
    const limit = amount(threshold.value);
    out.note.textContent = limit && price && price <= limit
      ? 'That is under your limit of ' + money(limit, 0) + ', so the rule does not require a wait, but it is on the list with one anyway.'
      : 'On the list. You can decide on ' + day(Date.now() + Number(wait.value) * DAY) + '.';
    items.push({
      name: name, price: price, situation: field('imp-situation').value,
      added: Date.now(), wait: Number(wait.value), status: 'waiting',
    });
    field('imp-name').value = '';
    field('imp-price').value = '';
    field('imp-situation').value = '';
    form.querySelectorAll('#imp-checks input:checked').forEach(c => { c.checked = false; });
    renderVerdict();
    update();
  });

  field('imp-csv').addEventListener('click', () => {
    const q = (v) => '"' + String(v).replace(/"/g, '""') + '"';
    const iso = (ms) => (ms ? new Date(ms).toISOString().slice(0, 10) : '');
    const rows = [['Item', 'Price', 'Situation', 'Added', 'Decide from', 'Outcome', 'Decided']];
    items.forEach(i => rows.push([i.name, i.price, i.situation, iso(i.added), iso(readyAt(i)),
      { waiting: 'Waiting', bought: 'Bought', skipped: 'Not bought' }[i.status], iso(i.decided)]));
    const blob = new Blob([rows.map(r => r.map(q).join(',')).join('\r\n')], { type: 'text/csv' });
    const a = el('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'impulse-waiting-list.csv';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  });

  // The list is kept for weeks, so clearing it takes a second tap.
  const reset = field('imp-reset');
  let armed = null;
  reset.addEventListener('click', () => {
    if (!armed) {
      reset.textContent = 'Tap again to clear';
      armed = setTimeout(() => { reset.textContent = 'Clear'; armed = null; }, 3000);
      return;
    }
    clearTimeout(armed);
    armed = null;
    reset.textContent = 'Clear';
    items = [];
    try { localStorage.removeItem(STORE); } catch (e) { /* unavailable */ }
    update();
  });

  field('imp-print').addEventListener('click', () => window.print());
  form.querySelectorAll('#imp-checks input').forEach(c => c.addEventListener('change', renderVerdict));
  [currency, threshold, wait].forEach(i => i.addEventListener('change', update));
  threshold.addEventListener('input', save);
  form.addEventListener('submit', (e) => e.preventDefault());

  const saved = load();
  if (saved.currency) currency.value = saved.currency;
  if (saved.threshold) threshold.value = saved.threshold;
  if (saved.wait) wait.value = saved.wait;
  items = Array.isArray(saved.items) ? saved.items : [];
  renderVerdict();
  update();
  // An item can become ready while the page is open.
  setInterval(renderList, 60000);
})();
