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

/**
 * Render thumbs-up / thumbs-down feedback buttons into `container`.
 *
 * @param {string} contentType  'checkin' | 'journal' | 'summary'
 * @param {string} contentId    The database ID of the AI-generated row
 * @param {HTMLElement} container  Where to mount the buttons
 */
function renderAiFeedback(contentType, contentId, container) {
  const wrap = document.createElement('div');
  wrap.className = 'ai-feedback-row';
  wrap.style.cssText = 'display:flex;align-items:center;gap:8px;margin-top:10px';

  const label = document.createElement('span');
  label.textContent = 'Helpful?';
  label.style.cssText = 'font-size:11px;color:var(--text-muted,#888);letter-spacing:.04em';

  const makeBtn = (rating, emoji, title) => {
    const btn = document.createElement('button');
    btn.textContent = emoji;
    btn.title = title;
    btn.dataset.rating = rating;
    btn.style.cssText =
      'background:none;border:1px solid var(--border-color,#ddd);border-radius:4px;' +
      'padding:2px 8px;cursor:pointer;font-size:15px;transition:background .15s,border-color .15s';
    btn.addEventListener('click', () => {
      const already = btn.classList.contains('fb-active');
      // Reset both buttons
      wrap.querySelectorAll('button').forEach(b => {
        b.classList.remove('fb-active');
        b.style.background = 'none';
        b.style.borderColor = 'var(--border-color,#ddd)';
      });
      if (!already) {
        btn.classList.add('fb-active');
        btn.style.background = rating === 'up' ? '#dcfce7' : '#fee2e2';
        btn.style.borderColor = rating === 'up' ? '#86efac' : '#fca5a5';
        fetch('/api/feedback', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content_type: contentType, content_id: String(contentId), rating }),
        }).catch(() => {});
      }
    });
    return btn;
  };

  wrap.appendChild(label);
  wrap.appendChild(makeBtn('up',   '👍', 'Helpful'));
  wrap.appendChild(makeBtn('down', '👎', 'Not helpful'));
  container.appendChild(wrap);
}

// Auto-dismiss flash messages
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.flash').forEach(el => {
    setTimeout(() => el.style.opacity = '0', 4000);
    setTimeout(() => el.remove(), 4600);
  });
});
