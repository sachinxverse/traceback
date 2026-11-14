// auth.js: shared helpers for profile page (change password / update profile).
import { apiFetch, showToast } from './api.js';

document.addEventListener('DOMContentLoaded', () => {
  const profileForm = document.getElementById('profile-form');
  if (profileForm) profileForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = {};
    new FormData(profileForm).forEach((v, k) => body[k] = v);
    try {
      await apiFetch('/auth/me', { method: 'PATCH', body });
      showToast('Profile updated', 'success');
    } catch (err) { showToast(err.message); }
  });

  const pwForm = document.getElementById('password-form');
  if (pwForm) pwForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = {};
    new FormData(pwForm).forEach((v, k) => body[k] = v);
    try {
      await apiFetch('/auth/change-password', { method: 'POST', body });
      showToast('Password changed', 'success');
      pwForm.reset();
    } catch (err) { showToast(err.message); }
  });
});
