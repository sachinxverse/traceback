// Admin portal interactions.
import { apiFetch, showToast, fmtDate } from './api.js';

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('kpi-cards')) loadAnalytics();
  if (document.getElementById('reports-table')) loadReports();
  if (document.getElementById('claims-table')) loadClaims('all');
  document.querySelectorAll('.nav-tabs [data-status]').forEach(a =>
    a.addEventListener('click', (e) => { e.preventDefault(); loadClaims(a.dataset.status); }));
  if (document.getElementById('users-table')) loadUsers();
  if (document.getElementById('inst-table')) wireInstitutions();
  if (document.getElementById('recoveries-table')) loadRecoveries();
});

async function loadAnalytics() {
  try {
    const s = await apiFetch('/admin/analytics/summary');
    const cards = [
      ['Reports', s.total_reports], ['Lost', s.lost_reports], ['Found', s.found_reports],
      ['Active', s.active_reports], ['Matched', s.matched_reports], ['Recovered', s.recovered_reports],
      ['Open claims', s.open_claims], ['Disputed', s.disputed_claims],
      ['Potential match rate', s.potential_match_rate != null ? Math.round(s.potential_match_rate * 100) + '%' : '—'],
      ['Verified recovery rate', s.verified_recovery_rate != null ? Math.round(s.verified_recovery_rate * 100) + '%' : '—'],
      ['Avg hours to candidate', s.avg_hours_to_first_candidate ?? '—'],
      ['False candidate rate', s.false_candidate_rate != null ? Math.round(s.false_candidate_rate * 100) + '%' : '—'],
      ['Active users (30d)', s.active_users_30d ?? '—'], ['Institutions', s.institutions_count ?? '—'],
    ];
    document.getElementById('kpi-cards').innerHTML = cards.map(([k, v]) =>
      `<div class="col-md-3"><div class="card p-3"><div class="fs-5 fw-bold">${v}</div><div class="text-muted small">${k}</div></div></div>`).join('');

    const ts = await apiFetch('/admin/analytics/timeseries');
    new Chart(document.getElementById('timeseries-chart'), {
      type: 'line',
      data: {
        labels: ts.points.map(p => p.date),
        datasets: [
          { label: 'Lost', data: ts.points.map(p => p.lost), borderColor: '#D97706' },
          { label: 'Found', data: ts.points.map(p => p.found), borderColor: '#1D4ED8' },
          { label: 'Recovered', data: ts.points.map(p => p.recovered), borderColor: '#0D9488' },
        ],
      },
    });

    const cats = await apiFetch('/admin/analytics/categories');
    new Chart(document.getElementById('category-chart'), {
      type: 'bar',
      data: {
        labels: cats.map(c => c.category),
        datasets: [
          { label: 'Lost', data: cats.map(c => c.lost), backgroundColor: '#D97706' },
          { label: 'Found', data: cats.map(c => c.found), backgroundColor: '#1D4ED8' },
          { label: 'Recovered', data: cats.map(c => c.recovered), backgroundColor: '#0D9488' },
        ],
      },
    });

    const map = L.map('admin-heatmap').setView([30.0668, 79.0193], 5);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
    async function drawHeat() {
      const from = document.getElementById('hm-from').value;
      const to = document.getElementById('hm-to').value;
      const qs = new URLSearchParams();
      if (from) qs.set('from', from);
      if (to) qs.set('to', to);
      const cells = await apiFetch('/admin/analytics/heatmap' + (qs.toString() ? '?' + qs : ''));
      if (window._heat) map.removeLayer(window._heat);
      window._heat = L.heatLayer(cells.map(c => [c.lat, c.lng, c.count]),
        { radius: 25, blur: 12, maxZoom: 12 }).addTo(map);
    }
    drawHeat();
    document.getElementById('hm-apply').addEventListener('click', drawHeat);
  } catch (e) { showToast(e.message); }
}

async function loadReports() {
  try {
    const qs = new URLSearchParams(new FormData(document.getElementById('filter-form'))).toString();
    const rows = await apiFetch('/admin/reports' + (qs ? '?' + qs : ''));
    document.querySelector('#reports-table tbody').innerHTML = rows.map(r => `<tr>
      <td>${r.id}</td><td><a href="/reports/${r.id}">${escapeHtml(r.title)}</a></td>
      <td>${r.report_type}</td><td><span class="status-pill status-${r.status}">${r.status}</span></td>
      <td>${escapeHtml(r.owner_first_name || '')}</td>
      <td>${r.status === 'REMOVED'
        ? `<button class="btn btn-sm btn-outline-secondary restore-btn" data-id="${r.id}">Restore</button>`
        : `<button class="btn btn-sm btn-outline-danger remove-btn" data-id="${r.id}">Remove</button>`}</td>
    </tr>`).join('');
    document.querySelectorAll('.remove-btn').forEach(b => b.addEventListener('click', () => {
      const modal = new bootstrap.Modal(document.getElementById('reason-modal'));
      modal.show();
      document.getElementById('reason-confirm').onclick = async () => {
        try {
          await apiFetch(`/admin/reports/${b.dataset.id}/remove`,
            { method: 'POST', body: { reason: document.getElementById('reason-input').value } });
          modal.hide(); loadReports();
        } catch (e) { showToast(e.message); }
      };
    }));
    document.querySelectorAll('.restore-btn').forEach(b => b.addEventListener('click', async () => {
      try { await apiFetch(`/admin/reports/${b.dataset.id}/restore`, { method: 'POST' }); loadReports(); }
      catch (e) { showToast(e.message); }
    }));
  } catch (e) { showToast(e.message); }
}

async function loadClaims(status) {
  try {
    const wanted = status === 'all' ? 'PENDING' : status.toUpperCase();
    const rows = await apiFetch('/admin/claims?status=' + wanted);
    document.querySelector('#claims-table tbody').innerHTML = rows.map(c => `<tr>
      <td>${c.id}</td><td>${c.found_public ? escapeHtml(c.found_public.title) : ''}</td>
      <td><span class="status-pill status-${c.status}">${c.status}</span></td>
      <td>${c.claimant_id}</td>
      <td><a class="btn btn-sm btn-outline-primary" href="/claims/${c.id}">Open</a></td></tr>`).join('');
  } catch (e) { showToast(e.message); }
}

async function loadUsers() {
  try {
    const q = document.getElementById('user-q').value.trim();
    const rows = await apiFetch('/admin/users' + (q ? '?q=' + encodeURIComponent(q) : ''));
    document.querySelector('#users-table tbody').innerHTML = rows.map(u => `<tr>
      <td>${u.id}</td><td>${escapeHtml(u.name)}</td><td>${escapeHtml(u.email)}</td>
      <td>${u.role}</td><td>${u.institution ? escapeHtml(u.institution.name) : '—'}</td>
      <td>${u.is_active ? '✔' : '—'}</td>
      <td><button class="btn btn-sm btn-outline-primary edit-user" data-id="${u.id}" data-role="${u.role}" data-inst="${u.institution_id || ''}">Edit</button></td></tr>`).join('');
    document.querySelectorAll('.edit-user').forEach(b => b.addEventListener('click', () => {
      const role = prompt('Role (USER/STAFF/ADMIN):', b.dataset.role);
      if (!role) return;
      const inst = role === 'STAFF' ? prompt('Institution ID:', b.dataset.inst) : null;
      const body = { role };
      if (role === 'STAFF' && inst) body.institution_id = parseInt(inst, 10);
      apiFetch(`/admin/users/${b.dataset.id}`, { method: 'PATCH', body })
        .then(loadUsers).catch(e => showToast(e.message));
    }));
  } catch (e) { showToast(e.message); }
  document.getElementById('user-q').onchange = loadUsers;
}

function wireInstitutions() {
  document.querySelectorAll('.edit-inst').forEach(b => b.addEventListener('click', async () => {
    const id = b.dataset.id;
    const insts = await apiFetch('/institutions');
    const inst = insts.find(i => i.id == id);
    if (!inst) return;
    document.getElementById('inst-id').value = inst.id;
    document.getElementById('inst-name').value = inst.name;
    document.getElementById('inst-type').value = inst.institution_type || 'OTHER';
    document.getElementById('inst-address').value = inst.address || '';
    document.getElementById('inst-lat').value = inst.latitude ?? '';
    document.getElementById('inst-lng').value = inst.longitude ?? '';
    document.getElementById('inst-verified').checked = false;
    new bootstrap.Modal(document.getElementById('inst-modal')).show();
  }));
  document.getElementById('inst-save').addEventListener('click', async () => {
    const id = document.getElementById('inst-id').value;
    const body = {
      name: document.getElementById('inst-name').value,
      institution_type: document.getElementById('inst-type').value,
      address: document.getElementById('inst-address').value,
      latitude: parseFloat(document.getElementById('inst-lat').value) || null,
      longitude: parseFloat(document.getElementById('inst-lng').value) || null,
    };
    try {
      if (id) await apiFetch(`/institutions/${id}`, { method: 'PATCH', body });
      else await apiFetch('/institutions', { method: 'POST', body });
      location.reload();
    } catch (e) { showToast(e.message); }
  });
}

async function loadRecoveries() {
  try {
    const rows = await apiFetch('/admin/recoveries');
    document.querySelector('#recoveries-table tbody').innerHTML = rows.map(r => `<tr>
      <td>${r.claim_id}</td><td>${escapeHtml(r.lost_report_title)}</td>
      <td>${fmtDate(r.created_at)}</td><td>${fmtDate(r.handed_over_at)}</td>
      <td>${fmtDate(r.received_confirmed_at)}</td><td>${r.duration_hours ?? '—'}</td></tr>`).join('');
  } catch (e) { showToast(e.message); }
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
