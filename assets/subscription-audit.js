// Subscription Audit. Runs entirely in the browser; nothing is sent anywhere.
(function () {
  const form = document.getElementById('sub-audit');
  if (!form) return;

  const rows = document.getElementById('sub-rows');
  const currency = document.getElementById('sub-currency');
  const out = {
    year: document.getElementById('sub-year'),
    month: document.getElementById('sub-month'),
    keep: document.getElementById('sub-keep'),
    summary: document.getElementById('sub-summary'),
  };
  const STORE = 'adhd-subscription-audit';
  const COMMON = ['Streaming video', 'Music', 'Cloud storage', 'Phone extras', 'Gym',
                  'News or magazine', 'Software or app', 'Delivery membership'];

  const load = () => {
    try { return JSON.parse(localStorage.getItem(STORE) || '{}'); } catch (e) { return {}; }
  };
  const save = (state) => {
    try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) { /* unavailable */ }
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

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };

  function addRow(name, cost, decision) {
    const row = el('div', 'sub-row');

    const nameInput = el('input', 'sub-name');
    nameInput.type = 'text';
    nameInput.placeholder = 'What is it?';
    nameInput.setAttribute('aria-label', 'Subscription name');
    nameInput.value = name || '';

    const costInput = el('input', 'sub-cost');
    costInput.type = 'text';
    costInput.inputMode = 'decimal';
    costInput.placeholder = '0';
    costInput.setAttribute('aria-label', 'Monthly cost');
    costInput.value = cost || '';

    const choice = el('div', 'sub-choice');
    [['keep', 'Keep'], ['cancel', 'Cancel'], ['unsure', 'Unsure']].forEach(([value, label]) => {
      const b = el('button', 'sub-pick', label);
      b.type = 'button';
      b.dataset.value = value;
      b.setAttribute('aria-pressed', String((decision || 'keep') === value));
      b.addEventListener('click', () => {
        choice.querySelectorAll('.sub-pick').forEach(o => o.setAttribute('aria-pressed', 'false'));
        b.setAttribute('aria-pressed', 'true');
        update();
      });
      choice.appendChild(b);
    });

    const remove = el('button', 'sub-remove', '×');
    remove.type = 'button';
    remove.setAttribute('aria-label', 'Remove this subscription');
    remove.addEventListener('click', () => { row.remove(); update(); });

    row.append(nameInput, costInput, choice, remove);
    rows.appendChild(row);
    return row;
  }

  const amount = (input) => {
    const n = parseFloat(String(input.value).replace(/[^0-9.]/g, ''));
    return Number.isFinite(n) && n > 0 ? n : 0;
  };

  const decisionOf = (row) => {
    const picked = row.querySelector('.sub-pick[aria-pressed="true"]');
    return picked ? picked.dataset.value : 'keep';
  };

  function update() {
    const state = { currency: currency.value, rows: [] };
    let cancel = 0, keep = 0, unsure = 0, cancelCount = 0, unsureCount = 0;

    rows.querySelectorAll('.sub-row').forEach(row => {
      const name = row.querySelector('.sub-name').value;
      const costInput = row.querySelector('.sub-cost');
      const cost = amount(costInput);
      const decision = decisionOf(row);
      state.rows.push({ name: name, cost: costInput.value, decision: decision });
      row.classList.toggle('is-cancel', decision === 'cancel');
      if (decision === 'cancel') { cancel += cost; cancelCount++; }
      else if (decision === 'unsure') { unsure += cost; unsureCount++; }
      else { keep += cost; }
    });

    out.year.textContent = money(cancel * 12, 0);
    out.month.textContent = money(cancel, 2);
    out.keep.textContent = money(keep, 2);

    out.summary.replaceChildren();
    if (!cancelCount && !unsureCount) {
      out.summary.appendChild(el('p', 'calc-empty',
        rows.children.length ? 'Mark anything you do not use as cancel.'
                             : 'Add a few subscriptions to see what this is worth.'));
    } else {
      const list = el('ul', 'sub-summary-list');
      if (cancelCount) {
        list.appendChild(el('li', null, cancelCount + (cancelCount === 1 ? ' to cancel, worth ' : ' to cancel, worth ') + money(cancel * 12, 0) + ' a year'));
      }
      if (unsureCount) {
        list.appendChild(el('li', null, unsureCount + ' unsure, holding ' + money(unsure * 12, 0) + ' a year'));
      }
      out.summary.appendChild(list);
      if (cancelCount) {
        out.summary.appendChild(el('p', 'sub-nudge', 'Cancel them now, in one sitting. A list of intentions is another doom pile.'));
      }
    }
    save(state);
  }

  const saved = load();
  if (saved.currency) currency.value = saved.currency;
  if (saved.rows && saved.rows.length) {
    saved.rows.forEach(r => addRow(r.name, r.cost, r.decision));
  } else {
    for (let i = 0; i < 3; i++) addRow();
  }

  document.getElementById('sub-add').addEventListener('click', () => {
    const row = addRow();
    row.querySelector('.sub-name').focus();
    update();
  });
  document.getElementById('sub-common').addEventListener('click', () => {
    COMMON.forEach(n => addRow(n));
    update();
  });
  document.getElementById('sub-reset').addEventListener('click', () => {
    rows.replaceChildren();
    for (let i = 0; i < 3; i++) addRow();
    try { localStorage.removeItem(STORE); } catch (e) { /* unavailable */ }
    update();
  });
  document.getElementById('sub-print').addEventListener('click', () => window.print());
  form.addEventListener('input', update);
  form.addEventListener('submit', (e) => e.preventDefault());
  update();
})();
