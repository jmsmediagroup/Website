// ADHD Tax Calculator. Runs entirely in the browser; nothing is sent anywhere.
// Category data is embedded in the page as JSON by build.py.
(function () {
  const form = document.getElementById('adhd-tax-calc');
  const dataEl = document.getElementById('calc-data');
  if (!form || !dataEl) return;

  const categories = JSON.parse(dataEl.textContent);
  const currency = document.getElementById('calc-currency');
  const out = {
    month: document.getElementById('calc-month'),
    year: document.getElementById('calc-year'),
    decade: document.getElementById('calc-decade'),
    top: document.getElementById('calc-top'),
  };
  const STORE = 'adhd-tax-calculator';

  // Browser storage can be blocked or throw; the calculator works without it.
  const load = () => {
    try { return JSON.parse(localStorage.getItem(STORE) || '{}'); } catch (e) { return {}; }
  };
  const save = (state) => {
    try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) { /* not available */ }
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

  const amount = (input) => {
    const n = parseFloat(String(input.value).replace(/[^0-9.]/g, ''));
    return Number.isFinite(n) && n > 0 ? n : 0;
  };

  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  function update() {
    const state = { currency: currency.value, values: {} };
    const totals = categories.map((cat) => {
      let sum = 0;
      form.querySelectorAll('[data-cat="' + cat.id + '"]').forEach((input) => {
        sum += amount(input);
        if (input.value !== '') state.values[input.name] = input.value;
      });
      const sub = form.querySelector('[data-subtotal="' + cat.id + '"]');
      if (sub) sub.textContent = money(sum, 2);
      return { cat: cat, sum: sum };
    });

    const month = totals.reduce((acc, t) => acc + t.sum, 0);
    out.month.textContent = money(month, 2);
    out.year.textContent = money(month * 12, 0);
    out.decade.textContent = money(month * 120, 0);

    out.top.replaceChildren();
    const ranked = totals.filter((t) => t.sum > 0).sort((a, b) => b.sum - a.sum).slice(0, 3);
    if (!ranked.length) {
      out.top.appendChild(el('p', 'calc-empty', 'Enter some amounts to see where most of it goes.'));
    } else {
      out.top.appendChild(el('div', 'calc-label', 'Where most of it goes'));
      const list = el('ol', 'calc-top-list');
      ranked.forEach((t) => {
        const li = el('li');
        const head = el('div', 'calc-top-head');
        head.appendChild(el('span', 'calc-top-name', t.cat.name));
        head.appendChild(el('span', 'calc-top-sum', money(t.sum, 0) + '/mo'));
        li.appendChild(head);
        li.appendChild(el('p', 'calc-top-tip', t.cat.tip));
        const link = el('a', 'calc-top-link', 'Read more');
        link.href = t.cat.link;
        li.appendChild(link);
        list.appendChild(li);
      });
      out.top.appendChild(list);
    }
    save(state);
  }

  const saved = load();
  if (saved.currency) currency.value = saved.currency;
  Object.entries(saved.values || {}).forEach(([name, value]) => {
    const input = form.elements[name];
    if (input) input.value = value;
  });

  form.addEventListener('input', update);
  form.addEventListener('submit', (e) => e.preventDefault());
  document.getElementById('calc-reset').addEventListener('click', () => {
    form.reset();
    try { localStorage.removeItem(STORE); } catch (e) { /* not available */ }
    update();
  });
  document.getElementById('calc-print').addEventListener('click', () => window.print());
  update();
})();
