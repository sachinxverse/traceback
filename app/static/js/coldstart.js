// Cold-start UX (Issue 4.4): the Render free tier sleeps after ~15 min
// idle and takes up to ~50 s to wake. Instead of a silent hang or a raw
// error, show a friendly "waking up" banner and keep retrying the health
// endpoint until the app responds (or give up after a generous window).
const API = '/api/v1';

let banner = null;

function ensureBanner() {
  if (banner) return banner;
  banner = document.createElement('div');
  banner.id = 'coldstart-banner';
  banner.className = 'coldstart-banner';
  banner.setAttribute('role', 'status');
  banner.innerHTML =
    '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>' +
    '<span class="coldstart-msg">Waking up the server — this takes up to a minute…</span>';
  document.body.appendChild(banner);
  return banner;
}

function hideBanner() {
  if (banner) {
    banner.remove();
    banner = null;
  }
}

async function waitForWake(timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(API + '/health', { cache: 'no-store' });
      if (r.ok) {
        hideBanner();
        return true;
      }
    } catch (e) { /* still asleep — keep polling */ }
    await new Promise(res => setTimeout(res, 4000));
  }
  hideBanner();
  return false;
}

// Warm up immediately on every page load; the banner only appears if the
// first response takes longer than 3s (i.e. the instance is asleep).
export function warmUp() {
  ensureBanner();
  const t0 = Date.now();
  return new Promise((resolve) => {
    const tick = async () => {
      try {
        const r = await fetch(API + '/health', { cache: 'no-store' });
        if (r.ok) {
          if (Date.now() - t0 > 3000) hideBanner();
          else hideBanner();
          resolve(true);
          return;
        }
      } catch (e) { /* asleep */ }
      if (Date.now() - t0 > 3000) {
        // banner already visible — keep polling until awake
        await waitForWake();
        resolve(true);
      } else {
        setTimeout(tick, 800);
      }
    };
    tick();
  });
}

// Outbound link interception: a plain <a href> navigation on a sleeping
// instance hangs silently for up to ~50 s with zero feedback (the banner
// above only covers in-page API calls and fresh page loads). Intercept
// internal link clicks, wake the instance first, then navigate.
function isInternalLink(el) {
  if (!(el instanceof HTMLAnchorElement)) return false;
  if (el.target && el.target !== '_self') return false;
  if (el.hasAttribute('download')) return false;
  if (el.getAttribute('href')?.startsWith('#')) return false;
  const href = new URL(el.href, location.href);
  return href.origin === location.origin;
}

document.addEventListener('click', async (ev) => {
  if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey ||
      ev.shiftKey || ev.altKey) return;
  const link = ev.target.closest('a');
  if (!link || !isInternalLink(link)) return;
  ev.preventDefault();
  const href = link.href;
  // If the instance answers quickly, navigate straight away; otherwise show
  // the wake banner until the instance is warm, then continue navigating.
  const t0 = Date.now();
  ensureBanner();
  let warm = false;
  try {
    const r = await Promise.race([
      fetch(API + '/health', { cache: 'no-store' }),
      new Promise(res => setTimeout(() => res(null), 2500)),
    ]);
    warm = Boolean(r && r.ok);
  } catch (e) { warm = false; }
  if (!warm && Date.now() - t0 < 2500) {
    // health endpoint not answered within budget — poll until awake
    await waitForWake();
  } else {
    hideBanner();
  }
  window.location.href = href;
}, true);

// Auto-run on import so every page benefits, including a cold load.
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', warmUp);
} else {
  warmUp();
}
