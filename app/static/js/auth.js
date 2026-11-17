// auth.js: profile page (update profile / change password with OTP, Part C1.5).
import { apiFetch, showToast } from './api.js';

document.addEventListener('DOMContentLoaded', () => {
  const profileForm = document.getElementById('profile-form');
  if (profileForm) profileForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = {};
    new FormData(profileForm).forEach((v, k) => { body[k] = v; });
    try {
      const needsOtp = body.phone !== undefined && body.phone !== '';
      if (needsOtp) {
        // C1.5: phone changes need a fresh SENSITIVE_ACTION OTP
        try {
          await apiFetch('/auth/me', { method: 'PATCH', body });
        } catch (err) {
          if (err.details && err.details.otp_required) {
            const ch = await apiFetch('/auth/sensitive-otp', { method: 'POST' });
            const code = window.prompt(`Enter the code sent to ${ch.masked_destination || 'your email'}:`);
            if (!code) return;
            await apiFetch('/auth/me', { method: 'PATCH',
              body: { ...body, otp_challenge_id: ch.challenge_id, otp: code } });
          } else { throw err; }
        }
      } else {
        await apiFetch('/auth/me', { method: 'PATCH', body });
      }
      showToast('Profile updated', 'success');
    } catch (err) {
      showToast(err.message + (err.details ? ' — ' + Object.values(err.details).flat().join('; ') : ''));
    }
  });

  const pwForm = document.getElementById('password-form');
  if (pwForm) pwForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = {};
    new FormData(pwForm).forEach((v, k) => { body[k] = v; });
    try {
      // C1.5: request an OTP first, then submit with challenge + code
      const ch = await apiFetch('/auth/sensitive-otp', { method: 'POST' });
      const code = window.prompt(`Enter the code sent to ${ch.masked_destination || 'your email'}:`);
      if (!code) return;
      await apiFetch('/auth/change-password', {
        method: 'POST',
        body: { ...body, otp_challenge_id: ch.challenge_id, otp: code },
      });
      showToast('Password changed', 'success');
      pwForm.reset();
    } catch (err) {
      showToast(err.message + (err.details ? ' — ' + Object.values(err.details).flat().join('; ') : ''));
    }
  });

  // Issue 6: self-service account deletion (sensitive-action OTP protected).
  const delBtn = document.getElementById('delete-account-btn');
  if (delBtn) delBtn.addEventListener('click', async () => {
    if (!window.confirm('Delete your account? This anonymises your personal data and signs you out everywhere. This cannot be undone.')) return;
    try {
      const ch = await apiFetch('/auth/sensitive-otp', { method: 'POST' });
      const code = window.prompt(`Enter the code sent to ${ch.masked_destination || 'your email'} to confirm deletion:`);
      if (!code) return;
      await apiFetch('/auth/me', { method: 'DELETE', body: { otp_challenge_id: ch.challenge_id, otp: code } });
      showToast('Account deleted. Your personal data has been anonymised.', 'success');
      setTimeout(() => { window.location.href = '/'; }, 1500);
    } catch (err) {
      showToast(err.message + (err.details ? ' — ' + Object.values(err.details).flat().join('; ') : ''));
    }
  });
});
