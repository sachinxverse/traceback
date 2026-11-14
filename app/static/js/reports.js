// Report form + report detail interactions.
import { apiFetch, showToast } from './api.js';

const FORM = document.getElementById('report-form');

function reportType() {
  if (location.pathname.includes('/report/lost')) return 'LOST';
  if (location.pathname.includes('/report/found')) return 'FOUND';
  return null;
}

document.addEventListener('DOMContentLoaded', () => {
  // category grid
  const grid = document.getElementById('category-grid');
  if (grid) {
    grid.addEventListener('click', (e) => {
      const cell = e.target.closest('.category-cell');
      if (!cell) return;
      grid.querySelectorAll('.category-cell').forEach(c => c.classList.remove('selected'));
      cell.classList.add('selected');
      document.getElementById('category-value').value = cell.dataset.value;
    });
  }

  // dropzone
  const dz = document.getElementById('dropzone');
  const input = document.getElementById('images');
  if (dz && input) {
    dz.addEventListener('click', () => input.click());
    input.addEventListener('change', () => renderPreviews(input.files));
    dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('dragover'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
    dz.addEventListener('drop', e => {
      e.preventDefault(); dz.classList.remove('dragover');
      input.files = e.dataTransfer.files;
      renderPreviews(input.files);
    });
  }

  // submit
  if (FORM) FORM.addEventListener('submit', onSubmit);

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
  const btn = document.getElementById('submit-btn');
  btn.disabled = true;
  const type = reportType();
  const fd = new FormData();
  fd.append('report_type', type);
  const cat = document.getElementById('category-value').value;
  if (!cat) { showToast('Please choose a category'); btn.disabled = false; return; }
  fd.append('category', cat);
  const val = id => document.getElementById(id)?.value ?? '';
  fd.append('title', val('title'));
  fd.append('description', val('description'));
  const pd = val('private_details');
  if (pd) fd.append('private_details', pd);
  // datetime-local -> ISO with seconds
  const d = val('incident_date');
  if (d) fd.append('incident_date', new Date(d).toISOString().slice(0, 19));
  const lat = val('latitude'), lng = val('longitude');
  if (lat && lng) { fd.append('latitude', lat); fd.append('longitude', lng); }
  const lt = val('location_text');
  if (lt) fd.append('location_text', lt);
  const inst = val('institution');
  if (inst) fd.append('institution_id', inst);
  if (type === 'FOUND') {
    const custody = document.querySelector('input[name="custody"]:checked')?.value;
    if (!custody) { showToast('Please choose custody'); btn.disabled = false; return; }
    fd.append('custody', custody);
  }
  for (const f of Array.from(document.getElementById('images').files).slice(0, 4)) {
    fd.append('images', f);
  }
  document.getElementById('processing-note').classList.remove('d-none');
  try {
    const report = await apiFetch('/reports', { method: 'POST', formData: fd });
    showToast('Report submitted — processing for matches', 'success');
    setTimeout(() => { window.location.href = `/reports/${report.id}`; }, 800);
  } catch (err) {
    showToast(err.message + (err.details ? ' — ' + Object.values(err.details).flat().join('; ') : ''));
    document.getElementById('processing-note').classList.add('d-none');
    btn.disabled = false;
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
