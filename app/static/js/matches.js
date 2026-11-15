// Match list rendering for a report page (with score rings + animated bars).
import { apiFetch, showToast, fmtDate } from './api.js';

document.addEventListener('DOMContentLoaded', () => {
  const list = document.getElementById('matches-list');
  if (!list) return;
  const id = parseInt(location.pathname.split('/')[2], 10);
  loadMatches(id, list);
});

function ringSvg(score, size = 46) {
  const r = 19, c = 2 * Math.PI * r;
  const col = score >= 75 ? '#16A34A' : score >= 55 ? '#F59E0B' : '#94A3B8';
  return `<span class="score-ring" style="width:${size}px;height:${size}px">
    <svg viewBox="0 0 44 44" width="${size}" height="${size}" style="transform:rotate(-90deg)">
      <circle class="ring-track" cx="22" cy="22" r="${r}" fill="none" stroke-width="4.5"></circle>
      <circle class="ring-fill" cx="22" cy="22" r="${r}" fill="none" stroke-width="4.5" stroke="${col}"
        stroke-dasharray="${(c * score / 100).toFixed(1)} ${c.toFixed(1)}"></circle>
    </svg>
    <span class="ring-label" style="font-size:.78rem">${score}</span></span>`;
}

async function loadMatches(id, list) {
  try {
    const matches = await apiFetch(`/reports/${id}/matches`);
    const count = document.getElementById('match-count');
    if (count) count.textContent = matches.length ? `${matches.length} candidate${matches.length > 1 ? 's' : ''}` : '';
    if (!matches.length) {
      list.innerHTML = `<div class="card p-3"><div class="empty-state" style="padding:1.6rem 1rem">
        <div class="es-icon"><i class="bi bi-stars"></i></div>
        <div class="es-title">No matches yet</div>
        <div class="small mb-0">Matching runs automatically once processing completes. Check back after a moment.</div>
      </div></div>`;
      return;
    }
    list.innerHTML = matches.map(m => {
      const b = m.breakdown;
      const bar = (label, sig, v) => `<div class="mb-2">
        <div class="d-flex justify-content-between"><small class="text-muted" style="font-weight:600">
          <i class="bi ${{'image':'bi-images','text':'bi-chat-left-text','location':'bi-geo-alt','time':'bi-clock'}[sig]}"></i> ${label}</small>
          <small class="fw-bold" style="color:var(--navy)">${v ?? '—'}</small></div>
        <div class="breakdown-bar bar-${sig}"><span data-width="${v ?? 0}"></span></div></div>`;
      return `<div class="card card-hover p-3 mb-2">
        <div class="d-flex gap-3 align-items-center flex-wrap flex-sm-nowrap">
          ${m.counterpart.image_urls?.[0]
            ? `<img class="img-thumb" src="${m.counterpart.image_urls[0]}" alt="">`
            : `<div class="img-thumb d-grid" style="place-items:center;color:#94A3B8"><i class="bi bi-image fs-4"></i></div>`}
          <div class="flex-grow-1 min-w-0">
            <div class="d-flex align-items-center gap-2 flex-wrap">
              <span class="fw-bold text-truncate" style="max-width:240px">${escapeHtml(m.counterpart.title)}</span>
              <span class="status-pill status-${m.confidence}">${m.confidence}</span>
            </div>
            <div class="text-muted small">${fmtDate(m.counterpart.incident_date)}</div>
            <div class="d-flex align-items-center gap-2 mt-2">
              ${ringSvg(m.score)}
              <div class="flex-grow-1 min-w-0">
                <div class="row g-1">
                  <div class="col-6">${bar('Image', 'image', b.image)}</div>
                  <div class="col-6">${bar('Text', 'text', b.text)}</div>
                  <div class="col-6">${bar('Location', 'location', b.location)}</div>
                  <div class="col-6">${bar('Time', 'time', b.time)}</div>
                </div>
                <div class="text-muted small mt-1">signals: ${(m.signals_used || []).join(', ') || '—'}</div>
              </div>
            </div>
          </div>
          <div class="d-flex flex-column gap-2">
            <a class="btn btn-sm btn-primary" href="/matches/${m.id}">Compare <i class="bi bi-arrows-angle-contract"></i></a>
            <button class="btn btn-sm btn-outline-secondary dismiss-btn" data-id="${m.id}">Dismiss</button>
          </div>
        </div>
      </div>`;
    }).join('');
    // animate bars
    requestAnimationFrame(() =>
      list.querySelectorAll('.breakdown-bar > span').forEach(s => s.style.width = s.dataset.width + '%'));
    list.querySelectorAll('.dismiss-btn').forEach(btn =>
      btn.addEventListener('click', async () => {
        try {
          await apiFetch(`/matches/${btn.dataset.id}/dismiss`, { method: 'POST' });
          showToast('Match dismissed', 'success');
          btn.closest('.card').remove();
        } catch (e) { showToast(e.message); }
      }));
  } catch (e) {
    list.innerHTML = `<div class="card p-3 text-muted small">Could not load matches.</div>`;
  }
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
