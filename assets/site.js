// Email sign-up for the free toolkit. Posts to /api/subscribe (worker.js), which adds the address
// to MailerLite; MailerLite then sends the toolkit email. On the toolkit page a successful sign-up
// also shows the download links that are marked data-after-signup.
document.querySelectorAll('form.signup-form').forEach((form) => {
  const button = form.querySelector('button');
  const input = form.querySelector('input[type="email"]');
  const label = button.textContent;
  let status = form.parentNode.querySelector('.form-status');
  if (!status) {
    status = document.createElement('p');
    status.className = 'form-status';
    form.insertAdjacentElement('afterend', status);
  }
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');

  const say = (msg, ok) => {
    status.textContent = msg;
    status.classList.toggle('is-error', !ok);
  };

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = input.value.trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      say('Please enter a valid email address.', false);
      input.focus();
      return;
    }
    button.disabled = true;
    button.textContent = 'Sending…';
    say('', true);
    try {
      const res = await fetch('/api/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        form.reset();
        say('Thank you. The toolkit email is on its way; check your inbox, and your spam folder if it does not arrive.', true);
        document.querySelectorAll('[data-after-signup]').forEach((el) => {
          el.hidden = false;
          if (!el.dataset.shown) { el.dataset.shown = '1'; el.focus({ preventScroll: false }); }
        });
      } else {
        say(data.error || 'Something went wrong. Please try again.', false);
      }
    } catch (err) {
      say('The connection failed. Please try again.', false);
    } finally {
      button.disabled = false;
      button.textContent = label;
    }
  });
});
