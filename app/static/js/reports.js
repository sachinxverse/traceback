// Report form stepper + report detail interactions.
import { apiFetch, showToast } from './api.js';

const FORM = document.getElementById('report-form');

function reportType() {
  if (location.pathname.includes('/report/lost')) return 'LOST';
  if (location.pathname.includes('/report/found')) return 'FOUND';
  return null;
}

// ------------------------------------------------------------------ stepper
const STEP_COUNT = 4;
let currentStep = 1;

function showStep(n) {
  currentStep = Math.min(Math.max(n, 1), STEP_COUNT);
  FORM.querySelectorAll('.stepper-step').forEach(s =>
    s.classList.toggle('active', Number(s.dataset.step) === currentStep));
  document.getElementById('step-label').textContent = `Step ${currentStep} of ${STEP_COUNT}`;
  const bar = document.getElementById('step-progress');
  bar.setAttribute('aria-valuenow', String(currentStep));
  bar.querySelector('span').style.width = `${(currentStep / STEP_COUNT) * 100}%`;
  document.getElementById('step-back').disabled = currentStep === 1;
  document.getElementById('step-next').classList.toggle('d-none', currentStep === STEP_COUNT);
  document.getElementById('submit-btn').classList.toggle('d-none', currentStep !== STEP_COUNT);
  if (currentStep === 3) {
    // leaflet needs a resize when its container becomes visible
    const mapEl = document.getElementById('map-picker');
    if (mapEl && mapEl._tbMap) mapEl._tbMap.invalidateSize();
    window.dispatchEvent(new Event('resize'));
  }
  if (currentStep === 4) renderReview();
  try { FORM.scrollIntoView({ behavior: 'smooth', block: 'start' }); } catch (e) { /* reduced motion */ }
  window.dispatchEvent(new CustomEvent('tb:stepchange', { detail: { step: currentStep } }));
}

function validateStep(n) {
  let ok = true;
  const mark = (inputId, errId, bad) => {
    if (bad && ok === true) ok = false;
    const input = document.getElementById(inputId);
    const err = document.getElementById(errId);
    if (err) err.classList.toggle('show', bad);
    if (input) {
      input.setAttribute('aria-invalid', bad ? 'true' : 'false');
      input.classList.toggle('is-invalid', bad);
    }
  };
  if (n === 2) {
    mark('category-value', 'category-error', !document.getElementById('category-value').value);
    mark('title', 'title-error', document.getElementById('title').value.trim().length < 3);
    mark('description', 'description-error', document.getElementById('description').value.trim().length < 10);
    if (reportType() === 'FOUND') {
      const custody = document.querySelector('input[name="custody"]:checked');
      mark('custody1', 'custody-error', !custody);
    }
  }
  if (n === 3) {
    mark('incident_date', 'date-error', !document.getElementById('incident_date').value);
  }
  return ok;
}

function firstInvalidIn(step) {
  const section = FORM.querySelector(`.stepper-step[data-step="${step}"]`);
  return section ? section.querySelector('.is-invalid') : null;
}

// ------------------------------------------------------------- draft autosave
function draftKey() { return 'tb-draft-' + (reportType() || 'unknown').toLowerCase(); }

function saveDraft() {
  if (!FORM) return;
  try {
    const d = {};
    for (const id of ['category-value', 'title', 'description', 'private_details',
                      'incident_date', 'latitude', 'longitude', 'location_text', 'institution']) {
      const el = document.getElementById(id);
      if (el) d[id] = el.value;
    }
    const custody = document.querySelector('input[name="custody"]:checked');
    if (custody) d.custody = custody.value;
    localStorage.setItem(draftKey(), JSON.stringify(d));
  } catch (e) { /* storage unavailable */ }
}

function restoreDraft() {
  try {
    const raw = localStorage.getItem(draftKey());
    if (!raw) return;
    const d = JSON.parse(raw);
    for (const [id, v] of Object.entries(d)) {
      const el = document.getElementById(id);
      if (el && v) el.value = v;
    }
    if (d.custody) {
      const radio = document.querySelector(`input[name="custody"][value="${d.custody}"]`);
      if (radio) radio.checked = true;
    }
    if (d['category-value']) {
      const cell = FORM.querySelector(`.category-cell[data-value="${d['category-value']}"]`);
      if (cell) {
        FORM.querySelectorAll('.category-cell').forEach(c => c.classList.remove('selected'));
        cell.classList.add('selected');
        cell.setAttribute('aria-selected', 'true');
      }
    }
  } catch (e) { /* corrupt draft: ignore */ }
}

function clearDraft() {
  try { localStorage.removeItem(draftKey()); } catch (e) { /* ignore */ }
}

// ------------------------------------------------------------------ review
function esc(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderReview() {
  const val = id => (document.getElementById(id)?.value || '').trim();
  const cat = document.getElementById('category-value').value;
  const imgCount = document.getElementById('images').files.length;
  const lat = val('latitude'), lng = val('longitude');
  const custodyEl = document.querySelector('input[name="custody"]:checked');
  const instSel = document.getElementById('institution');
  const rows = [
    ['Photos', imgCount ? `${imgCount} photo${imgCount > 1 ? 's' : ''}` : 'None (recommended)'],
    ['Category', cat ? cat.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase()) : '—'],
    ['Title', esc(val('title')) || '—'],
    ['Description', esc(val('description')).slice(0, 140) || '—'],
    ['Date and time', val('incident_date') || '—'],
    ['Location', lat && lng ? `${(+lat).toFixed(4)}, ${(+(+lng)).toFixed(4)}` : (val('location_text') || 'Not set')],
  ];
  if (reportType() === 'FOUND') {
    rows.push(['Custody', custodyEl ? (custodyEl.value === 'WITH_FINDER' ? "I'm keeping it with me" : 'Held at an institution') : '—']);
  }
  if (instSel && instSel.value) {
    rows.push(['Institution', instSel.options[instSel.selectedIndex].text]);
  }
  document.getElementById('review-summary').innerHTML =
    `<div class="table-responsive"><table class="table table-sm align-middle mb-0">
      <tbody>${rows.map(r =>
        `<tr><th class="text-muted fw-semibold" style="width:140px">${esc(r[0])}</th><td>${r[1]}</td></tr>`).join('')}
      </tbody></table></div>`;
}

// ------------------------------------------------------------------ wiring
document.addEventListener('DOMContentLoaded', () => {
  const grid = document.getElementById('category-grid');
  if (grid) {
    const select = (cell) => {
      grid.querySelectorAll('.category-cell').forEach(c => {
        c.classList.remove('selected');
        c.setAttribute('aria-selected', 'false');
      });
      cell.classList.add('selected');
      cell.setAttribute('aria-selected', 'true');
      document.getElementById('category-value').value = cell.dataset.value;
      saveDraft();
    };
    grid.addEventListener('click', (e) => {
      const cell = e.target.closest('.category-cell');
      if (cell) select(cell);
    });
    grid.addEventListener('keydown', (e) => {
      const cell = e.target.closest('.category-cell');
      if (cell && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); select(cell); }
    });
  }

  const dz = document.getElementById('dropzone');
  const input = document.getElementById('images');
  if (dz && input) {
    dz.addEventListener('click', () => input.click());
    dz.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
    input.addEventListener('change', () => { renderPreviews(input.files); saveDraft(); });
    dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('dragover'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
    dz.addEventListener('drop', e => {
      e.preventDefault(); dz.classList.remove('dragover');
      input.files = e.dataTransfer.files;
      renderPreviews(input.files);
    });
  }

  if (FORM) {
    restoreDraft();
    showStep(1);
    // autosave text inputs
    for (const id of ['title', 'description', 'private_details', 'incident_date',
                      'location_text', 'institution', 'latitude', 'longitude']) {
      document.getElementById(id)?.addEventListener('input', saveDraft);
    }
    FORM.querySelectorAll('input[name="custody"]').forEach(r => r.addEventListener('change', saveDraft));
    FORM.addEventListener('submit', onSubmit);
    document.getElementById('step-next').addEventListener('click', () => {
      if (!validateStep(currentStep)) {
        showToast('Please fix the highlighted fields first');
        firstInvalidIn(currentStep)?.focus();
        return;
      }
      showStep(currentStep + 1);
    });
    document.getElementById('step-back').addEventListener('click', () => showStep(currentStep - 1));
  }

  // report detail page buttons
  const closeBtn = document.getElementById('close-btn');
  if (closeBtn) closeBtn.addEventListener('click', doClose);
  const rematchBtn = document.getElementById('rematch-btn');
  if (rematchBtn) rematchBtn.addEventListener('click', doRematch);
  wireCarousel();
});

function renderPreviews(files) {
  const row = document.getElementById('preview-row');
  row.innerHTML = '';
  for (const f of Array.from(files).slice(0, 4)) {
    const img = document.createElement('img');
    img.className = 'img-thumb';
    img.src = URL.createObjectURL(f);
    img.alt = f.name;
    row.appendChild(img);
  }
}

async function onSubmit(e) {
  e.preventDefault();
  // validate all steps before submitting
  for (let s = 1; s <= 3; s++) {
    if (!validateStep(s)) {
      showStep(s);
      showToast('Please fix the highlighted fields first');
      firstInvalidIn(s)?.focus();
      return;
    }
  }
  const btn = document.getElementById('submit-btn');
  btn.disabled = true;
  btn.setAttribute('aria-busy', 'true');
  btn.querySelector('.btn-label')?.classList.add('d-none');
  btn.querySelector('.btn-spin')?.classList.remove('d-none');
  const type = reportType();
  const fd = new FormData();
  fd.append('report_type', type);
  const val = id => document.getElementById(id)?.value ?? '';
  fd.append('category', val('category-value'));
  fd.append('title', val('title'));
  fd.append('description', val('description'));
  const pd = val('private_details');
  if (pd) fd.append('private_details', pd);
  const d = val('incident_date');
  if (d) fd.append('incident_date', new Date(d).toISOString().slice(0, 19));
  const lat = val('latitude'), lng = val('longitude');
  if (lat && lng) { fd.append('latitude', lat); fd.append('longitude', lng); }
  const lt = val('location_text');
  if (lt) fd.append('location_text', lt);
  const inst = val('institution');
  if (inst) fd.append('institution_id', inst);
  if (type === 'FOUND') {
    fd.append('custody', document.querySelector('input[name="custody"]:checked').value);
  }
  for (const f of Array.from(document.getElementById('images').files).slice(0, 4)) {
    fd.append('images', f);
  }
  document.getElementById('processing-note').classList.remove('d-none');
  try {
    const report = await apiFetch('/reports', { method: 'POST', formData: fd });
    clearDraft();
    showToast('Report submitted — processing for matches', 'success');
    setTimeout(() => { window.location.href = `/reports/${report.id}`; }, 800);
  } catch (err) {
    showToast(err.message + (err.details ? ' — ' + Object.values(err.details).flat().join('; ') : ''));
    document.getElementById('processing-note').classList.add('d-none');
    btn.disabled = false;
    btn.setAttribute('aria-busy', 'false');
    btn.querySelector('.btn-label')?.classList.remove('d-none');
    btn.querySelector('.btn-spin')?.classList.add('d-none');
  }
}

async function doClose() {
  const id = reportIdFromPath();
  try {
    await apiFetch(`/reports/${id}/close`, { method: 'POST' });
    showToast('Report closed', 'success');
    location.reload();
  } catch (err) { showToast(err.message); }
}

async function doRematch() {
  const id = reportIdFromPath();
  try {
    await apiFetch(`/reports/${id}/rematch`, { method: 'POST' });
    showToast('Re-matching complete', 'success');
    location.reload();
  } catch (err) { showToast(err.message); }
}

function reportIdFromPath() {
  return parseInt(location.pathname.split('/')[2], 10);
}

function wireCarousel() {
  const prev = document.getElementById('img-prev');
  const next = document.getElementById('img-next');
  if (!prev) return;
  const imgs = Array.from(document.querySelectorAll('.report-img'));
  let idx = 0;
  const show = () => imgs.forEach((im, i) => im.classList.toggle('d-none', i !== idx));
  prev.addEventListener('click', () => { idx = (idx - 1 + imgs.length) % imgs.length; show(); });
  next.addEventListener('click', () => { idx = (idx + 1) % imgs.length; show(); });
}
