// Claim submission on match page; claim actions on claim page; messaging.
import { apiFetch, showToast, fmtDate } from './api.js';

document.addEventListener('DOMContentLoaded', () => {
  let matchId = window.location.pathname.startsWith('/matches/')
    ? parseInt(location.pathname.split('/')[2], 10) : null;
  const msgPanel = document.getElementById('messaging-panel');
  if (!matchId && msgPanel) {
    const attr = msgPanel.dataset.matchId || msgPanel.getAttribute('data-match-id');
    if (attr) matchId = parseInt(attr, 10);
  }
  const claimId = window.location.pathname.startsWith('/claims/')
    ? parseInt(location.pathname.split('/')[2], 10) : null;

  const claimForm = document.getElementById('claim-form');
  if (claimForm && matchId) {
    claimForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData();
      fd.append('claim_details', claimForm.querySelector('[name="claim_details"]').value);
      const files = document.getElementById('proof_images').files;
      for (const f of Array.from(files).slice(0, 2)) fd.append('proof_images', f);
      try {
        await apiFetch(`/matches/${matchId}/claims`, { method: 'POST', formData: fd });
        showToast('Claim submitted — awaiting review', 'success');
        location.reload();
      } catch (err) { showToast(err.message + details(err)); }
    });
  }

  const actions = document.getElementById('claim-actions');
  if (actions && claimId) {
    actions.querySelectorAll('button[data-action]').forEach(btn =>
      btn.addEventListener('click', () => handleAction(btn.dataset.action, btn, claimId)));
    const confirm = document.getElementById('note-confirm');
    confirm?.addEventListener('click', () => {
      const action = confirm.dataset.action;
      const note = document.getElementById('note-input').value;
      doAction(action, claimId, note);
      bootstrap.Modal.getInstance(document.getElementById('note-modal')).hide();
    });
  }

  const msgForm = document.getElementById('message-form');
  if (msgForm && matchId) wireMessaging(matchId, msgForm);
});

function details(err) {
  if (!err.details) return '';
  return ' — ' + Object.values(err.details).flat().join('; ');
}

function handleAction(action, btn, claimId) {
  if (action === 'reject' || action === 'dispute') {
    document.getElementById('note-title').textContent =
      action === 'reject' ? 'Rejection note (required)' : 'Dispute reason';
    document.getElementById('note-confirm').dataset.action = action;
    return; // modal opens via data-bs-toggle
  }
  doAction(action, claimId, '');
}

async function doAction(action, claimId, note) {
  const body = {};
  if (action === 'reject') body.review_note = note;
  if (action === 'dispute') body.reason = note;
  try {
    await apiFetch(`/claims/${claimId}/${action}`, { method: 'POST', body });
    showToast('Done', 'success');
    location.reload();
  } catch (err) { showToast(err.message + details(err)); }
}

// ------------------------------------------------------------------ messaging
function wireMessaging(matchId, form) {
  const box = document.getElementById('messages');
  const input = document.getElementById('message-input');
  const warn = document.getElementById('contact-warning');
  let lastId = 0;

  input.addEventListener('input', () => {
    const text = input.value;
    const suspicious = /(?:\+\d[\d\s\-()]{7,}\d)|([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/.test(text);
    warn.classList.toggle('d-none', !suspicious);
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    try {
      await apiFetch(`/matches/${matchId}/messages`, { method: 'POST', body: { message: text } });
      input.value = '';
      poll();
    } catch (err) { showToast(err.message); }
  });

  async function poll() {
    try {
      const msgs = await apiFetch(`/matches/${matchId}/messages?after_id=${lastId}`);
      if (msgs.length) {
        lastId = msgs[msgs.length - 1].id;
        box.insertAdjacentHTML('beforeend', msgs.map(m =>
          `<div class="border rounded p-2 mb-1"><div class="small text-muted">${escapeHtml(m.sender_name || '')} · ${fmtDate(m.created_at)}</div>${escapeHtml(m.message)}</div>`).join(''));
        box.scrollTop = box.scrollHeight;
      }
    } catch (e) { /* messaging may be closed */ }
  }
  poll();
  setInterval(poll, 10000);
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}
