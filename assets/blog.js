// Signup handling for blog pages, matching the home page behaviour.
document.querySelectorAll('form.signup-form').forEach(form => {
  const button = form.querySelector('button');
  const input = form.querySelector('input[type="email"]');
  const defaultLabel = button.textContent;

  let status = form.parentNode.querySelector('.form-status');
  if (!status) {
    status = document.createElement('p');
    status.className = 'form-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    form.insertAdjacentElement('afterend', status);
  }

  const setStatus = (msg, ok) => {
    status.textContent = msg;
    status.classList.toggle('is-error', !ok);
  };

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = input.value.trim();
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setStatus('Please enter a valid email address.', false);
      return;
    }

    button.disabled = true;
    button.textContent = 'Sending…';
    setStatus('', true);

    try {
      const res = await fetch('/.netlify/functions/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        form.reset();
        setStatus('Done! Check your inbox — your Survival Kit is on the way.', true);
      } else {
        setStatus(data.error || 'Something went wrong. Please try again.', false);
      }
    } catch (err) {
      setStatus('Network error. Please try again.', false);
    } finally {
      button.disabled = false;
      button.textContent = defaultLabel;
    }
  });
});
