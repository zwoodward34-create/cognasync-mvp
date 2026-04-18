// Provider dashboard utilities — generateSummary is inlined in the template
// This file exists for shared provider logic if needed.

function sortTable(col) {
  const table = document.querySelector('.provider-table');
  if (!table) return;
  const rows = Array.from(table.querySelectorAll('tbody tr'));
  const idx = col;
  rows.sort((a, b) => {
    const ta = a.cells[idx]?.textContent.trim() || '';
    const tb = b.cells[idx]?.textContent.trim() || '';
    return ta.localeCompare(tb);
  });
  const tbody = table.querySelector('tbody');
  rows.forEach(r => tbody.appendChild(r));
}
