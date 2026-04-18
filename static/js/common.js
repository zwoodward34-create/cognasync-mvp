// Shared utilities

function getSessionToken() {
  const cookies = Object.fromEntries(
    document.cookie.split(';').map(c => c.trim().split('='))
  );
  // Try Flask session cookie approach — token is stored server-side.
  // For API calls from the browser, we read it from a meta tag if present.
  const meta = document.querySelector('meta[name="session-token"]');
  return meta ? meta.content : null;
}

async function apiGet(url) {
  const res = await fetch(url, {
    method: 'GET',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Request failed');
  return data;
}

async function apiPost(url, body = {}) {
  const res = await fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'Request failed');
  return data;
}

function toggleSection(id) {
  const el = document.getElementById(id);
  el.classList.toggle('open');
  const btn = el.previousElementSibling;
  if (btn) {
    const arrow = btn.querySelector('.toggle-arrow');
    if (arrow) arrow.textContent = el.classList.contains('open') ? '▲' : '▼';
  }
}

function showAlert(id, message, autohide = false) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = message;
  el.classList.remove('hidden');
  if (autohide) setTimeout(() => el.classList.add('hidden'), 5000);
}

function hideAlert(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('hidden');
}

// Auto-dismiss flash messages
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.flash').forEach(el => {
    setTimeout(() => el.style.opacity = '0', 4000);
    setTimeout(() => el.remove(), 4600);
  });
});
