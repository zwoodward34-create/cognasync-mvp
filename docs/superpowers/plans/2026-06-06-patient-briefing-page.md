# Patient Magic-Link Briefing Page — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a no-login weekly briefing page that patients reach via SMS magic link, showing 14 days of mood/sleep/stress/energy trend data and their active monitoring targets.

**Architecture:** Token-gated route reads patient trend data assembled by a new `get_briefing_data()` database function, renders a standalone Jinja2 template with Chart.js sparklines. A new scheduler endpoint sends weekly SMS links using the existing `create_sms_token` + `trigger_flow('voice')` pattern. No authentication layer — the signed, expiring token is the auth.

**Tech Stack:** Flask, Supabase Python client, Jinja2, Chart.js 4.4.0 (CDN), Twilio Studio (voice flow reused for SMS delivery).

**Note on testing:** This project has no test suite (`CLAUDE.md`: "There is no test suite"). Each task uses manual verification steps — `python -c` smoke tests, `curl` commands, and browser checks.

---

## Chunk 1: Database Layer

---

### Task 1: Apply Supabase Migration

`sms_tokens` has a `CHECK (flow_type IN ('medication', 'short', 'full', 'voice'))` constraint. Inserting `flow_type='briefing'` without this migration throws a constraint violation and silently skips every patient.

**Files:**
- Apply via Supabase dashboard SQL Editor (no migration file in this project — schema changes go directly to Supabase)

- [ ] **Step 1: Apply migration via Supabase MCP or SQL Editor**

```sql
ALTER TABLE sms_tokens
  DROP CONSTRAINT IF EXISTS sms_tokens_flow_type_check;

ALTER TABLE sms_tokens
  ADD CONSTRAINT sms_tokens_flow_type_check
  CHECK (flow_type IN ('medication', 'short', 'full', 'voice', 'briefing'));
```

- [ ] **Step 2: Verify constraint updated**

```sql
SELECT conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conname = 'sms_tokens_flow_type_check';
```

Expected: one row showing `flow_type IN ('medication', 'short', 'full', 'voice', 'briefing')`.

- [ ] **Step 3: Verify existing rows unaffected**

```sql
SELECT DISTINCT flow_type FROM sms_tokens LIMIT 20;
```

Expected: existing values only (`medication`, `short`, `full`, `voice` — no errors).

---

### Task 2: Add `validate_sms_token_readonly` to `database.py`

Read-only token validation for multi-access briefing links. Does not block subsequent opens; records `used_at` on first open only (analytics).

**Files:**
- Modify: `database.py` — add after `validate_and_consume_token` (~line 6605)

- [ ] **Step 1: Add function to `database.py`**

Insert immediately after the closing of `validate_and_consume_token` (search for the function by name to find the insertion point):

```python
def validate_sms_token_readonly(token: str) -> dict | None:
    """
    Validate a briefing token without consuming it.

    Unlike validate_and_consume_token, this does not block access after
    first use. Records used_at on first open for analytics (with an IS NULL
    guard on the UPDATE to handle concurrent opens harmlessly).

    Returns {patient_id, flow_type, metadata} or None on invalid/expired.
    """
    from datetime import timezone as _tz

    if not token:
        return None

    try:
        now_iso = datetime.now(_tz.utc).isoformat()

        result = supabase_admin.table('sms_tokens') \
            .select('id, patient_id, flow_type, metadata, expires_at') \
            .eq('token', token) \
            .execute()

        if not result.data:
            print(f'[db] validate_token_readonly: not found token={token!r}')
            return None

        row = result.data[0]

        if row['expires_at'] < now_iso:
            print(f'[db] validate_token_readonly: expired token={token!r}')
            return None

        # Record first open for analytics. IS NULL guard prevents double-write
        # from concurrent opens (e.g., link preview + actual tap). A 0-row update
        # is an acceptable "already recorded" outcome — do not check the result.
        supabase_admin.table('sms_tokens') \
            .update({'used_at': now_iso}) \
            .eq('id', row['id']) \
            .is_('used_at', 'null') \
            .execute()

        return {
            'patient_id': row['patient_id'],
            'flow_type':  row['flow_type'],
            'metadata':   row['metadata'] or {},
        }

    except Exception as e:
        print(f'[db] validate_sms_token_readonly error: {e}')
        return None
```

- [ ] **Step 2: Smoke-test the function**

First create a valid briefing token in the DB (use the Flask shell or a quick script):

```bash
cd /path/to/cognasync-mvp
python - <<'EOF'
from database import db
# Create a test token for an existing patient — replace PATIENT_ID
import os; from database import create_sms_token
token = create_sms_token('PATIENT_ID', 'briefing', ttl_hours=1)
print(f"token={token!r}")
EOF
```

Then test validate:

```bash
python - <<'EOF'
from database import validate_sms_token_readonly
result = validate_sms_token_readonly('TOKEN_FROM_ABOVE')
print(result)  # expected: {patient_id, flow_type, metadata}
result2 = validate_sms_token_readonly('TOKEN_FROM_ABOVE')
print(result2)  # expected: same dict — confirms multi-use
print(validate_sms_token_readonly('bad-token'))  # expected: None
EOF
```

- [ ] **Step 3: Commit**

```bash
git add database.py
git commit -m "feat: add validate_sms_token_readonly for multi-use briefing tokens"
```

---

### Task 3: Add constants and `get_briefing_data` to `database.py`

Assembles the full data dict the briefing template needs in one call. Applies domain label translation and trend string remapping.

**Files:**
- Modify: `database.py` — insert both the constants and `get_briefing_data` as one contiguous block immediately after `get_active_focus_domains_for_patient` closes (~line 7877), before the `_TREND_FIELD_MAP` block at line 7884. Search for `def get_active_focus_domains_for_patient` to locate the insertion point.

- [ ] **Step 1: Add module-level constants**

Find `_TREND_FIELD_MAP` in `database.py` and add the two new maps immediately before or after it:

```python
# ── Patient briefing — domain labels and trend remapping ─────────────────────

_BRIEFING_DOMAIN_LABELS: dict[str, str | None] = {
    'mood':                'Mood patterns',
    'anxiety_stress':      'Stress and anxiety levels',
    'sleep':               'Sleep quality and duration',
    'energy_focus':        'Energy and focus',
    'medication_response': 'Medication response',
    'social_functioning':  'Social wellbeing',
    'irritability':        'Irritability patterns',
    'motivation':          'Motivation levels',
    'appetite_nutrition':  'Appetite and nutrition',
    'suicidality':         None,   # NEVER surface to patient — silently dropped
    # Unknown keys are also dropped (forward-compatible with new domain types)
}

# Maps _trend_stats() output strings to patient-facing vocabulary.
# 'insufficient_data' → None so the template renders no trend arrow.
_BRIEFING_TREND_REMAP: dict[str, str | None] = {
    'increasing':        'improving',
    'decreasing':        'declining',
    'stable':            'stable',
    'insufficient_data': None,
}
```

- [ ] **Step 2: Add `get_briefing_data` function**

Add immediately after `get_active_focus_domains_for_patient`:

```python
def get_briefing_data(patient_id: str) -> dict:
    """
    Assemble everything the patient briefing template needs in one call.

    Calls get_trends_data (14-day window), get_active_focus_domains_for_patient,
    and a profile name lookup. Returns a fully resolved dict safe to pass
    directly to briefing.html.

    Never raises — returns a zeroed structure on any failure so the route
    can always render (even if data is empty).
    """
    from datetime import timezone as _tz

    def _empty() -> dict:
        """Zeroed fallback — returned when get_trends_data fails or is None."""
        start_iso = (date.today() - timedelta(days=14)).isoformat()
        end_iso   = date.today().isoformat()
        return {
            'patient_first_name': 'there',
            'period_days':  14,
            'date_range':   {'start': start_iso, 'end': end_iso},
            'checkin_count': 0,
            'mood':   {'average': None, 'trend': None, 'daily_scores': [], 'dates': []},
            'sleep':  {'average': None, 'trend': None, 'daily_hours':  [], 'dates': []},
            'stress': {'average': None, 'trend': None, 'daily_scores': [], 'dates': []},
            'energy': {'average': None, 'trend': None, 'daily_scores': [], 'dates': []},
            'monitoring_targets': [],
            'generated_at': datetime.now(_tz.utc).isoformat(),
        }

    def _remap(raw: str | None) -> str | None:
        return _BRIEFING_TREND_REMAP.get(raw) if raw else None

    # ── 1. Trend data ────────────────────────────────────────────
    try:
        trends = get_trends_data(patient_id, days=14)
    except Exception as e:
        print(f'[db] get_briefing_data: get_trends_data failed: {e}')
        trends = None

    if not trends:
        return _empty()

    # ── 2. Patient first name ────────────────────────────────────
    first_name = 'there'
    try:
        prof = supabase_admin.table('profiles') \
            .select('full_name') \
            .eq('id', str(patient_id)) \
            .limit(1) \
            .execute()
        if prof.data and prof.data[0].get('full_name'):
            full = (prof.data[0]['full_name'] or '').strip()
            first_name = full.split()[0] if full else 'there'
    except Exception as e:
        print(f'[db] get_briefing_data: profile lookup failed: {e}')

    # ── 3. Monitoring targets ────────────────────────────────────
    try:
        raw_domains = get_active_focus_domains_for_patient(patient_id) or []
    except Exception as e:
        print(f'[db] get_briefing_data: focus domains failed: {e}')
        raw_domains = []

    monitoring_targets = []
    for domain in raw_domains:
        label = _BRIEFING_DOMAIN_LABELS.get(domain)  # None for suicidality or unknown keys
        if label is not None:
            monitoring_targets.append(label)

    # ── 4. Assemble ──────────────────────────────────────────────
    return {
        'patient_first_name': first_name,
        'period_days':        14,
        'date_range':         trends.get('date_range', {}),
        'checkin_count':      trends.get('checkin_count', 0),
        'mood': {
            'average':      trends['mood'].get('average'),
            'trend':        _remap(trends['mood'].get('trend')),
            'daily_scores': trends['mood'].get('daily_scores', []),
            'dates':        trends['mood'].get('dates', []),
        },
        'sleep': {
            'average':     trends['sleep'].get('average'),
            'trend':       _remap(trends['sleep'].get('trend')),
            'daily_hours': trends['sleep'].get('daily_hours', []),   # note: daily_hours not daily_scores
            'dates':       trends['sleep'].get('dates', []),
        },
        'stress': {
            'average':      trends['stress'].get('average'),
            'trend':        _remap(trends['stress'].get('trend')),
            'daily_scores': trends['stress'].get('daily_scores', []),
            'dates':        trends['stress'].get('dates', []),
        },
        'energy': {
            'average':      trends['energy'].get('average'),
            'trend':        _remap(trends['energy'].get('trend')),
            'daily_scores': trends['energy'].get('daily_scores', []),
            'dates':        trends['energy'].get('dates', []),
        },
        'monitoring_targets': monitoring_targets,
        'generated_at':       datetime.now(_tz.utc).isoformat(),
    }
```

- [ ] **Step 3: Smoke-test `get_briefing_data`**

```bash
python - <<'EOF'
from database import get_briefing_data
result = get_briefing_data('PATIENT_ID')  # replace with a real patient ID
print("first_name:", result['patient_first_name'])
print("checkin_count:", result['checkin_count'])
print("mood avg:", result['mood']['average'])
print("mood trend:", result['mood']['trend'])   # expect: 'improving'|'declining'|'stable'|None
print("sleep daily_hours count:", len(result['sleep']['daily_hours']))
print("targets:", result['monitoring_targets'])
print("generated_at:", result['generated_at'])
# Verify all expected keys present:
for key in ['mood','sleep','stress','energy','monitoring_targets','date_range','checkin_count']:
    assert key in result, f"Missing key: {key}"
print("All keys present.")
EOF
```

- [ ] **Step 4: Commit**

```bash
git add database.py
git commit -m "feat: add _BRIEFING_DOMAIN_LABELS, _BRIEFING_TREND_REMAP, get_briefing_data"
```

---

### Task 4: Add `get_all_patients_for_weekly_briefing` to `database.py`

Returns patients with phones who haven't received a briefing token in the past 7 days. Exact mirror of `get_all_patients_for_weekly_voice`, differing only in `flow_type`.

**Files:**
- Modify: `database.py` — add immediately after `get_all_patients_for_weekly_voice` (~line 7935)

- [ ] **Step 1: Add function**

```python
def get_all_patients_for_weekly_briefing() -> list:
    """Return all patients with a phone number who have not received a
    briefing SMS token in the past 7 days.

    Mirrors get_all_patients_for_weekly_voice but uses flow_type='briefing'.

    Returns [{patient_id, phone}, ...]
    """
    from datetime import timezone as _tz, timedelta as _td

    cutoff = (datetime.now(_tz.utc) - _td(days=7)).isoformat()

    try:
        all_res = supabase_admin.table('patient_profiles') \
            .select('user_id, phone_number') \
            .neq('phone_number', None) \
            .neq('phone_number', '') \
            .execute()

        if not all_res.data:
            return []

        recent_res = supabase_admin.table('sms_tokens') \
            .select('patient_id') \
            .eq('flow_type', 'briefing') \
            .gte('created_at', cutoff) \
            .execute()
        already_sent = {r['patient_id'] for r in (recent_res.data or [])}

        return [
            {'patient_id': r['user_id'], 'phone': r['phone_number']}
            for r in all_res.data
            if r['user_id'] not in already_sent and r.get('phone_number')
        ]
    except Exception as e:
        print(f'[db] get_all_patients_for_weekly_briefing error: {e}')
        return []
```

- [ ] **Step 2: Smoke-test**

```bash
python - <<'EOF'
from database import get_all_patients_for_weekly_briefing
patients = get_all_patients_for_weekly_briefing()
print(f"Would send to {len(patients)} patients")
for p in patients[:3]:
    print("  ", p['patient_id'], p['phone'][-4:])  # last 4 digits only for safety
EOF
```

Expected: list of dicts (can be empty if all patients were recently sent tokens).

- [ ] **Step 3: Commit**

```bash
git add database.py
git commit -m "feat: add get_all_patients_for_weekly_briefing"
```

---

## Chunk 2: App Routes

---

### Task 5: Add `GET /patient/briefing/<token>` route to `app.py`

No-login page route. Validates the token (read-only), assembles data, renders template.

**Files:**
- Modify: `app.py` — add near the `GET /voice/<token_str>` route (~line 4063). Search for `@app.route('/voice/<token_str>')` to find the insertion point; add the new route immediately before it.

- [ ] **Step 1: Add route to `app.py`**

```python
@app.route('/patient/briefing/<token>')
def patient_briefing_page(token):
    """Patient weekly briefing page. No login required — token is the auth.

    The token is a 7-day magic link sent via SMS once per week.
    Multi-access: validates without consuming so patients can reopen.
    """
    tok = db.validate_sms_token_readonly(token)
    if not tok or tok['flow_type'] != 'briefing':
        return render_template('token_invalid.html',
            message='Briefing links are valid for one week. '
                    'Your provider will send a new one next week.'), 410

    data = db.get_briefing_data(tok['patient_id'])
    return render_template('patient/briefing.html', data=data)
```

- [ ] **Step 2: Verify route registered**

```bash
python - <<'EOF'
from app import app
rules = [r for r in app.url_map.iter_rules() if 'briefing' in r.rule]
print(rules)
EOF
```

Expected: `[<Rule '/patient/briefing/<token>' (GET, HEAD, OPTIONS) -> patient_briefing_page>]`

- [ ] **Step 3: Test invalid token returns 410**

Start Flask: `python app.py`

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:5002/patient/briefing/bad-token
```

Expected: `410`

- [ ] **Step 4: Test valid token renders page**

Create a test token and hit the route:

```bash
python - <<'EOF'
from database import create_sms_token
token = create_sms_token('PATIENT_ID', 'briefing', ttl_hours=1)
print(f"http://localhost:5002/patient/briefing/{token}")
EOF
```

Open the URL in a browser. At this point `briefing.html` doesn't exist yet — Flask will raise a `TemplateNotFound` error. That's expected and confirms the route is wired.

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: add /patient/briefing/<token> route"
```

---

### Task 6: Add `POST /api/internal/trigger-briefing-sms` to `app.py`

Weekly scheduler endpoint. Same guard and pattern as `internal_trigger_voice_sms`.

**Files:**
- Modify: `app.py` — add immediately after `internal_trigger_voice_sms` (~line 5291). Search for the `app.logger.info(f"[internal/voice] triggered=...` line to find the end of that function.

- [ ] **Step 1: Add scheduler endpoint**

```python
@app.route('/api/internal/trigger-briefing-sms', methods=['POST'])
def internal_trigger_briefing_sms():
    """
    Send weekly briefing SMS to all eligible patients (once per 7 days).

    Called by Render cron or external scheduler. Requires INTERNAL_SECRET.
    Creates a flow_type='briefing' token (7-day TTL) and delivers via the
    voice Twilio Studio flow, which sends a plain SMS with the link.
    """
    valid, err = _validate_internal_secret()
    if not valid:
        return err

    base_url = os.environ.get('APP_URL', '').rstrip('/')
    patients  = db.get_all_patients_for_weekly_briefing()

    triggered = 0
    skipped   = 0

    for patient in patients:
        patient_id = patient['patient_id']

        token = db.create_sms_token(
            patient_id=patient_id,
            flow_type='briefing',
            metadata={'source': 'weekly_briefing'},
            ttl_hours=168,   # 7 days — patients may revisit throughout the week
        )
        if not token:
            skipped += 1
            continue

        briefing_url = f"{base_url}/patient/briefing/{token}"

        sid = _twilio.trigger_flow(
            flow_type='voice',
            to_phone=patient['phone'],
            parameters={
                'provider_name': '',   # required by the voice Studio flow template
                'voice_prompt': (
                    'Your weekly CognaSync summary is ready — '
                    '2 weeks of your mood, sleep, and energy data. '
                    'No login needed.'
                ),
                'voice_link': briefing_url,
            },
        )

        if sid:
            triggered += 1
            app.logger.info(
                f"[internal/briefing] sent patient={patient_id!r}"
            )
        else:
            skipped += 1
            app.logger.warning(
                f"[internal/briefing] trigger_flow returned None for patient={patient_id!r}"
            )

    app.logger.info(f"[internal/briefing] triggered={triggered} skipped={skipped}")
    return jsonify({'ok': True, 'triggered': triggered, 'skipped': skipped})
```

- [ ] **Step 2: Test endpoint with curl (dry run against 0 eligible patients)**

Start Flask: `python app.py`

```bash
curl -s -X POST http://localhost:5002/api/internal/trigger-briefing-sms \
  -H "X-Internal-Secret: YOUR_INTERNAL_SECRET"
```

Expected response: `{"ok": true, "triggered": 0, "skipped": 0}` (if all patients already have recent briefing tokens) OR counts showing actual sends. If `401` — check the `INTERNAL_SECRET` env var.

- [ ] **Step 3: Verify token flow_type in DB after a test send**

If any patients were triggered, check the DB:

```sql
SELECT token, patient_id, flow_type, expires_at, created_at
FROM sms_tokens
WHERE flow_type = 'briefing'
ORDER BY created_at DESC
LIMIT 5;
```

Expected: rows with `flow_type = 'briefing'` and `expires_at` ~7 days from now.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: add /api/internal/trigger-briefing-sms scheduler endpoint"
```

---

## Chunk 3: Template

---

### Task 7: Create `templates/patient/briefing.html`

Standalone page — no `layout.html` extension, no nav, no auth context. Mobile-first (375px primary). Four stacked Chart.js sparklines. 2×2 stat grid. Conditional monitoring targets section.

**Files:**
- Create: `templates/patient/briefing.html`

- [ ] **Step 1: Create the template**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your Weekly Summary — CognaSync</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,300&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="{{ url_for('static', filename='css/tokens.css') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    /* ── Briefing-page layout overrides ────────────────────── */
    body {
      max-width: 480px;
      margin: 0 auto;
      padding: 24px 16px 56px;
    }

    /* Header */
    .b-header {
      text-align: center;
      padding-bottom: 20px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 24px;
    }
    .b-wordmark {
      font-size: 11px;
      letter-spacing: 0.10em;
      text-transform: uppercase;
      color: var(--text-muted);
      margin-bottom: 10px;
    }
    .b-greeting {
      font-family: 'DM Serif Display', Georgia, serif;
      font-size: 28px;
      font-weight: 400;
      color: var(--text);
      margin-bottom: 4px;
    }
    .b-period {
      font-size: 13px;
      color: var(--text-muted);
    }

    /* Stat grid */
    .b-stat-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-bottom: 28px;
    }
    .b-stat-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px 16px;
    }
    .b-stat-label {
      font-size: 11px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 4px;
    }
    .b-stat-value {
      font-family: 'JetBrains Mono', monospace;
      font-size: 26px;
      color: var(--text);
      line-height: 1;
    }
    .b-stat-unit {
      font-size: 11px;
      color: var(--text-muted);
      margin-top: 2px;
    }
    .b-stat-trend {
      font-size: 12px;
      margin-top: 5px;
    }
    .trend-up     { color: var(--green); }
    .trend-down   { color: var(--red); }
    .trend-stable { color: var(--text-muted); }

    /* Charts */
    .b-chart-section { margin-bottom: 20px; }
    .b-chart-label {
      font-size: 11px;
      font-weight: 500;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 6px;
    }
    .b-chart-wrap {
      height: 120px;
      position: relative;
    }

    /* Empty state */
    .b-empty {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 28px 20px;
      text-align: center;
      color: var(--text-muted);
      font-size: 14px;
      line-height: 1.6;
      margin-bottom: 24px;
      display: none;
    }

    /* Targets */
    .b-targets {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px;
      margin-bottom: 24px;
    }
    .b-targets h2 {
      font-family: 'DM Serif Display', Georgia, serif;
      font-size: 18px;
      font-weight: 400;
      margin-bottom: 6px;
    }
    .b-targets p {
      font-size: 13px;
      color: var(--text-muted);
      margin-bottom: 12px;
    }
    .b-targets ul {
      list-style: none;
      padding: 0;
      margin: 0;
    }
    .b-targets li {
      font-size: 14px;
      padding: 4px 0 4px 18px;
      position: relative;
    }
    .b-targets li::before {
      content: '·';
      position: absolute;
      left: 4px;
      color: var(--accent);
      font-size: 18px;
      line-height: 1;
    }

    /* Footer */
    .b-footer {
      border-top: 1px solid var(--border);
      padding-top: 20px;
      text-align: center;
      font-size: 12px;
      color: var(--text-muted);
      line-height: 1.8;
    }
  </style>
</head>
<body>

  {# Pass all data to JavaScript in one block at the top of the body #}
  <script>const BRIEFING_DATA = {{ data | tojson | safe }};</script>

  <!-- ── Header ───────────────────────────────────────────────── -->
  <header class="b-header">
    <div class="b-wordmark">CS · CognaSync</div>
    <h1 class="b-greeting">Hi {{ data.patient_first_name }}</h1>
    <p class="b-period">
      {{ data.date_range.start[:10] if data.date_range.start else '' }}
      –
      {{ data.date_range.end[:10] if data.date_range.end else '' }}
    </p>
  </header>

  <!-- ── Stat strip ───────────────────────────────────────────── -->
  <div class="b-stat-grid">
    <div class="b-stat-card">
      <div class="b-stat-label">Avg Mood</div>
      <div class="b-stat-value" id="s-mood">—</div>
      <div class="b-stat-unit">/10</div>
      <div class="b-stat-trend" id="t-mood"></div>
    </div>
    <div class="b-stat-card">
      <div class="b-stat-label">Avg Sleep</div>
      <div class="b-stat-value" id="s-sleep">—</div>
      <div class="b-stat-unit">hrs</div>
      <div class="b-stat-trend" id="t-sleep"></div>
    </div>
    <div class="b-stat-card">
      <div class="b-stat-label">Avg Stress</div>
      <div class="b-stat-value" id="s-stress">—</div>
      <div class="b-stat-unit">/10</div>
      <div class="b-stat-trend" id="t-stress"></div>
    </div>
    <div class="b-stat-card">
      <div class="b-stat-label">Avg Energy</div>
      <div class="b-stat-value" id="s-energy">—</div>
      <div class="b-stat-unit">/10</div>
      <div class="b-stat-trend" id="t-energy"></div>
    </div>
  </div>

  <!-- ── Empty state (JS shows/hides based on checkin_count) ─── -->
  <div class="b-empty" id="charts-empty">
    Not enough check-in data to show trends yet.<br>
    Log check-ins throughout the week to see your patterns here.
  </div>

  <!-- ── Charts (JS hides if < 3 check-ins) ───────────────────── -->
  <div id="charts-section">
    <div class="b-chart-section">
      <div class="b-chart-label">Mood</div>
      <div class="b-chart-wrap"><canvas id="chart-mood"></canvas></div>
    </div>
    <div class="b-chart-section">
      <div class="b-chart-label">Sleep</div>
      <div class="b-chart-wrap"><canvas id="chart-sleep"></canvas></div>
    </div>
    <div class="b-chart-section">
      <div class="b-chart-label">Stress</div>
      <div class="b-chart-wrap"><canvas id="chart-stress"></canvas></div>
    </div>
    <div class="b-chart-section">
      <div class="b-chart-label">Energy</div>
      <div class="b-chart-wrap"><canvas id="chart-energy"></canvas></div>
    </div>
  </div>

  <!-- ── Monitoring targets (Jinja conditional) ───────────────── -->
  {% if data.monitoring_targets %}
  <section class="b-targets">
    <h2>What we're paying attention to</h2>
    <p>Your care team asked us to focus on these areas in your check-ins:</p>
    <ul>
      {% for label in data.monitoring_targets %}
      <li>{{ label }}</li>
      {% endfor %}
    </ul>
  </section>
  {% endif %}

  <!-- ── Footer ───────────────────────────────────────────────── -->
  <footer class="b-footer">
    <p>Generated from your check-ins · {{ data.generated_at[:10] }}</p>
    <p>Questions? Reach out to your care team.</p>
  </footer>

  <!-- ── JavaScript ───────────────────────────────────────────── -->
  <script>
    (function () {
      'use strict';
      var d = BRIEFING_DATA;

      // ── Stat cards ──────────────────────────────────────────
      function renderStat(valId, trendId, average, trend) {
        var valEl   = document.getElementById(valId);
        var trendEl = document.getElementById(trendId);

        if (valEl) {
          valEl.textContent = (average != null) ? Number(average).toFixed(1) : '—';
        }

        if (!trendEl) return;
        if (trend === 'improving') {
          trendEl.textContent = '▲ improving';
          trendEl.className = 'b-stat-trend trend-up';
        } else if (trend === 'declining') {
          trendEl.textContent = '▼ declining';
          trendEl.className = 'b-stat-trend trend-down';
        } else if (trend === 'stable') {
          trendEl.textContent = '– stable';
          trendEl.className = 'b-stat-trend trend-stable';
        } else {
          trendEl.textContent = '';
        }
      }

      renderStat('s-mood',   't-mood',   d.mood.average,   d.mood.trend);
      renderStat('s-sleep',  't-sleep',  d.sleep.average,  d.sleep.trend);
      renderStat('s-stress', 't-stress', d.stress.average, d.stress.trend);
      renderStat('s-energy', 't-energy', d.energy.average, d.energy.trend);

      // ── Empty state check ───────────────────────────────────
      if (d.checkin_count < 3) {
        document.getElementById('charts-section').style.display = 'none';
        document.getElementById('charts-empty').style.display   = 'block';
        return;   // no charts to render
      }

      // ── Chart helpers ────────────────────────────────────────
      function thinLabels(dates) {
        // Show every 3rd date to prevent crowding on 375px mobile
        return dates.map(function (iso, i) {
          if (i % 3 !== 0) return '';
          var dt = new Date(iso);
          return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        });
      }

      function makeChart(canvasId, dates, values, yMax) {
        // Deep-copy the base config so each chart is independent
        var cfg = {
          type: 'line',
          data: {
            labels: thinLabels(dates),
            datasets: [{
              data:            values,
              borderColor:     '#0F6E56',
              backgroundColor: 'rgba(15, 110, 86, 0.10)',
              fill:            true,
              tension:         0.3,
              pointRadius:     3,
              pointHoverRadius: 5,
              spanGaps:        true,  // connect line across null (missing check-in) days
            }]
          },
          options: {
            responsive:          true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: {
                grid:  { display: false },
                ticks: { font: { size: 11 }, color: '#5F5E5A' }
              },
              y: {
                display: false,   // averages are shown in stat cards above
                min:     0,
                max:     yMax,
              }
            }
          }
        };
        new Chart(document.getElementById(canvasId), cfg);
      }

      makeChart('chart-mood',   d.mood.dates,   d.mood.daily_scores,   10);
      makeChart('chart-sleep',  d.sleep.dates,  d.sleep.daily_hours,   12);  // y.max=12 for hours
      makeChart('chart-stress', d.stress.dates, d.stress.daily_scores, 10);
      makeChart('chart-energy', d.energy.dates, d.energy.daily_scores, 10);

    })();
  </script>
</body>
</html>
```

- [ ] **Step 2: Confirm `tokens.css` exists**

```bash
ls /path/to/cognasync-mvp/static/css/tokens.css
```

Expected: file present. If missing, change the template's `tokens.css` link to use the same hardcoded path that `token_invalid.html` uses, or remove it if it's not needed for the briefing page's subset of CSS variables.

- [ ] **Step 3: Verify template renders with a real token**

With Flask running: `python app.py`

```bash
# Create a test briefing token
python - <<'EOF'
from database import create_sms_token
token = create_sms_token('PATIENT_ID', 'briefing', ttl_hours=1)
print(f"Open: http://localhost:5002/patient/briefing/{token}")
EOF
```

Open the URL in a browser. Verify:
- Page loads without error
- Header shows patient's first name and date range
- Stat cards show numeric values (or `—` if no check-ins)
- If ≥ 3 check-ins: four charts render with green lines
- If < 3 check-ins: empty state message shows, no charts
- If provider has set monitoring targets: targets section appears below charts
- Reload the page — it still works (confirms multi-use token)

- [ ] **Step 4: Mobile viewport check**

In Chrome DevTools, open the page at 375px width (iPhone SE). Verify:
- 2×2 stat grid lays out correctly (not overflowing)
- Charts are full width and readable at 120px height
- No horizontal scroll
- Target list items wrap cleanly

- [ ] **Step 5: Commit**

```bash
git add templates/patient/briefing.html
git commit -m "feat: add patient briefing template with Chart.js sparklines"
```

---

## Final Verification

- [ ] **End-to-end test: SMS → page → reload**

1. Trigger the scheduler manually:
   ```bash
   curl -s -X POST http://localhost:5002/api/internal/trigger-briefing-sms \
     -H "X-Internal-Secret: YOUR_SECRET"
   ```
2. Check the DB for new `flow_type='briefing'` token:
   ```sql
   SELECT token, patient_id, expires_at FROM sms_tokens
   WHERE flow_type = 'briefing' ORDER BY created_at DESC LIMIT 1;
   ```
3. Open `http://localhost:5002/patient/briefing/{token}` — page renders.
4. Open the same URL again — still renders (multi-use confirmed).
5. Manually expire the token (set `expires_at` to the past in Supabase), reload — 410 page shows.

- [ ] **Verify `suicidality` domain never surfaces**

In Supabase, temporarily set a test patient's provider focus config to include `suicidality`. Load their briefing page. Confirm the monitoring targets section either shows no targets (if that was the only domain) or shows only non-suicidality targets. Then remove the test config.

- [ ] **Final commit: tag the feature complete**

```bash
git commit --allow-empty -m "feat: patient briefing page — complete"
```
