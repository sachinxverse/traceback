// Registration step 2: email verification OTP (Part C1.4).
import { apiFetch, showToast } from './api.js';

const form = document.getElementById('register-form');
const otpStep = document.getElementById('register-otp-step');
if (form && otpStep) {
  const digits = Array.from(otpStep.querySelectorAll('.otp-digit'));
  const errorEl = document.getElementById('reg-otp-error');
  let challenge = null;
  let countdownTimer = null;
  let resendTimer = null;

  const clearError = () => { errorEl.textContent = ''; errorEl.classList.remove('show'); };
  const showError = (msg) => { errorEl.textContent = msg; errorEl.classList.add('show'); };

  digits.forEach((digit, i) => {
    digit.addEventListener('input', () => {
      digit.value = digit.value.replace(/\D/g, '').slice(0, 1);
      clearError();
      if (digit.value && i < digits.length - 1) digits[i + 1].focus();
    });
    digit.addEventListener('keydown', (e) => { if (e.key === 'Enter') verify(); });
    digit.addEventListener('paste', (e) => {
      const text = (e.clipboardData.getData('text') || '').replace(/\D/g, '').slice(0, 6);
      if (!text) return;
      e.preventDefault();
      for (let k = 0; k < text.length; k++) digits[k].value = text[k];
    });
  });

  function startCountdown(seconds) {
    clearInterval(countdownTimer);
    let left = seconds;
    const el = document.getElementById('reg-otp-countdown');
    const render = () => {
      const m = Math.floor(left / 60), s = left % 60;
      el.textContent = `${m}:${String(s).padStart(2, '0')}`;
    };
    render();
    countdownTimer = setInterval(() => {
      left -= 1;
      if (left <= 0) { clearInterval(countdownTimer); el.textContent = '0:00'; showError('The code has expired. Resend a new one.'); return; }
      render();
    }, 1000);
  }

  function startResendCooldown(seconds) {
    clearInterval(resendTimer);
    let left = seconds;
    const btn = document.getElementById('reg-otp-resend');
    btn.disabled = true;
    btn.textContent = `Resend code (${left}s)`;
    resendTimer = setInterval(() => {
      left -= 1;
      if (left <= 0) { clearInterval(resendTimer); btn.disabled = false; btn.textContent = 'Resend code'; return; }
      btn.textContent = `Resend code (${left}s)`;
    }, 1000);
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearError();
    const btn = form.querySelector('button[type=submit]');
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    btn.querySelector('.btn-label')?.classList.add('d-none');
    btn.querySelector('.btn-spin')?.classList.remove('d-none');
    try {
      const fd = new FormData(form);
      const body = {};
      fd.forEach((v, k) => { body[k] = v; });
      challenge = await apiFetch('/auth/register', { method: 'POST', body });
      form.classList.add('d-none');
      otpStep.classList.remove('d-none');
      document.getElementById('reg-otp-destination').textContent =
        challenge.masked_destination || 'your email';
      startCountdown(challenge.expires_in || 300);
      startResendCooldown(challenge.resend_after || 30);
      digits.forEach(d => d.value = '');
      digits[0].focus();
    } catch (err) {
      showToast(err.message + (err.details ? ' — ' + Object.values(err.details).flat().join('; ') : ''));
    } finally {
      btn.disabled = false;
      btn.setAttribute('aria-busy', 'false');
      btn.querySelector('.btn-label')?.classList.remove('d-none');
      btn.querySelector('.btn-spin')?.classList.add('d-none');
    }
  });

  async function verify() {
    clearError();
    const c = digits.map(d => d.value).join('');
    if (c.length !== digits.length) { showError('Enter all six digits.'); return; }
    const btn = document.getElementById('reg-otp-verify');
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    try {
      await apiFetch('/auth/register/verify-otp', {
        method: 'POST',
        body: { challenge_id: challenge.challenge_id, otp: c },
      });
      showToast('Account verified — welcome!', 'success');
      setTimeout(() => { window.location.href = '/dashboard'; }, 500);
    } catch (err) {
      showError(err.message || 'Incorrect code.');
      digits.forEach(d => d.value = '');
      digits[0].focus();
    } finally {
      btn.disabled = false;
      btn.setAttribute('aria-busy', 'false');
    }
  }

  document.getElementById('reg-otp-verify').addEventListener('click', verify);
  document.getElementById('reg-otp-resend').addEventListener('click', async () => {
    clearError();
    const btn = document.getElementById('reg-otp-resend');
    btn.disabled = true;
    try {
      const data = await apiFetch('/auth/user/resend-otp', {
        method: 'POST', body: { challenge_id: challenge.challenge_id },
      });
      challenge = { ...challenge, ...data };
      digits.forEach(d => d.value = '');
      digits[0].focus();
      startCountdown(data.expires_in || 300);
      startResendCooldown(data.resend_after || 30);
      showToast('New code sent', 'success');
    } catch (err) {
      showError(err.message || 'Could not resend right now.');
      startResendCooldown(30);
    }
  });
}
