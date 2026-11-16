// Notifications page: mark-all-read button.
import { apiFetch } from '/static/js/api.js';
document.getElementById('read-all')?.addEventListener('click', async () => {
  await apiFetch('/notifications/read-all', { method: 'POST' });
  location.reload();
});
