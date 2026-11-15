// Leaflet map helpers: report form picker, match comparison, report location.
document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('map-picker')) initPicker();
  if (document.getElementById('match-map')) initMatchMap();
  if (document.getElementById('report-map')) initReportMap();
});

function tileLayer(map) {
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);
}

function initPicker() {
  const map = L.map('map-picker').setView([30.0668, 79.0193], 5);
  tileLayer(map);
  let marker = null;
  const latInput = document.getElementById('latitude');
  const lngInput = document.getElementById('longitude');
  const preLat = document.getElementById('prefill-lat')?.value;
  const preLng = document.getElementById('prefill-lng')?.value;
  if (preLat && preLng) {
    map.setView([parseFloat(preLat), parseFloat(preLng)], 14);
    marker = L.marker([parseFloat(preLat), parseFloat(preLng)]).addTo(map);
    latInput.value = preLat; lngInput.value = preLng;
  }
  map.on('click', (e) => {
    if (marker) marker.setLatLng(e.latlng); else marker = L.marker(e.latlng).addTo(map);
    latInput.value = e.latlng.lat.toFixed(6);
    lngInput.value = e.latlng.lng.toFixed(6);
  });
  document.getElementById('geo-loc-btn')?.addEventListener('click', () => {
    navigator.geolocation?.getCurrentPosition(pos => {
      map.setView([pos.coords.latitude, pos.coords.longitude], 15);
      if (marker) marker.setLatLng(map.getCenter()); else marker = L.marker(map.getCenter()).addTo(map);
      latInput.value = pos.coords.latitude.toFixed(6);
      lngInput.value = pos.coords.longitude.toFixed(6);
    });
  });
  wireGeocode((lat, lng, label) => {
    map.setView([lat, lng], 14);
    if (marker) marker.setLatLng([lat, lng]); else marker = L.marker([lat, lng]).addTo(map);
    latInput.value = lat; lngInput.value = lng;
    const lt = document.getElementById('location_text');
    if (lt && !lt.value) lt.value = label;
  });
}

function wireGeocode(onPick) {
  const btn = document.getElementById('geocode-btn');
  const q = document.getElementById('geocode-q');
  const out = document.getElementById('geocode-results');
  btn?.addEventListener('click', async () => {
    if (!q.value.trim()) return;
    try {
      const res = await fetch('/api/v1/geocode?q=' + encodeURIComponent(q.value.trim()));
      const payload = await res.json();
      const items = payload.data || [];
      out.innerHTML = items.map((r, i) =>
        `<button type="button" class="list-group-item list-group-item-action" data-i="${i}">${escapeHtml(r.label)}</button>`).join('');
      out.querySelectorAll('button').forEach(b =>
        b.addEventListener('click', () => {
          const r = items[parseInt(b.dataset.i, 10)];
          onPick(r.lat, r.lng, r.label);
          out.innerHTML = '';
        }));
    } catch (e) { out.innerHTML = ''; }
  });
}

function initMatchMap() {
  const el = document.getElementById('match-map');
  const map = L.map('match-map');
  tileLayer(map);
  const lostLat = parseFloat(el.dataset.lostLat || 'NaN');
  const lostLng = parseFloat(el.dataset.lostLng || 'NaN');
  const foundLat = parseFloat(el.dataset.foundLat || 'NaN');
  const foundLng = parseFloat(el.dataset.foundLng || 'NaN');
  const pts = [];
  if (!isNaN(lostLat)) { L.marker([lostLat, lostLng]).addTo(map).bindPopup('Lost'); pts.push([lostLat, lostLng]); }
  if (!isNaN(foundLat)) { L.marker([foundLat, foundLng]).addTo(map).bindPopup('Found'); pts.push([foundLat, foundLng]); }
  if (pts.length === 1) map.setView(pts[0], 13); else if (pts.length > 1) map.fitBounds(pts); else map.setView([30.0668, 79.0193], 5);
}

function initReportMap() {
  const el = document.getElementById('report-map');
  const lat = parseFloat(el.dataset.lat), lng = parseFloat(el.dataset.lng);
  const map = L.map('report-map').setView([lat, lng], 14);
  tileLayer(map);
  L.marker([lat, lng]).addTo(map);
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
