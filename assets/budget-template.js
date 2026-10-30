// ADHD Budget Template. Runs entirely in the browser; nothing is sent anywhere.
// Gives the same answers as the downloadable spreadsheet: weekly money is the
// three flexible categories divided by 52/12 weeks, and left over is income
// minus bills, flexible spending, the ADHD tax buffer and savings.
(function () {
  const form = document.getElementById('bud-form');
  if (!form) return;

  const bills = document.getElementById('bud-bills');
  const currency = document.getElementById('bud-currency');
  const field = (id) => document.getElementById(id);
  const inputs = {
    income: field('bud-income'), groceries: field('bud-groceries'), transport: field('bud-transport'),
    other: field('bud-other'), tax: field('bud-tax'), savings: field('bud-savings'),
  };
  const out = {
    week: field('bud-week'), left: field('bud-left'), billsTotal: field('bud-bills-total'),
    summary: field('bud-summary'),
  };
  const STORE = 'adhd-budget-template';
  const WEEKS_PER_MONTH = 52 / 12;
  const COMMON = ['Rent or mortgage', 'Electricity', 'Water', 'Phone', 'Internet', 'Insurance'];

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

  const amount = (input) => {
    const n = parseFloat(String(input.value).replace(/[^0-9.]/g, ''));
    return Number.isFinite(n) && n > 0 ? n : 0;
  };

  const dueDay = (input) => {
    const n = parseInt(String(input.value).replace(/[^0-9]/g, ''), 10);
    return n >= 1 && n <= 31 ? n : 0;
  };

  function addBill(name, cost, day, auto) {
    const row = el('div', 'bud-row');

    const nameInput = el('input', 'bud-name');
    nameInput.type = 'text';
    nameInput.placeholder = 'What is it?';
    nameInput.setAttribute('aria-label', 'Bill name');
    nameInput.value = name || '';

    const costInput = el('input', 'bud-cost');
    costInput.type = 'text';
    costInput.inputMode = 'decimal';
    costInput.placeholder = '0';
    costInput.setAttribute('aria-label', 'Amount per month');
    costInput.value = cost || '';

    const dayInput = el('input', 'bud-day');
    dayInput.type = 'text';
    dayInput.inputMode = 'numeric';
    dayInput.placeholder = 'Day';
    dayInput.setAttribute('aria-label', 'Day of the month it is due');
    dayInput.value = day || '';

    const choice = el('div', 'bud-auto');
    [['auto', 'Autopay'], ['manual', 'By hand']].forEach(([value, label]) => {
      const b = el('button', 'sub-pick', label);
      b.type = 'button';
      b.dataset.value = value;
      b.setAttribute('aria-pressed', String((auto || 'manual') === value));
      b.addEventListener('click', () => {
        choice.querySelectorAll('.sub-pick').forEach(o => o.setAttribute('aria-pressed', 'false'));
        b.setAttribute('aria-pressed', 'true');
        update();
      });
      choice.appendChild(b);
    });

    const remove = el('button', 'sub-remove', '×');
    remove.type = 'button';
    remove.setAttribute('aria-label', 'Remove this bill');
    remove.addEventListener('click', () => { row.remove(); update(); });

    row.append(nameInput, costInput, dayInput, choice, remove);
    bills.appendChild(row);
    return row;
  }

  const paidBy = (row) => {
    const picked = row.querySelector('.sub-pick[aria-pressed="true"]');
    return picked ? picked.dataset.value : 'manual';
  };

  // Days until a bill's due day comes round, clamped to short months.
  function daysUntil(day, today) {
    const pick = (y, m) => new Date(y, m, Math.min(day, new Date(y, m + 1, 0).getDate()));
    let next = pick(today.getFullYear(), today.getMonth());
    if (next < new Date(today.getFullYear(), today.getMonth(), today.getDate())) {
      next = pick(today.getFullYear(), today.getMonth() + 1);
    }
    return Math.round((next - new Date(today.getFullYear(), today.getMonth(), today.getDate())) / 86400000);
  }

  function readBills() {
    return Array.from(bills.querySelectorAll('.bud-row')).map(row => ({
      name: row.querySelector('.bud-name').value.trim(),
      costRaw: row.querySelector('.bud-cost').value,
      cost: amount(row.querySelector('.bud-cost')),
      dayRaw: row.querySelector('.bud-day').value,
      day: dueDay(row.querySelector('.bud-day')),
      auto: paidBy(row),
    }));
  }

  function totals() {
    const list = readBills();
    const billsTotal = list.reduce((s, b) => s + b.cost, 0);
    const flexible = amount(inputs.groceries) + amount(inputs.transport) + amount(inputs.other);
    const income = amount(inputs.income);
    const spending = billsTotal + flexible + amount(inputs.tax) + amount(inputs.savings);
    return { list, billsTotal, flexible, income, left: income - spending, weekly: flexible / WEEKS_PER_MONTH };
  }

  function update() {
    const t = totals();
    out.week.textContent = money(t.weekly, 0);
    out.left.textContent = money(t.left, 0);
    out.billsTotal.textContent = money(t.billsTotal, 0);

    out.summary.replaceChildren();
    const named = t.list.filter(b => b.name || b.cost);
    if (!t.income && !named.length) {
      out.summary.appendChild(el('p', 'calc-empty', 'Enter your income and a few bills to see your weekly number.'));
    } else {
      const list = el('ul', 'sub-summary-list');
      if (t.income && t.left < 0) {
        list.appendChild(el('li', null, 'The plan spends ' + money(-t.left, 0) + ' more than comes in. Trim a flexible figure first.'));
      }
      const manual = named.filter(b => b.auto === 'manual');
      if (manual.length) {
        list.appendChild(el('li', null, manual.length + (manual.length === 1 ? ' bill' : ' bills') + ' you pay by hand.'));
      }
      const today = new Date();
      const soon = named.filter(b => b.day).map(b => ({ b, d: daysUntil(b.day, today) }))
        .sort((x, y) => x.d - y.d).slice(0, 3);
      soon.forEach(({ b, d }) => {
        const when = d === 0 ? 'today' : d === 1 ? 'tomorrow' : 'in ' + d + ' days';
        list.appendChild(el('li', null, (b.name || 'A bill') + ' due ' + when + (b.auto === 'auto' ? ', on autopay' : '')));
      });
      out.summary.appendChild(list);
      if (manual.length) {
        out.summary.appendChild(el('p', 'sub-nudge', 'Each one you move to autopay is a due date you no longer have to remember.'));
      }
    }

    const state = { currency: currency.value, bills: t.list.map(b => ({ name: b.name, cost: b.costRaw, day: b.dayRaw, auto: b.auto })) };
    Object.keys(inputs).forEach(k => { state[k] = inputs[k].value; });
    save(state);
  }

  function csv() {
    const t = totals();
    const q = (v) => '"' + String(v).replace(/"/g, '""') + '"';
    const lines = [['Section', 'Item', 'Per month', 'Due day', 'Paid by']];
    lines.push(['Income', 'Take-home income', t.income, '', '']);
    t.list.filter(b => b.name || b.cost).forEach(b =>
      lines.push(['Bill', b.name, b.cost, b.day || '', b.auto === 'auto' ? 'Autopay' : 'Me']));
    lines.push(['Flexible', 'Groceries', amount(inputs.groceries), '', '']);
    lines.push(['Flexible', 'Getting around', amount(inputs.transport), '', '']);
    lines.push(['Flexible', 'Everything else', amount(inputs.other), '', '']);
    lines.push(['Set aside', 'ADHD tax buffer', amount(inputs.tax), '', '']);
    lines.push(['Set aside', 'Savings', amount(inputs.savings), '', '']);
    lines.push(['Result', 'Left over per month', t.left.toFixed(2), '', '']);
    lines.push(['Result', 'Weekly spending money', t.weekly.toFixed(2), '', '']);
    const blob = new Blob([lines.map(r => r.map(q).join(',')).join('\r\n')], { type: 'text/csv' });
    const a = el('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'adhd-budget.csv';
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  }

  const saved = load();
  if (saved.currency) currency.value = saved.currency;
  Object.keys(inputs).forEach(k => { if (saved[k]) inputs[k].value = saved[k]; });
  if (saved.bills && saved.bills.length) {
    saved.bills.forEach(b => addBill(b.name, b.cost, b.day, b.auto));
  } else {
    for (let i = 0; i < 3; i++) addBill();
  }

  field('bud-add').addEventListener('click', () => {
    const row = addBill();
    row.querySelector('.bud-name').focus();
    update();
  });
  field('bud-common').addEventListener('click', () => {
    COMMON.forEach(n => addBill(n));
    update();
  });
  field('bud-reset').addEventListener('click', () => {
    bills.replaceChildren();
    Object.values(inputs).forEach(i => { i.value = ''; });
    for (let i = 0; i < 3; i++) addBill();
    try { localStorage.removeItem(STORE); } catch (e) { /* unavailable */ }
    update();
  });
  field('bud-csv').addEventListener('click', csv);
  field('bud-print').addEventListener('click', () => window.print());
  form.addEventListener('input', update);
  form.addEventListener('submit', (e) => e.preventDefault());
  update();
})();
