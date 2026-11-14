// Shared fetch wrapper for the JSON REST API (Section 11.2).
const API = '/api/v1';

// Read a CSRF cookie. kind: 'access' | 'refresh'.
function csrfToken(kind = 'access') {
  const m = document.cookie.match(new RegExp('(?:^|;\\s*)csrf_' + kind + '_token=([^;]+)'));
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

export async function apiFetch(path, { method = 'GET', body = null, formData = null,
                                       csrfKind = 'access', retry = true } = {}) {
  method = method.toUpperCase();
  const headers = {};
  // Attach the CSRF double-submit header on every state-changing request,
  // including body-less POSTs such as logout (this was the logout bug).
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    headers['X-CSRF-TOKEN'] = csrfToken(csrfKind);
  }
  if (formData) {
    // Content-Type is set by the browser for FormData
  } else if (body !== null) {
    headers['Content-Type'] = 'application/json';
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
  // Access token expired: transparently refresh and retry once.
  if (err.code === 'TOKEN_EXPIRED' && retry) {
    const refreshed = await refreshSession();
    if (refreshed) return apiFetch(path, { method, body, formData, csrfKind, retry: false });
  }
  throw new ApiError(err.code, err.message, resp.status, err.details);
}

// Silent refresh using the refresh-token CSRF cookie.
export async function refreshSession() {
  const token = csrfToken('refresh');
  if (!token) return false;
  const r = await fetch(API + '/auth/refresh', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-CSRF-TOKEN': token },
  });
  return r.ok;
}

export function showToast(message, kind = 'danger') {
  const area = document.getElementById('toast-area');
  if (!area) return;
  const icon = kind === 'success' ? 'check-circle' : 'exclamation-triangle';
  const el = document.createElement('div');
  el.className = `toast align-items-center text-bg-${kind} border-0 show mb-2`;
  el.setAttribute('role', 'alert');
  el.innerHTML = `<div class="d-flex"><div class="toast-body"><i class="bi bi-${icon} me-2"></i><span class="msg"></span></div>
    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
  el.querySelector('.msg').textContent = message;
  area.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

export function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso.replace('Z', '+00:00')).toLocaleString();
}
