// Two-step portal login (Part B + C): credentials -> 6-digit OTP.
// The portal comes from the script tag's data-portal attribute.
import { apiFetch, showToast } from './api.js';

const PORTAL = (document.querySelector('script[data-portal]')?.dataset.portal) || 'user';
const form = document.getElementById('login-form');
const otpStep = document.getElementById('otp-step');
const errorEl = document.getElementById('login-error');
const otpError = document.getElementById('otp-error');

let challenge = null;      // {challenge_id, masked_destination, expires_in, resend_after}
let countdownTimer = null;
let resendTimer = null;

const digits = Array.from(document.querySelectorAll('.otp-digit'));

function showError(el, message) {
  el.textContent = message;
  el.classList.add('show');
}

function clearError(el) {
  el.textContent = '';
  el.classList.remove('show');
}

function setBusy(formEl, busy) {
  formEl.querySelectorAll('button[type=submit], #otp-verify').forEach(b => {
    b.disabled = busy;
    b.setAttribute('aria-busy', String(busy));
    const label = b.querySelector('.btn-label');
    const spin = b.querySelector('.btn-spin');
    if (label && spin) { label.classList.toggle('d-none', busy); spin.classList.toggle('d-none', !busy); }
  });
}

// ------------------------------------------------------------ digit boxes
function code() { return digits.map(d => d.value).join(''); }

digits.forEach((digit, i) => {
  digit.addEventListener('input', () => {
    digit.value = digit.value.replace(/\D/g, '').slice(0, 1);
    clearError(otpError);
    if (digit.value && i < digits.length - 1) digits[i + 1].focus();
  });
  digit.addEventListener('keydown', (e) => {
    if (e.key === 'Backspace' && !digit.value && i > 0) digits[i - 1].focus();
    if (e.key === 'Enter') verifyOtp();
  });
  digit.addEventListener('paste', (e) => {
    const text = (e.clipboardData.getData('text') || '').replace(/\D/g, '').slice(0, 6);
    if (!text) return;
    e.preventDefault();
    for (let k = 0; k < text.length; k++) digits[k].value = text[k];
    if (text.length === digits.length) digits[digits.length - 1].focus();
  });
});

// ------------------------------------------------------------ step 1
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  clearError(errorEl);
  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;
  if (!email || !password) { showError(errorEl, 'Enter your email and password.'); return; }
  setBusy(form, true);
  try {
    const data = await apiFetch(`/auth/${PORTAL}/login`, { method: 'POST', body: { email, password } });
    challenge = data;
    if (data.purpose === 'REGISTER') {
      // unverified account: finish e-mail verification then log in
      challenge._register = true;
    }
    showOtpStep(data);
  } catch (err) {
    showError(errorEl, err.message || 'Invalid credentials');
  } finally {
    setBusy(form, false);
  }
});

// ------------------------------------------------------------ step 2
function showOtpStep(data) {
  form.classList.add('d-none');
  otpStep.classList.remove('d-none');
  document.getElementById('otp-destination').textContent =
    data.masked_destination || 'your email';
  startCountdown(data.expires_in || 300);
  startResendCooldown(data.resend_after || 30);
  digits.forEach(d => d.value = '');
  digits[0].focus();
  otpStep.scrollIntoView({ block: 'center' });
}

function startCountdown(seconds) {
  clearInterval(countdownTimer);
  let left = seconds;
  const el = document.getElementById('otp-countdown');
  const render = () => {
    const m = Math.floor(left / 60), s = left % 60;
    el.textContent = `${m}:${String(s).padStart(2, '0')}`;
  };
  render();
  countdownTimer = setInterval(() => {
    left -= 1;
    if (left <= 0) {
      clearInterval(countdownTimer);
      el.textContent = '0:00';
      showError(otpError, 'The code has expired. Go back and request a new one.');
      return;
    }
    render();
  }, 1000);
}

function startResendCooldown(seconds) {
  clearInterval(resendTimer);
  let left = seconds;
  const btn = document.getElementById('otp-resend');
  btn.disabled = true;
  btn.textContent = `Resend code (${left}s)`;
  resendTimer = setInterval(() => {
    left -= 1;
    if (left <= 0) { clearInterval(resendTimer); btn.disabled = false; btn.textContent = 'Resend code'; return; }
    btn.textContent = `Resend code (${left}s)`;
  }, 1000);
}

async function verifyOtp() {
  clearError(otpError);
  const c = code();
  if (c.length !== digits.length) { showError(otpError, 'Enter all six digits.'); return; }
  const verifyBtn = document.getElementById('otp-verify');
  verifyBtn.disabled = true;
  verifyBtn.setAttribute('aria-busy', 'true');
  try {
    const path = challenge._register ? '/auth/register/verify-otp' : `/auth/${PORTAL}/verify-otp`;
    const user = await apiFetch(path, { method: 'POST', body: { challenge_id: challenge.challenge_id, otp: c } });
    showToast('Signed in', 'success');
    const next = new URLSearchParams(location.search).get('next');
    const home = PORTAL === 'admin' ? '/admin' : PORTAL === 'staff' ? '/staff' : '/dashboard';
    // only allow same-site relative redirects
    const target = next && next.startsWith('/') && !next.startsWith('//') ? next : home;
    setTimeout(() => { window.location.href = target; }, 500);
  } catch (err) {
    showError(otpError, err.message || 'Incorrect code.');
    digits.forEach(d => d.value = '');
    digits[0].focus();
  } finally {
    verifyBtn.disabled = false;
    verifyBtn.setAttribute('aria-busy', 'false');
  }
}

document.getElementById('otp-verify').addEventListener('click', verifyOtp);

document.getElementById('otp-back').addEventListener('click', () => {
  challenge = null;
  clearInterval(countdownTimer); clearInterval(resendTimer);
  otpStep.classList.add('d-none');
  form.classList.remove('d-none');
  document.getElementById('email').focus();
});

document.getElementById('otp-resend').addEventListener('click', async () => {
  clearError(otpError);
  const btn = document.getElementById('otp-resend');
  btn.disabled = true;
  try {
    const path = challenge._register
      ? null
      : `/auth/${PORTAL}/resend-otp`;
    let data;
    if (challenge._register) {
      // registration OTP: request a fresh challenge via a new register call is
      // not possible (409) — the backend resend accepts register challenges too
      data = await apiFetch('/auth/user/resend-otp', { method: 'POST', body: { challenge_id: challenge.challenge_id } });
    } else {
      data = await apiFetch(path, { method: 'POST', body: { challenge_id: challenge.challenge_id } });
    }
    challenge = { ...challenge, ...data };
    digits.forEach(d => d.value = '');
    digits[0].focus();
    startCountdown(data.expires_in || 300);
    startResendCooldown(data.resend_after || 30);
    showToast('New code sent', 'success');
  } catch (err) {
    showError(otpError, err.message || 'Could not resend right now.');
    startResendCooldown(30);
  }
});

// password visibility toggle (same as other pages)
document.querySelectorAll('[data-toggle-pw]').forEach(btn => {
  btn.addEventListener('click', () => {
    const input = document.getElementById('password');
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    btn.setAttribute('aria-pressed', String(show));
    btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    btn.querySelector('i').className = show ? 'bi bi-eye-slash' : 'bi bi-eye';
  });
});
