// Register form: live inline validation (U5) — CSP-safe external module.
const form = document.getElementById('register-form');
if (form) {
  const rules = {
    length: v => v.length >= 8,
    letter: v => /[A-Za-z]/.test(v),
    digit: v => /\d/.test(v),
  };
  const emailOk = v => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v);
  const setError = (input, errEl, bad) => {
    if (!input || !errEl) return;
    errEl.classList.toggle('show', bad);
    input.setAttribute('aria-invalid', bad ? 'true' : 'false');
    input.classList.toggle('is-invalid', bad);
  };

  const pw = form.querySelector('#password');
  pw?.addEventListener('input', () => {
    form.querySelectorAll('.pw-rules li').forEach(li => {
      const met = rules[li.dataset.rule](pw.value);
      li.classList.toggle('met', met);
      const icon = li.querySelector('i');
      if (icon) icon.className = met ? 'bi bi-check-circle-fill' : 'bi bi-circle';
    });
  });

  // inline validation on blur
  form.querySelector('#name')?.addEventListener('blur', e =>
    setError(e.target, document.getElementById('name-error'), e.target.value.trim().length < 2));
  form.querySelector('#email')?.addEventListener('blur', e =>
    setError(e.target, document.getElementById('email-error'), e.target.value !== '' && !emailOk(e.target.value)));
  pw?.addEventListener('blur', () => {
    const v = pw.value;
    setError(pw, document.getElementById('pw-error'),
      v !== '' && !(rules.length(v) && rules.letter(v) && rules.digit(v)));
  });
}
