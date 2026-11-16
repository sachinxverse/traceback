// Theme bootstrap — loaded as a classic script in <head> BEFORE any CSS so the
// dark theme applies before first paint (no flash). CSP forbids inline scripts,
// so this lives in its own file.
(function () {
  try {
    var pref = localStorage.getItem('tb-theme') || 'light';
    if (pref === 'system') {
      pref = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    if (pref === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
  } catch (e) { /* private mode: keep light */ }
})();
