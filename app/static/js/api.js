// Shared fetch wrapper for the JSON REST API (Section 11.2).
const API = '/api/v1';

function csrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)csrf_access_token=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : '';
}

class ApiError extends Error {
  constructor(code, message, status, details) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export async function apiFetch(path, { method = 'GET', body = null, formData = null, retry = true } = {}) {
  const headers = {};
  if (formData) {
    headers['X-CSRF-TOKEN'] = csrfToken();
  } else if (body !== null) {
    headers['Content-Type'] = 'application/json';
    headers['X-CSRF-TOKEN'] = csrfToken();
  }
  const resp = await fetch(API + path, {
    method,
    credentials: 'same-origin',
    headers,
    body: formData ? formData : body !== null ? JSON.stringify(body) : undefined,
  });
  let payload = {};
  try { payload = await resp.json(); } catch (e) { /* empty body */ }
  if (resp.ok) return payload.data !== undefined ? payload.data : payload;

  const err = payload.error || { code: 'ERROR', message: 'Request failed' };
  if (err.code === 'TOKEN_EXPIRED' && retry) {
    const r = await fetch(API + '/auth/refresh', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRF-TOKEN': document.cookie.match(/(?:^|;\s*)csrf_refresh_token=([^;]+)/) ? decodeURIComponent(RegExp.$1) : '' },
    });
    if (r.ok) return apiFetch(path, { method, body, formData, retry: false });
  }
  throw new ApiError(err.code, err.message, resp.status, err.details);
}

export function showToast(message, kind = 'danger') {
  const area = document.getElementById('toast-area');
  if (!area) return;
  const el = document.createElement('div');
  el.className = `toast align-items-center text-bg-${kind} border-0 show mb-2`;
  el.setAttribute('role', 'alert');
  el.innerHTML = `<div class="d-flex"><div class="toast-body"></div>
    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
  el.querySelector('.toast-body').textContent = message;
  area.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

export function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso.replace('Z', '+00:00')).toLocaleString();
}
