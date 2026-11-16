// Institutions directory: search-as-you-type with debounce (U7).
  // search-as-you-type with debounce (U7)
  const input = document.getElementById('inst-search-input');
  const grid = document.getElementById('inst-grid');
  const form = document.getElementById('inst-search-form');
  if (input && grid) {
    let timer = null;
    input.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => form.requestSubmit(), 350);
    });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const q = input.value.trim();
      const url = new URL('/api/v1/institutions', location.origin);
      if (q) url.searchParams.set('q', q);
      const resp = await fetch(url);
      const payload = await resp.json();
      const items = payload.data || [];
      grid.innerHTML = items.length ? items.map(i => `
        <div class="col-md-6 col-lg-4">
          <div class="card card-hover p-3 h-100">
            <a class="stretched-link-card" href="/i/${i.slug}" aria-label="View ${i.name}"></a>
            <div class="inst-card">
              <div class="inst-icon"><i class="bi bi-building"></i></div>
              <div class="min-w-0">
                <h5>${i.name}</h5>
                <div class="inst-meta">
                  <span class="badge-type">${(i.institution_type || '').replace(/_/g, ' ').toLowerCase().replace(/\\b\\w/g, c => c.toUpperCase()) || 'Partner'}</span>
                  ${i.verified ? '<span class="badge-verified"><i class="bi bi-patch-check-fill"></i>Verified</span>' : ''}
                </div>
                <p class="small mb-0 mt-1">${i.address || ''}</p>
              </div>
            </div>
            <div class="inst-actions position-relative">
              <a class="btn btn-amber btn-sm" href="/report/lost?institution=${i.slug}"><i class="bi bi-search-heart me-1"></i>Report lost here</a>
              <a class="btn btn-found btn-sm" href="/report/found?institution=${i.slug}"><i class="bi bi-hand-thumbs-up me-1"></i>Report found here</a>
            </div>
          </div>
        </div>`).join('')
        : '<div class="col-12"><div class="empty-state"><div class="es-icon"><i class="bi bi-building"></i></div>' +
          '<div class="es-title">No institutions match your search</div>' +
          '<div class="small mb-0">Try a different name, city or type — or clear the search.</div></div></div>';
      history.replaceState(null, '', q ? `/institutions?q=${encodeURIComponent(q)}` : '/institutions');
    });
  }
