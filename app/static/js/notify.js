// Notification bell polling (every 30 s) and auth pages wiring.
import { apiFetch, showToast } from './api.js';

const BADGE_URL = '/api/v1/notifications/unread-count';
const LIST_URL = '/api/v1/notifications?per_page=5&unread=true';

async function refreshBadge() {
  const badge = document.getElementById('unread-badge');
  if (!badge) return;
  try {
    const { count } = await apiFetch('/notifications/unread-count');
    if (count > 0) {
      badge.textContent = count > 99 ? '99+' : count;
      badge.classList.remove('d-none');
    } else {
      badge.classList.add('d-none');
    }
  } catch (e) { /* anonymous or logged out */ }
}

async function showDropdown() {
  const dd = document.getElementById('notif-dropdown');
  if (!dd) return;
  dd.classList.add('show');
  dd.innerHTML = '<div class="notif-item text-muted">Loading…</div>';
  try {
    const items = await apiFetch('/notifications?per_page=5');
    dd.innerHTML = items.length
      ? items.map(n => `<div class="notif-item ${n.is_read ? '' : 'unread'}">
          <a href="${n.link || '/notifications'}">${escapeHtml(n.message)}</a>
          <div class="text-muted" style="font-size:.75rem">${fmtWhen(n.created_at)}</div></div>`).join('')
      : '<div class="notif-item text-muted">No notifications yet.</div>';
    dd.insertAdjacentHTML('beforeend', '<a class="notif-item d-block text-center" href="/notifications">View all</a>');
  } catch (e) {
    dd.innerHTML = '<div class="notif-item text-muted">Sign in to see notifications.</div>';
  }
}

function fmtWhen(iso) {
  return iso ? iso.replace('T', ' ').replace('Z', ' UTC') : '';
}
// Attribute-safe escape: &, <, >, double and single quotes (review C4).
function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

document.addEventListener('DOMContentLoaded', () => {
  // remember current user id for chat bubble alignment
  apiFetch('/auth/me').then(u => { window.__myUserId = u.id; }).catch(() => {});
  refreshBadge();
  setInterval(refreshBadge, 30000);
  const bell = document.getElementById('notif-bell');
  if (bell) {
    bell.addEventListener('click', (e) => {
      e.preventDefault();
      const dd = document.getElementById('notif-dropdown');
      if (dd.classList.contains('show')) dd.classList.remove('show');
      else showDropdown();
    });
    document.addEventListener('click', (e) => {
      if (!bell.contains(e.target)) {
        const dd = document.getElementById('notif-dropdown');
        if (dd) dd.classList.remove('show');
      }
    });
  }

  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) logoutBtn.addEventListener('click', async () => {
    // Try the access-token path first; if the access token is expired or
    // already revoked, retry with the refresh-token CSRF header so the
    // server revokes the refresh token too. Cookies are then cleared.
    try {
      await apiFetch('/auth/logout', { method: 'POST' });
    } catch (e) {
      try { await apiFetch('/auth/logout', { method: 'POST', csrfKind: 'refresh' }); } catch (e2) { /* both failed */ }
    }
    window.location.href = '/';
  });

  // login / register / profile forms
  wireAuthForm('login-form', '/auth/login', data => {
    const p = new URLSearchParams(location.search);
    window.location.href = p.get('next') || '/dashboard';
  });
  wireAuthForm('register-form', '/auth/register', () => { window.location.href = '/dashboard'; });
});

function wireAuthForm(formId, endpoint, onSuccess) {
  const form = document.getElementById(formId);
  if (!form) return;
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    setBusy(form, true);
    try {
      const fd = new FormData(form);
      const body = {};
      fd.forEach((v, k) => { body[k] = v; });
      await apiFetch(endpoint, { method: endpoint.endsWith('login') ? 'POST' : 'POST', body });
      onSuccess(body);
    } catch (err) {
      showToast(err.message + detailText(err));
    } finally {
      setBusy(form, false);
    }
  });
}

function detailText(err) {
  if (!err.details) return '';
  return ' — ' + Object.values(err.details).flat().join('; ');
}

function setBusy(form, busy) {
  form.querySelectorAll('button[type="submit"]').forEach(b => { b.disabled = busy; });
}
