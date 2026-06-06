# Patient Magic-Link Briefing Page — Design Spec

**Date:** 2026-06-06  
**Status:** Approved for implementation  
**Scope:** Data-only v1 (no AI summary). AI summary layer is v2.

---

## Problem

Patients have no visibility into their own trend data between appointments. Jonathan raised a "behavior change" concern — patients who can't see their numbers have no feedback loop to sustain engagement. Will's point: patients should know what's being tracked. The briefing page addresses both directly.

---

## What We're Building

A lightweight, no-login web page delivered weekly via SMS magic link. It shows the patient their own 14-day mood, sleep, stress, and energy trend data, plus the monitoring targets their care team has set. No app download, no account creation, no authentication beyond the link itself.

---

## Decisions Locked

| Decision | Choice | Rationale |
|---|---|---|
| AI summary on day one? | No — data-only | Mode B prompt designed for pre-appointment framing, not weekly briefing. AI layer is v2, pre-generated at send time (not page load). |
| Monitoring target display | Unified care team | "Your care team is tracking: X, Y, Z" — no per-provider attribution. Simpler, still satisfies transparency requirement. |
| Chart layout | Stacked full-width | Cleaner on 375px mobile. Four charts stacked vertically. |
| Token lifetime | 7 days | Patients should be able to revisit during the week (unlike 24–48h check-in/voice tokens). |
| Token re-access | Multi-use | `validate_sms_token_readonly` — validates without consuming. Records `used_at` on first open for analytics only; does not block subsequent access. |

---

## Files Touched

| File | Change type |
|---|---|
| `database.py` | 3 new functions |
| `app.py` | 1 new page route + 1 new scheduler endpoint |
| `templates/patient/briefing.html` | New file |
| `sms_tokens` table (Supabase) | Migration — add `'briefing'` to CHECK constraint |

No changes to `claude_api.py`, `static/css/style.css`, or any existing route.

---

## Required Database Migration

The `sms_tokens` table has a `CHECK (flow_type IN ('medication', 'short', 'full', 'voice'))` constraint. Inserting `flow_type='briefing'` without this migration will throw a constraint violation and silently skip all patients.

Apply via Supabase SQL Editor or `apply_migration` before deploying the scheduler:

```sql
-- Drop and recreate the flow_type check to include 'briefing'
ALTER TABLE sms_tokens
  DROP CONSTRAINT IF EXISTS sms_tokens_flow_type_check;

ALTER TABLE sms_tokens
  ADD CONSTRAINT sms_tokens_flow_type_check
  CHECK (flow_type IN ('medication', 'short', 'full', 'voice', 'briefing'));
```

This is a non-breaking change — existing rows are unaffected.

---

## `database.py` — New Functions

### `validate_sms_token_readonly(token: str) -> dict | None`

Validates a token from `sms_tokens` without consuming it.

Checks:
- Token exists
- `expires_at > now()`

Does NOT check or block on `used_at`. On first access (where `used_at IS NULL`), sets `used_at = now()` for analytics tracking. On subsequent accesses, still returns the record.

**Race condition note:** The read-then-conditional-write is non-atomic. Two concurrent opens (e.g., link preview bot + patient tap) can both see `used_at IS NULL` and both attempt the update. This is acceptable because `used_at` is analytics-only — a double-write is harmless. Implement the update with `.is_('used_at', 'null')` as a guard on the UPDATE clause (not in Python) to avoid the double-write without requiring a transaction:

```python
supabase_admin.table('sms_tokens') \
    .update({'used_at': now_iso}) \
    .eq('id', row['id']) \
    .is_('used_at', 'null') \   # guard: only update if not already set
    .execute()
# Do not check whether 0 rows were updated — that's a valid "already set" outcome
```

Returns `{patient_id, flow_type, metadata}` or `None` on invalid/expired.

```python
def validate_sms_token_readonly(token: str) -> dict | None:
    """
    Validate a briefing token without consuming it.

    Unlike validate_and_consume_token, this does not block access after
    first use. Sets used_at on first open for analytics only (with
    an IS NULL guard on the update to handle concurrent opens).

    Returns {patient_id, flow_type, metadata} or None.
    """
```

### `get_briefing_data(patient_id: str) -> dict`

Assembles everything the briefing template needs in one call.

Calls:
1. `get_trends_data(patient_id, days=14)` — existing function, returns daily arrays + averages
2. `get_active_focus_domains_for_patient(patient_id)` — existing function, returns list of domain keys
3. Profile name lookup: `SELECT full_name FROM profiles WHERE id = patient_id`

**Error handling:** If `get_trends_data` raises or returns `None`, `get_briefing_data` must catch the exception and return the zeroed-out structure with `checkin_count: 0` and all metric fields zeroed. The zeroed structure must use the correct field names per metric — specifically, sleep uses `daily_hours` (not `daily_scores`):

```python
# Zeroed fallback — note field name differences
{
  'mood':   {'average': None, 'trend': None, 'daily_scores': [], 'dates': []},
  'sleep':  {'average': None, 'trend': None, 'daily_hours': [],  'dates': []},  # daily_hours, not daily_scores
  'stress': {'average': None, 'trend': None, 'daily_scores': [], 'dates': []},
  'energy': {'average': None, 'trend': None, 'daily_scores': [], 'dates': []},
  'checkin_count': 0,
  # ... other fields
}
```

Do not propagate the exception to the route. If `get_active_focus_domains_for_patient` returns `[]`, `monitoring_targets` is `[]` — correct behavior, no special case needed.

**Trend string remapping:** `get_trends_data` returns trend values from `_trend_stats()` using the strings `'increasing'`, `'decreasing'`, `'stable'`, and `'insufficient_data'`. `get_briefing_data` must remap these before returning:

```python
_TREND_REMAP = {
    'increasing':        'improving',
    'decreasing':        'declining',
    'stable':            'stable',
    'insufficient_data': None,
}
# Apply: trend = _TREND_REMAP.get(raw_trend)
```

The template JavaScript tests for `'improving'` and `'declining'` when rendering trend arrows — passing unmapped strings will cause arrows to never render.

**`checkin_count` source:** Use `trends['checkin_count']` from the `get_trends_data` return value (equivalent to `checkins_this_period` — all three fields carry the same value, use `checkin_count`).

Applies `_BRIEFING_DOMAIN_LABELS` map to translate domain keys to plain language. Silently filters out `None`-mapped domains (specifically `suicidality` — must never appear on patient-facing pages). Any domain key not present in the map is also silently dropped.

Returns:

```python
{
    'patient_first_name': str,          # first name only from full_name split
    'period_days': 14,
    'date_range': {'start': ISO, 'end': ISO},
    'checkin_count': int,               # check-ins in window
    'mood': {
        'average': float | None,
        'trend': 'improving' | 'declining' | 'stable' | None,  # remapped from _trend_stats strings
        'daily_scores': [float | None, ...],   # 14 values, None = no check-in that day
        'dates': [ISO str, ...],
    },
    'sleep': {
        'average': float | None,
        'trend': 'improving' | 'declining' | 'stable' | None,
        'daily_hours': [float | None, ...],
        'dates': [ISO str, ...],
    },
    'stress': {
        'average': float | None,
        'trend': 'improving' | 'declining' | 'stable' | None,
        'daily_scores': [float | None, ...],
        'dates': [ISO str, ...],
    },
    'energy': {
        'average': float | None,
        'trend': 'improving' | 'declining' | 'stable' | None,
        'daily_scores': [float | None, ...],
        'dates': [ISO str, ...],
    },
    'monitoring_targets': [str, ...],   # plain-language labels, filtered
    'generated_at': ISO str,
}
```

The `_BRIEFING_DOMAIN_LABELS` map (module-level constant in `database.py`):

```python
_BRIEFING_DOMAIN_LABELS = {
    'mood':                'Mood patterns',
    'anxiety_stress':      'Stress and anxiety levels',
    'sleep':               'Sleep quality and duration',
    'energy_focus':        'Energy and focus',
    'medication_response': 'Medication response',
    'social_functioning':  'Social wellbeing',
    'irritability':        'Irritability patterns',
    'motivation':          'Motivation levels',
    'appetite_nutrition':  'Appetite and nutrition',
    'suicidality':         None,   # NEVER surface to patient
}
```

If a domain key is not in this map, it is also silently dropped (forward-compatible with new domain types).

### `get_all_patients_for_weekly_briefing() -> list`

Mirrors `get_all_patients_for_weekly_voice()` exactly, using `flow_type='briefing'` for the recency check.

```python
def get_all_patients_for_weekly_briefing() -> list:
    """
    Return all patients with a phone number who have not received a
    briefing SMS token in the past 7 days.

    Returns [{patient_id, phone}, ...]
    """
```

Queries:
1. `patient_profiles` where `phone_number IS NOT NULL AND phone_number != ''`
2. `sms_tokens` where `flow_type = 'briefing' AND created_at >= (now - 7 days)`
3. Returns patients not in the recent-send set

---

## `app.py` — New Blocks

### Route: `GET /patient/briefing/<token>`

```python
@app.route('/patient/briefing/<token>')
def patient_briefing_page(token):
    """Patient weekly briefing page. No login required — token is the auth."""
    tok = db.validate_sms_token_readonly(token)
    if not tok or tok['flow_type'] != 'briefing':
        return render_template('token_invalid.html',
            message='Briefing links are valid for one week. '
                    'Your provider will send a new one next week.'), 410

    data = db.get_briefing_data(tok['patient_id'])
    return render_template('patient/briefing.html', data=data)
```

### Scheduler: `POST /api/internal/trigger-briefing-sms`

Protected by `_validate_internal_secret()`. Same structure as `internal_trigger_voice_sms`.

**Route path:** `/api/internal/trigger-briefing-sms` — matches the existing pattern (voice is at `/api/internal/trigger-voice-sms`, checkin is at `/api/internal/trigger-checkin-sms`).

**SMS delivery:** Use `trigger_flow(flow_type='voice', to_phone=..., parameters={'voice_prompt': '', 'voice_link': briefing_url})`. The Twilio wrapper (`twilio_client.py`) exposes only `trigger_flow` for outbound sends — there is no `send_sms` method. The voice Studio flow delivers the link as a plain SMS, which is exactly the behavior needed. Do NOT use `flow_type='short'`; that flow is wired to the check-in webhook and will misroute any replies.

Logic:
1. Call `db.get_all_patients_for_weekly_briefing()`
2. For each patient:
   a. Call `db.create_sms_token(patient_id, flow_type='briefing', ttl_hours=168)`
   b. **If `token` is `None`:** `skipped += 1; continue` — do not attempt to send
   c. Build briefing URL: `f"{base_url}/patient/briefing/{token}"`
   d. Send SMS
   e. **If send returns falsy SID:** `skipped += 1` — else `triggered += 1`
3. Log counts, return `200 {'triggered': N, 'skipped': N}`

SMS body (constant, not personalized):
```
Your weekly CognaSync summary is ready — 2 weeks of your mood, sleep, and energy data. No login needed.
[briefing_link]
```

---

## `templates/patient/briefing.html` — New Template

Standalone file. Does NOT extend `layout.html`. Imports fonts (Google Fonts CDN) and `style.css` directly. No auth nav, no session context.

### Structure

```
<html>
  <head>
    Google Fonts (DM Serif Display, DM Sans, JetBrains Mono)
    tokens.css + style.css (via /static/)
    Chart.js @4.4.0 (CDN)
    <style> briefing-specific layout overrides </style>
  </head>
  <body>
    <script>const BRIEFING_DATA = {{ data | tojson | safe }};</script>

    <!-- Header -->
    CS wordmark + "CognaSync"
    "Hi [first_name]" (DM Serif Display, ~28px)
    "[Start date] – [End date]" (pencil gray, small)

    <!-- Stat strip: 2x2 grid -->
    [Avg Mood] [Avg Sleep]
    [Avg Stress] [Avg Energy]

    <!-- Charts: 4 stacked -->
    <section> Mood (14 days) — line chart, 120px height </section>
    <section> Sleep (14 days) — line chart, 120px height </section>
    <section> Stress (14 days) — line chart, 120px height </section>
    <section> Energy (14 days) — line chart, 120px height </section>

    <!-- Monitoring targets (conditional) -->
    IF monitoring_targets.length > 0:
      "What we're paying attention to"
      "Your care team asked us to focus on these areas:"
      <ul> [target labels] </ul>

    <!-- Footer -->
    "Generated from your check-ins · [date]"
    "Questions? Reach out to your care team."
  </body>
</html>
```

### Stat Cards

2×2 CSS grid, 8px gap. Each card:
- Label: metric name (small, pencil gray)
- Value: average formatted (`6.4` for /10 metrics, `6.8 hrs` for sleep)
- Unit: sub-label (`/10` or `hrs`)
- Trend: `▲` in green / `▼` in red / `–` in gray, based on `trend` field

If `average` is null (no check-ins), display `—` with muted sub-label "no data."

### Chart Configuration (per chart)

```javascript
{
  type: 'line',
  data: {
    labels: formattedDates,   // "Jun 1", "Jun 3" etc. — thinned every 3rd
    datasets: [{
      data: dailyScores,
      borderColor: '#0F6E56',
      backgroundColor: 'rgba(15, 110, 86, 0.10)',
      fill: true,
      tension: 0.3,
      pointRadius: 3,
      pointHoverRadius: 5,
      spanGaps: true,         // connect across null (no check-in) days
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: {
        grid: { display: false },
        ticks: { font: { size: 11 }, color: '#5F5E5A' }
      },
      y: {
        display: false,       // averages are in stat cards above
        min: 0,
        max: 10               // override to 12 for the sleep chart only (see below)
      }
    }
  }
}
```

**Sleep chart y-axis override:** The sleep chart uses `max: 12` instead of `max: 10` to accommodate hours > 10. Apply this as a per-chart override when instantiating the sleep chart:

```javascript
// Sleep chart only — override y.max
options.scales.y.max = 12;
```

The base config object should be constructed first (shared across all four charts), then the sleep chart instance mutates its own copy of `options.scales.y.max` before passing to `new Chart(...)`. Do not mutate the shared base object.
```

`spanGaps: true` ensures the line connects through days with no check-in rather than breaking.

### Empty State (< 3 check-ins in window)

**Trigger:** Checked client-side in JavaScript using `BRIEFING_DATA.checkin_count < 3`.

When true, replace the charts section (all four chart `<canvas>` elements and their wrapping sections) with a single muted message:

```
"Not enough check-in data to show trends yet.
 Log check-ins throughout the week to see your patterns here."
```

Implementation: render all four chart sections as normal HTML, but run the check before `new Chart(...)` — if `BRIEFING_DATA.checkin_count < 3`, hide the chart sections and show the empty state div instead. Do not skip rendering the `<canvas>` elements server-side; this keeps the template logic simple and puts the condition in JS where `BRIEFING_DATA` lives.

Stat cards still render with whatever averages exist (or `—`). The empty state applies to charts only.

### Monitoring Targets Section

Conditionally rendered. Only if `data.monitoring_targets.length > 0`.

```html
<section class="briefing-targets">
  <h2>What we're paying attention to</h2>
  <p>Your care team asked us to focus on these areas in your check-ins:</p>
  <ul>
    {% for label in data.monitoring_targets %}
    <li>{{ label }}</li>
    {% endfor %}
  </ul>
</section>
```

No clinical framing. No provider names. No explanation of thresholds or scoring. Plain list.

---

## Token Flow (end-to-end)

```
Weekly cron fires → POST /api/internal/trigger-briefing-sms
  → get_all_patients_for_weekly_briefing()
  → create_sms_token(flow_type='briefing', ttl_hours=168)
  → Twilio SMS with link /patient/briefing/{token}

Patient opens link → GET /patient/briefing/{token}
  → validate_sms_token_readonly(token)
    → if used_at IS NULL: set used_at = now()  [analytics]
    → return record regardless
  → get_briefing_data(patient_id)
  → render briefing.html

Patient opens link again (same week) → same flow, still works
Link expires after 7 days → 410 with token_invalid.html
```

---

## What This Is Not

- Not a summary page (no narrative AI text in v1)
- Not an appointment prep tool (Mode B framing is wrong for this surface)
- Not a login prompt (no link to the authenticated app)
- Not a clinical document (no scores, no derived metrics like Stability Score or Crash Risk)

---

## v2 AI Layer (design note, not in scope)

When the AI summary is added, it should be pre-generated at SMS send time — not on page load. The scheduler generates the summary, stores it in `sms_tokens.metadata['summary']`, and the route reads it from the token. Zero page load latency. Requires a new Mode-B-like prompt variant specific to the weekly briefing context (not pre-appointment framing).
