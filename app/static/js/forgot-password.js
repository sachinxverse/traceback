// Forgot-password flow (Part C1.5): email -> OTP -> new password.
import { apiFetch, showToast } from './api.js';

const form = document.getElementById('forgot-form');
if (form) {
  const otpStep = document.getElementById('forgot-otp-step');
  const errorEl = document.getElementById('forgot-error');
  const otpError = document.getElementById('fp-otp-error');
  const digits = Array.from(document.querySelectorAll('.otp-digit'));
  let challenge = null;

  const showError = (el, msg) => { el.textContent = msg; el.classList.add('show'); };
  const clearError = (el) => { el.textContent = ''; el.classList.remove('show'); };

  digits.forEach((digit, i) => {
    digit.addEventListener('input', () => {
      digit.value = digit.value.replace(/\D/g, '').slice(0, 1);
      clearError(otpError);
      if (digit.value && i < digits.length - 1) digits[i + 1].focus();
    });
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearError(errorEl);
    const email = document.getElementById('email').value.trim();
    if (!email) { showError(errorEl, 'Enter your account email.'); return; }
    const btn = form.querySelector('button[type=submit]');
    btn.disabled = true;
    try {
      const data = await apiFetch('/auth/forgot-password', { method: 'POST', body: { email } });
      challenge = data;
      form.classList.add('d-none');
      otpStep.classList.remove('d-none');
      document.getElementById('fp-destination').textContent = data.masked_destination || 'your email';
      digits.forEach(d => d.value = '');
      digits[0].focus();
      showToast('If that email has an account, a code is on its way', 'success');
    } catch (err) {
      showError(errorEl, err.message || 'Could not send a code right now.');
    } finally {
      btn.disabled = false;
    }
  });

  document.getElementById('fp-back').addEventListener('click', () => {
    challenge = null;
    otpStep.classList.add('d-none');
    form.classList.remove('d-none');
  });

  document.getElementById('fp-submit').addEventListener('click', async () => {
    clearError(otpError);
    const code = digits.map(d => d.value).join('');
    if (code.length !== digits.length) { showError(otpError, 'Enter all six digits.'); return; }
    const pw = document.getElementById('new_password').value;
    if (pw.length < 8 || !/[A-Za-z]/.test(pw) || !/\d/.test(pw)) {
      document.getElementById('fp-pw-error').classList.add('show');
      document.getElementById('new_password').classList.add('is-invalid');
      return;
    }
    document.getElementById('fp-pw-error').classList.remove('show');
    const btn = document.getElementById('fp-submit');
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    try {
      await apiFetch('/auth/forgot-password/verify-otp', {
        method: 'POST',
        body: { challenge_id: challenge.challenge_id, otp: code, new_password: pw },
      });
      showToast('Password updated — you can sign in now', 'success');
      setTimeout(() => { window.location.href = '/login'; }, 800);
    } catch (err) {
      showError(otpError, err.message || 'Incorrect code.');
      digits.forEach(d => d.value = '');
      digits[0].focus();
    } finally {
      btn.disabled = false;
      btn.setAttribute('aria-busy', 'false');
    }
  });
}
