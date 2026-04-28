// CognaSync Hypothesis Tester
// Tests user-stated hypotheses against all three directions simultaneously.
// Surfaces unexpected patterns in unexamined variable pairs once per week.

const VAR_LABELS = {
  mood: 'Mood',
  stress: 'Stress',
  sleep: 'Sleep',
  energy: 'Energy',
  focus: 'Focus',
};

const DIR_LABELS = {
  positive: 'helps / increases',
  negative: 'hurts / decreases',
  null: 'has no effect on',
};

class HypothesisTester {
  constructor() {
    this.history = [];
  }

  async testUserHypothesis(varA, varB, userDirection, days = 60) {
    const primaryHypothesis = {
      statement: `${VAR_LABELS[varA]} ${DIR_LABELS[userDirection]} ${VAR_LABELS[varB]}`,
      direction: userDirection,
    };

    // API tests all three directions simultaneously and returns ranked results
    const result = await apiPost('/api/hypotheses/test', {
      variable_a: varA,
      variable_b: varB,
      user_direction: userDirection,
      days,
    });

    // Attach the original user hypothesis for display
    result.userHypothesis = primaryHypothesis.statement;
    return result;
  }

  async surfaceUnexpectedPatterns(days = 30) {
    // Once per week: show the strongest pattern the user hasn't examined
    const lastChecked = localStorage.getItem('hyp_unexpected_checked');
    const now = Date.now();
    if (lastChecked && now - parseInt(lastChecked, 10) < 7 * 24 * 3600 * 1000) {
      const cached = localStorage.getItem('hyp_unexpected_result');
      return cached ? JSON.parse(cached) : null;
    }

    const result = await apiGet('/api/hypotheses/unexpected?days=' + days);
    localStorage.setItem('hyp_unexpected_checked', String(now));
    localStorage.setItem('hyp_unexpected_result', JSON.stringify(result.pattern || null));
    return result.pattern || null;
  }

  async loadHistory() {
    const result = await apiGet('/api/hypotheses');
    this.history = result.history || [];
    return this.history;
  }

  // ── Rendering ───────────────────────────────────────────────────────────────

  renderResult(containerId, varA, varB, userDirection, result) {
    const el = document.getElementById(containerId);
    if (!el) return;

    const ranked = result.ranked || [];
    const winner = result.winner || {};
    const isDivergence = result.divergence;

    const dirIcon = { positive: '↑', negative: '↓', null: '⟷' };
    const dirColor = { positive: '#1a5c1a', negative: '#8B1A1A', null: '#555' };

    const rankedHtml = ranked.map(r => {
      const isWinner = r.rank === 1;
      const icon = dirIcon[r.direction] || '';
      const col = dirColor[r.direction] || '#333';
      return `
        <div style="display:flex;align-items:center;gap:10px;padding:8px 0;
                    border-bottom:1px solid var(--border-light);
                    ${isWinner ? 'font-weight:600;' : 'opacity:.7;'}">
          <span style="font-size:11px;border:1px solid currentColor;padding:1px 5px;
                       color:${col};min-width:60px;text-align:center;">
            ${isWinner ? '▶ WINNER' : `#${r.rank}`}
          </span>
          <span style="color:${col};font-size:13px;">${icon} ${r.statement}</span>
          <span style="margin-left:auto;font-size:11px;color:var(--text-muted);">
            evidence: ${r.evidence.toFixed(3)}
          </span>
        </div>`;
    }).join('');

    const divergenceHtml = isDivergence ? `
      <div style="background:#fff8e1;border:1px solid #f0c040;padding:12px 14px;margin-top:12px;font-size:13px;">
        <div style="font-weight:600;margin-bottom:4px;">⚠ Your hypothesis didn't match the data</div>
        <div>${result.divergence_message}</div>
      </div>` : `
      <div style="background:#f0faf0;border:1px solid #90c890;padding:10px 14px;margin-top:12px;font-size:13px;color:#1a5c1a;">
        ✓ Data supports your hypothesis.
      </div>`;

    el.innerHTML = `
      <div style="border:1px solid var(--border-light);padding:16px;margin-top:12px;background:var(--surface);">
        <div style="font-size:12px;color:var(--text-muted);margin-bottom:10px;">
          Testing: <strong>${VAR_LABELS[varA]}</strong> → <strong>${VAR_LABELS[varB]}</strong>
          · ${result.n} matched check-ins · r=${result.r} · p=${result.p_value}
        </div>
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;
                    color:var(--text-muted);margin-bottom:6px;">Three directions tested</div>
        ${rankedHtml}
        ${divergenceHtml}
      </div>`;
  }

  renderHistory(containerId) {
    const el = document.getElementById(containerId);
    if (!el || !this.history.length) return;

    el.innerHTML = `
      <div style="margin-top:20px;">
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;
                    color:var(--text-muted);margin-bottom:8px;">Past Hypothesis Tests</div>
        ${this.history.map(h => {
          const divBadge = h.divergence
            ? `<span style="font-size:10px;border:1px solid #f0c040;color:#7a5800;padding:1px 6px;margin-left:6px;">diverged</span>`
            : `<span style="font-size:10px;border:1px solid #90c890;color:#1a5c1a;padding:1px 6px;margin-left:6px;">confirmed</span>`;
          return `
            <div style="display:flex;align-items:center;gap:8px;padding:7px 0;
                        border-bottom:1px solid var(--border-light);font-size:12px;">
              <span style="color:var(--text-muted);min-width:70px;">${h.created_at.slice(0,10)}</span>
              <span>${VAR_LABELS[h.variable_a] || h.variable_a}
                    <span style="color:var(--text-muted);">${DIR_LABELS[h.user_direction] || h.user_direction}</span>
                    ${VAR_LABELS[h.variable_b] || h.variable_b}</span>
              <span style="margin-left:auto;color:var(--text-muted);">
                winner: ${h.result_direction}${divBadge}
              </span>
            </div>`;
        }).join('')}
      </div>`;
  }

  renderUnexpected(containerId, pattern) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!pattern) { el.innerHTML = ''; return; }

    const dir = pattern.r > 0 ? '↑ positive' : '↓ negative';
    const dirColor = pattern.r > 0 ? '#1a5c1a' : '#8B1A1A';

    el.innerHTML = `
      <div style="border:1px solid var(--border);padding:16px;margin-bottom:20px;background:var(--surface);">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
          <span style="font-size:10px;text-transform:uppercase;letter-spacing:.08em;
                       border:1px solid var(--border);padding:2px 7px;color:var(--text-muted);">
            Weekly Discovery
          </span>
          <span style="font-size:10px;color:var(--text-muted);">${pattern.n} check-ins · p=${pattern.p_value}</span>
        </div>
        <div style="font-size:14px;font-weight:600;margin-bottom:6px;">${pattern.message}</div>
        <div style="display:flex;align-items:center;gap:10px;font-size:12px;">
          <span>${VAR_LABELS[pattern.var_a] || pattern.var_a}</span>
          <span style="color:${dirColor};">⟶ ${dir} correlation (r=${pattern.r})</span>
          <span>${VAR_LABELS[pattern.var_b] || pattern.var_b}</span>
        </div>
        <div style="margin-top:12px;display:flex;gap:8px;">
          <button class="btn btn-primary btn-sm"
                  onclick="prefillHypothesis('${pattern.var_a}', '${pattern.var_b}', '${pattern.r > 0 ? 'positive' : 'negative'}')">
            Investigate
          </button>
          <button class="btn btn-ghost btn-sm" onclick="dismissUnexpected()">Dismiss</button>
        </div>
      </div>`;
  }
}
