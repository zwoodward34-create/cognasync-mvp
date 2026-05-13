// CognaSync Hypothesis Tester
// Tests user-stated hypotheses against all three directions simultaneously.
// Surfaces unexpected patterns in unexamined variable pairs once per week.

const VAR_LABELS = {
  mood:              'Mood',
  stress:            'Stress',
  sleep:             'Sleep',
  energy:            'Energy',
  focus:             'Focus',
  irritability:      'Irritability',
  motivation:        'Motivation',
  perceived_stress:  'Perceived Stress',
  alcohol:           'Alcohol',
  exercise:          'Exercise',
  sunlight:          'Sunlight',
  screen_time:       'Screen Time',
  social_quality:    'Social Quality',
  workload_friction: 'Workload Friction',
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
    const lastChecked = localStorage.getItem('hyp_unexpected_checked');
    const now = Date.now();
    if (lastChecked && now - parseInt(lastChecked, 10) < 7 * 24 * 3600 * 1000) {
      const cached = localStorage.getItem('hyp_unexpected_result');
      if (cached) {
        try {
          const parsed = JSON.parse(cached);
          if (Array.isArray(parsed) && parsed.length > 0 && parsed[0].var_a) return parsed;
        } catch (_) {}
      }
    }

    const result = await apiGet('/api/hypotheses/unexpected?days=' + days);
    const patterns = result.patterns || [];
    localStorage.setItem('hyp_unexpected_checked', String(now));
    localStorage.setItem('hyp_unexpected_result', JSON.stringify(patterns));
    return patterns;
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

  renderDiscovery(containerId, patterns) {
    const el = document.getElementById(containerId);
    if (!el) return;

    if (!patterns || !patterns.length) {
      el.innerHTML = `
        <div style="text-align:center;padding:24px 16px;color:var(--text-muted);font-size:13px;
                    border:1px dashed var(--border-light);">
          Not enough data yet. Keep logging — patterns surface after 7+ check-ins.
        </div>`;
      return;
    }

    const pLabels = { '0.001': 'p&lt;0.001', '0.01': 'p&lt;0.01', '0.05': 'p&lt;0.05', '0.10': 'p&lt;0.10', '0.20': 'p&lt;0.20' };
    const strengthMeta = {
      strong:   { label: 'Strong Signal',      border: '2px solid #000', barColor: '#000' },
      moderate: { label: 'Moderate Pattern',   border: '1px solid #555', barColor: '#444' },
      notable:  { label: 'Notable Trend',      border: '1px solid var(--border-light)', barColor: '#888' },
    };

    el.innerHTML = patterns.map((p, i) => {
      const meta   = strengthMeta[p.strength] || strengthMeta.notable;
      const barPct = Math.round(Math.abs(p.r) * 100);
      const dir    = p.r > 0 ? '↑' : '↓';
      const dirTxt = p.r > 0 ? 'positive' : 'negative';
      const pDisp  = pLabels[p.p_value] || `p=${p.p_value}`;
      const newBadge = p.is_new
        ? `<span style="font-size:9px;background:#000;color:#fff;padding:2px 7px;letter-spacing:.08em;margin-left:6px;">NEW</span>`
        : '';

      return `
        <div style="${meta.border};padding:16px;${i > 0 ? 'margin-top:10px;' : ''}background:var(--surface);">
          <div style="display:flex;align-items:center;margin-bottom:10px;">
            <span style="font-size:10px;text-transform:uppercase;letter-spacing:.07em;font-weight:700;color:${meta.barColor};">
              ${meta.label}
            </span>
            ${newBadge}
            <span style="margin-left:auto;font-size:11px;color:var(--text-muted);">
              ${p.n} days &middot; r=${p.r} &middot; ${pDisp}
            </span>
          </div>
          <div style="font-size:14px;font-weight:600;line-height:1.45;margin-bottom:10px;">${p.message}</div>
          <div style="font-size:12px;color:var(--text-muted);margin-bottom:10px;">
            <strong style="color:var(--text);">${VAR_LABELS[p.var_a] || p.var_a}</strong>
            &nbsp;${dir} ${dirTxt} correlation with&nbsp;
            <strong style="color:var(--text);">${VAR_LABELS[p.var_b] || p.var_b}</strong>
          </div>
          <div style="background:var(--surface-alt);height:5px;margin-bottom:12px;overflow:hidden;">
            <div style="width:${barPct}%;height:100%;background:${meta.barColor};"></div>
          </div>
          <button class="btn btn-primary btn-sm"
                  onclick="prefillHypothesis('${p.var_a}','${p.var_b}','${p.r > 0 ? 'positive' : 'negative'}')">
            Investigate &rarr;
          </button>
        </div>`;
    }).join('');
  }

  renderUnexpected(containerId, pattern) {
    // Legacy shim: single pattern → wrap in array and delegate
    this.renderDiscovery(containerId, pattern ? [pattern] : []);
  }
}
