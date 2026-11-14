// Match list rendering for a report page.
import { apiFetch, showToast, fmtDate } from './api.js';

document.addEventListener('DOMContentLoaded', () => {
  const list = document.getElementById('matches-list');
  if (!list) return;
  const id = parseInt(location.pathname.split('/')[2], 10);
  loadMatches(id, list);
});

async function loadMatches(id, list) {
  try {
    const matches = await apiFetch(`/reports/${id}/matches`);
    if (!matches.length) {
      list.innerHTML = '<div class="text-muted">No matches yet. Check back after processing.</div>';
      return;
    }
    list.innerHTML = matches.map(m => {
      const b = m.breakdown;
      const bar = (label, v) => `<div class="mb-1"><div class="d-flex justify-content-between"><small>${label}</small><small>${v ?? '—'}</small></div>
        <div class="breakdown-bar"><span style="width:${v ?? 0}%"></span></div></div>`;
      return `<div class="card p-3 mb-2">
        <div class="d-flex gap-3 align-items-center">
          ${m.counterpart.image_urls?.[0] ? `<img class="img-thumb" src="${m.counterpart.image_urls[0]}" alt="">` : ''}
          <div class="flex-grow-1">
            <div class="fw-bold">${escapeHtml(m.counterpart.title)}</div>
            <div class="text-muted small">${fmtDate(m.counterpart.incident_date)}</div>
            <div class="d-flex align-items-center gap-2 mt-1">
              <span class="match-gauge">${m.score}%</span>
              <span class="status-pill status-${m.confidence}">${m.confidence}</span>
            </div>
            <div class="row g-2 mt-2">
              <div class="col-6">${bar('Image', b.image)}</div>
              <div class="col-6">${bar('Text', b.text)}</div>
              <div class="col-6">${bar('Location', b.location)}</div>
              <div class="col-6">${bar('Time', b.time)}</div>
            </div>
            <div class="text-muted small mt-1">signals: ${(m.signals_used || []).join(', ') || '—'}</div>
          </div>
          <div class="d-flex flex-column gap-2">
            <a class="btn btn-sm btn-primary" href="/matches/${m.id}">View match</a>
            <button class="btn btn-sm btn-outline-secondary dismiss-btn" data-id="${m.id}">Dismiss</button>
          </div>
        </div>
      </div>`;
    }).join('');
    list.querySelectorAll('.dismiss-btn').forEach(btn =>
      btn.addEventListener('click', async () => {
        try {
          await apiFetch(`/matches/${btn.dataset.id}/dismiss`, { method: 'POST' });
          showToast('Match dismissed', 'success');
          btn.closest('.card').remove();
        } catch (e) { showToast(e.message); }
      }));
  } catch (e) {
    list.innerHTML = `<div class="text-muted">Could not load matches.</div>`;
  }
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}
