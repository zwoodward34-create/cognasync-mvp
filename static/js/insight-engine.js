// CognaSync Insight Engine
// Every insight carries its evidence, limitations, and audit trail.
// Confidence degrades automatically when context is compromised.

function _daysBetween(dateA, dateB) {
  return (new Date(dateB) - new Date(dateA)) / 86400000;
}

function _calculateGaps(dates) {
  if (!dates || dates.length < 2) return [0];
  const gaps = [];
  for (let i = 1; i < dates.length; i++) {
    gaps.push((new Date(dates[i]) - new Date(dates[i - 1])) / 3600000);
  }
  return gaps;
}

class Insight {
  constructor(pattern, evidence) {
    this.pattern = pattern;
    this.evidence = {
      collectedBy: 'patient_app',
      dataWindow: {
        startDate: evidence.startDate,
        endDate: evidence.endDate,
        daysOfData: evidence.daysOfData,
      },
      dataPoints: {
        count: evidence.count,
        frequency: evidence.frequency,
        gaps: evidence.gaps,
      },
      contextChanges: evidence.contextChanges || [],
      statistics: {
        rSquared: evidence.rSquared,
        pValue: evidence.pValue,
        confidencePercentile: evidence.confidencePercentile,
        correlationCoefficient: evidence.correlationCoefficient,
      },
      dataPointsIncluded: evidence.dataPointsIncluded || [],
    };
  }

  calculateAdjustedConfidence() {
    let confidence = this.evidence.statistics.confidencePercentile;

    // Recent medication initiation penalty (< 28 days: ÷1.5)
    const now = new Date();
    for (const change of this.evidence.contextChanges) {
      const daysSince = _daysBetween(change.date, now);
      if (change.relevance.includes('CRITICAL') && daysSince < 28) {
        confidence = confidence / 1.5;
      } else if (change.relevance.includes('CONFOUNDING')) {
        confidence = confidence / 1.3;
      }
    }

    // Large gap penalty (> 48h: ÷1.2)
    const maxGap = Math.max(...this.evidence.dataPoints.gaps);
    if (maxGap > 48) confidence = confidence / 1.2;

    // Sparse data: scale linearly up to 21 observations (CLAUDE.md statistical minimum)
    const n = this.evidence.dataPoints.count;
    if (n < 21) {
      confidence = confidence * (n / 21);
    }

    return Math.max(0, Math.floor(confidence));
  }

  generateAuditTrail() {
    return {
      generatedAt: new Date().toISOString(),
      generatedBy: 'CognaSync Insight Engine v1.0',
      analysisMethod: 'Pearson linear regression + threshold detection',
      reviewedBy: null,
      reviewedAt: null,
      clinicalRelevance: null,
    };
  }

  generateLimitations() {
    const lims = [];
    const n = this.evidence.dataPoints.count;
    const r2 = this.evidence.statistics.rSquared;
    const maxGap = Math.max(...this.evidence.dataPoints.gaps);

    if (n < 21)
      lims.push(`Pattern based on ${n} observations; confidence stabilizes above 21 data points.`);

    if (maxGap > 48)
      lims.push(`Data gap of ${Math.round(maxGap)} hours detected — trend may not reflect the full period.`);

    for (const c of this.evidence.contextChanges) {
      const daysSince = _daysBetween(c.date, new Date());
      if (c.relevance.includes('CRITICAL') && daysSince < 28) {
        lims.push(`${c.change} occurred ${Math.round(daysSince)} days ago — medication response analysis is unreliable until 4 weeks post-initiation.`);
      } else if (c.relevance.includes('CONFOUNDING')) {
        lims.push(`"${c.change}" may confound the observed pattern.`);
      }
    }

    if (r2 < 0.5)
      lims.push(`R²=${r2} — the regression explains ${Math.round(r2 * 100)}% of variance; additional factors likely contribute.`);

    lims.push('Correlation does not imply causation; review raw data points before acting on this pattern.');
    return lims;
  }

  flagContextProblems() {
    const warnings = [];
    const now = new Date();
    for (const c of this.evidence.contextChanges) {
      const daysSince = _daysBetween(c.date, now);
      if (c.relevance.includes('CRITICAL') && daysSince < 28) {
        const clearDate = new Date(new Date(c.date).getTime() + 28 * 86400000);
        warnings.push(
          `Recent medication change (${c.change}) — response analysis unreliable until ` +
          clearDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + '.'
        );
      }
    }
    return warnings;
  }

  toProviderDisplay() {
    const adjusted = this.calculateAdjustedConfidence();
    return {
      pattern: this.pattern,
      confidence: adjusted,
      rawConfidence: this.evidence.statistics.confidencePercentile,
      evidence: this.evidence,
      limitations: this.generateLimitations(),
      auditTrail: this.generateAuditTrail(),
      contextProblems: this.flagContextProblems(),
    };
  }

  toPatientDisplay() {
    const adjusted = this.calculateAdjustedConfidence();
    return {
      pattern: this.pattern,
      confidence: adjusted,
      limitations: this.generateLimitations().slice(0, 2),
      contextProblems: this.flagContextProblems(),
    };
  }
}


// ── Factory ───────────────────────────────────────────────────────────────────

function buildInsightFromMetric(trendsData, metricKey, patternText) {
  const metric = trendsData[metricKey];
  if (!metric) return null;

  const scores = metric.daily_scores || metric.daily_hours || [];
  const dates  = metric.dates || [];
  if (!scores.length) return null;

  const gaps = _calculateGaps(dates);
  const n    = scores.length;
  const freq = trendsData.checkin_count / trendsData.period_days;

  // Context changes: medications started within the analysis window
  const windowStart = dates[0] ? new Date(dates[0]) : null;
  const windowEnd   = dates[dates.length - 1] ? new Date(dates[dates.length - 1]) : null;
  const contextChanges = [];

  for (const med of (trendsData.current_medications || [])) {
    if (!med.start_date) continue;
    const medStart = new Date(med.start_date);
    if (windowStart && windowEnd && medStart >= windowStart && medStart <= windowEnd) {
      contextChanges.push({
        date: med.start_date,
        change: `Started ${med.name}${med.dose ? ' ' + med.dose : ''}`,
        relevance: 'CRITICAL - invalidates medication response analysis until 4 weeks post-initiation',
      });
    }
  }

  const rawConf   = Math.round((1 - metric.p_value) * 100);
  const corrCoeff = Math.sqrt(metric.r_squared) * (metric.slope >= 0 ? 1 : -1);

  return new Insight(patternText, {
    startDate: dates[0] || '',
    endDate:   dates[dates.length - 1] || '',
    daysOfData: trendsData.period_days,
    count: n,
    frequency: `${freq.toFixed(1)} check-ins/day`,
    gaps,
    contextChanges,
    rSquared: metric.r_squared,
    pValue: metric.p_value,
    confidencePercentile: rawConf,
    correlationCoefficient: Math.round(corrCoeff * 100) / 100,
    dataPointsIncluded: scores.map((v, i) => ({
      date: dates[i] || `Day ${i + 1}`,
      value: v,
      variable: metricKey,
    })),
  });
}


// ── Provider rendering ────────────────────────────────────────────────────────

function renderProviderInsights(trendsData, containerId, threshold = 80) {
  const CONFIDENCE_THRESHOLD = threshold;
  const container = document.getElementById(containerId);
  if (!container) return;

  const candidates = [
    { key: 'mood',   dir: 'increasing', text: 'Mood trending upward.' },
    { key: 'mood',   dir: 'decreasing', text: 'Mood trending downward.' },
    { key: 'stress', dir: 'increasing', text: 'Stress trending upward.' },
    { key: 'stress', dir: 'decreasing', text: 'Stress declining.' },
    { key: 'sleep',  dir: 'increasing', text: 'Sleep duration trending upward.' },
    { key: 'sleep',  dir: 'decreasing', text: 'Sleep duration declining.' },
    { key: 'energy', dir: 'increasing', text: 'Energy trending upward.' },
    { key: 'energy', dir: 'decreasing', text: 'Energy declining.' },
  ];

  const displays = [];
  for (const c of candidates) {
    const metric = trendsData[c.key];
    if (!metric || metric.trend !== c.dir) continue;
    const insight = buildInsightFromMetric(trendsData, c.key, c.text);
    if (!insight) continue;
    displays.push(insight.toProviderDisplay());
  }

  const qualified = displays.filter(d => d.confidence >= CONFIDENCE_THRESHOLD);

  if (!qualified.length) {
    const best = displays.length ? Math.max(...displays.map(d => d.confidence)) : 0;
    container.innerHTML = best > 0
      ? `<p style="font-size:13px;color:var(--text-muted);padding:8px 0;">
           Highest adjusted confidence in this period is ${best}% — below the ${CONFIDENCE_THRESHOLD}% threshold required to surface insights.
           Confidence penalties from recent medication changes, data gaps, or sparse observations may be reducing the score.
         </p>`
      : '<p style="font-size:13px;color:var(--text-muted);padding:8px 0;">No statistically significant trends detected for this period.</p>';
    return;
  }

  container.innerHTML = qualified.map(d => {
    const confColor = d.confidence >= 80 ? '#1a5c1a' : d.confidence >= 65 ? '#7a5800' : '#8B1A1A';
    const confBg    = d.confidence >= 80 ? '#f0faf0' : d.confidence >= 65 ? '#fffbf0' : '#fff5f5';

    const problemsHtml = d.contextProblems.map(w =>
      `<div style="background:#fff8e1;border:1px solid #f0c040;padding:8px 12px;font-size:12px;margin-bottom:6px;border-radius:2px;">⚠ ${w}</div>`
    ).join('');

    const limitsHtml = d.limitations.map(l => `<li style="margin-bottom:4px;">${l}</li>`).join('');

    const at = d.auditTrail;
    const dpSample = (d.evidence.dataPointsIncluded || []).slice(0, 5)
      .map(p => `<span style="font-size:10px;border:1px solid var(--border-light);padding:1px 5px;margin:1px;display:inline-block;">${p.date}: ${p.value}</span>`).join('');
    const dpMore = d.evidence.dataPointsIncluded.length > 5
      ? `<span style="font-size:10px;color:var(--text-muted);"> +${d.evidence.dataPointsIncluded.length - 5} more</span>` : '';

    return `
      <div style="border:1px solid var(--border-light);padding:16px;margin-bottom:12px;background:var(--surface);">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;">
          <div style="font-size:14px;font-weight:600;">${d.pattern}</div>
          <div style="text-align:right;min-width:110px;">
            <div style="font-size:20px;font-weight:700;color:${confColor};background:${confBg};padding:4px 10px;border-radius:2px;">${d.confidence}%</div>
            <div style="font-size:10px;color:var(--text-muted);margin-top:2px;">adjusted · raw ${d.rawConfidence}%</div>
          </div>
        </div>

        <div style="display:flex;gap:16px;font-size:11px;color:var(--text-muted);margin-bottom:10px;flex-wrap:wrap;">
          <span>${d.evidence.dataPoints.count} observations</span>
          <span>${d.evidence.dataPoints.frequency}</span>
          <span>R²=${d.evidence.statistics.rSquared}</span>
          <span>p=${d.evidence.statistics.pValue}</span>
          <span>${d.evidence.dataWindow.startDate} – ${d.evidence.dataWindow.endDate}</span>
        </div>

        ${problemsHtml}

        <details style="margin-top:8px;">
          <summary style="font-size:12px;cursor:pointer;color:var(--text-muted);">Limitations (${d.limitations.length})</summary>
          <ul style="margin:8px 0 0 0;padding-left:18px;font-size:12px;color:var(--text-muted);">${limitsHtml}</ul>
        </details>

        <details style="margin-top:6px;">
          <summary style="font-size:12px;cursor:pointer;color:var(--text-muted);">Data points (${d.evidence.dataPointsIncluded.length}) · Audit trail</summary>
          <div style="margin-top:8px;">
            <div style="margin-bottom:6px;">${dpSample}${dpMore}</div>
            <div style="font-size:11px;color:var(--text-muted);border-top:1px solid var(--border-light);padding-top:6px;margin-top:6px;">
              Generated ${new Date(at.generatedAt).toLocaleString()} · ${at.analysisMethod}
              <span style="margin-left:10px;border:1px solid var(--border-light);padding:1px 5px;font-size:10px;">
                ${at.clinicalRelevance ? 'Reviewed' : 'Pending review'}
              </span>
            </div>
          </div>
        </details>
      </div>`;
  }).join('');
}
