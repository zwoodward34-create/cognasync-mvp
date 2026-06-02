# CognaSync SMS Daily Check-In — Design Specification

## The Core Constraint

SMS imposes a hard tradeoff: more questions = less compliance. The check-in must be
completable with a single reply. The design goal is to maximize computed score coverage
from the fewest possible data points, all within 160 characters per message.

---

## The Format: 5 Numbers, One Reply

### Daily outbound message (147 chars — 1 SMS segment)
```
CognaSync: Today's check-in
Reply: mood energy stress sleep-quality sleep-hrs
Scale 0-10, sleep in hrs (e.g. 6.5)
→ 7 8 4 6 6.5
Reply SKIP to skip.
```

### Patient reply
```
7 8 4 6 6.5
```

That's it. One inbound message, five numbers, parseable in milliseconds.

---

## Number Mapping

| Position | Field | Range | Maps to DB field |
|---|---|---|---|
| 1 | Mood | 0–10 | `checkins.mood_score` |
| 2 | Energy | 0–10 | `extended_data.energy` |
| 3 | Stress / Anxiety | 0–10 | `checkins.stress_score` |
| 4 | Sleep quality last night | 0–10 | `extended_data.sleep_quality` |
| 5 | Sleep hours last night | 0–12 (decimals OK) | `checkins.sleep_hours` |

Additional fields set automatically:
- `checkins.checkin_type = 'sms'`
- `extended_data.dissociation = 0` (clinical default — flagged in metadata)
- `extended_data.sms_format = '5num'`
- `extended_data.dissociation_source = 'default'`

---

## Score Coverage

| Computed Score | Formula inputs | SMS coverage |
|---|---|---|
| **Stability Score** | mood + energy + (10−dissoc) + (10−stress) / 4 | ✅ Approximate (dissociation=0 default) |
| **Sleep Disruption** | sleep_hours < 6 → +2; latency, awakenings | ⚠️ Partial (hours only, +2 if <6) |
| **Nervous System Load** | (stress + (10−sleep_quality) + stim_load) / 3 | ✅ Approximate (stim from med events) |
| **Crash Risk** | SD×0.4 + NSL×0.4 + (10−nutrition)×0.2 | ✅ Approximate (nutrition omitted → 50/50 weight) |
| **Mood Distortion** | \|mood − stability\| | ✅ Approximate |
| **Dopamine Efficiency** | (energy + focus) / 2 | ⚠️ Partial (focus not captured) |
| **Stim Load** | caffeine tier + stim meds + boosters | ⚠️ From med events only (no caffeine) |

**Net result**: all five core trend metrics (mood, stability, sleep, NS load, crash risk) are
populated and trended. The SMS check-in is not a replacement for the full React check-in —
it is a daily signal that keeps the longitudinal record alive between fuller submissions.

---

## Message Templates

### Onboarding (first send — 199 chars, 2 segments — acceptable once)
```
CognaSync daily check-in from Dr. [Provider].
Reply with 5 numbers:
1. Mood (0-10)
2. Energy (0-10)
3. Stress (0-10)
4. Sleep quality last night (0-10)
5. Hours slept
Ex: 7 8 4 6 6.5 | Reply SKIP to skip
```

### Daily recurring (147 chars — 1 segment)
```
CognaSync: Today's check-in
Reply: mood energy stress sleep-quality sleep-hrs
Scale 0-10, sleep in hrs (e.g. 6.5)
→ 7 8 4 6 6.5
Reply SKIP to skip.
```

### Confirmation (88 chars — 1 segment)
```
Got it — check-in logged ✓ Mood 7 · Energy 8 · Stress 4 · Sleep 6.5hrs. Have a good day.
```

### Medication add-on, if patient has meds (62 chars — 1 segment)
Sent immediately after confirmation, one per medication:
```
One more: did you take your [Medication] [dose]? Reply Y or N.
```

### Parse failure / invalid reply (105 chars — 1 segment)
```
Didn't catch that. Reply with 5 numbers: mood energy stress sleep-quality sleep-hrs. Example: 7 8 4 6 6.5
```

### SKIP acknowledgment (46 chars)
```
Got it — skipped for today. Talk soon.
```

### Crisis intercept (115 chars — 1 segment)
Triggered before any parsing if crisis keywords present:
```
It sounds like you may be struggling. Please reach out:
📞 988 (call or text)
💬 Text HOME to 741741
🚨 Emergency: 911
```

### Weekly add-on (Friday evening — adds dissociation, 150 chars — 1 segment)
```
Weekly add-on: same 5 numbers + dissociation (fog/spaciness, 0=clear 10=very foggy). Ex: 7 8 4 6 6.5 2. Optional: reply with one word about your week.
```

---

## Inbound Parse Logic (pseudo-code)

```python
def parse_sms_checkin(body: str) -> dict | None:
    # 1. Crisis check (always first, before any parsing)
    if _check_crisis(body):
        send_sms(from_number, CRISIS_MESSAGE)
        return None

    # 2. SKIP
    if body.strip().lower() in ('skip', 's', 'stop', 'no'):
        send_sms(from_number, SKIP_ACK)
        return None

    # 3. Parse numbers (space or comma separated, decimals allowed)
    tokens = re.split(r'[\s,]+', body.strip())
    nums = []
    for t in tokens:
        try:
            nums.append(float(t))
        except ValueError:
            continue

    # 4. Need at least 4 numbers (5 preferred)
    if len(nums) < 4:
        send_sms(from_number, INVALID_FORMAT_MESSAGE)
        return None

    mood     = clamp(nums[0], 0, 10)
    energy   = clamp(nums[1], 0, 10)
    stress   = clamp(nums[2], 0, 10)

    if len(nums) >= 5:
        sleep_q = clamp(nums[3], 0, 10)
        sleep_h = clamp(nums[4], 0, 12)
        fmt = '5num'
    else:
        # 4-number fallback: mood energy stress sleep_hrs (no sleep_quality)
        sleep_q = None
        sleep_h = clamp(nums[3], 0, 12)
        fmt = '4num'

    # 5. Weekly 6-number format (includes dissociation)
    dissoc = clamp(nums[5], 0, 10) if len(nums) >= 6 else 0
    dissoc_source = 'explicit' if len(nums) >= 6 else 'default'

    return {
        'mood': int(round(mood)),
        'stress': int(round(stress)),
        'sleep_hours': sleep_h,
        'extended_data': {
            'energy': int(round(energy)),
            'sleep_quality': int(round(sleep_q)) if sleep_q is not None else None,
            'dissociation': int(round(dissoc)),
            'dissociation_source': dissoc_source,
            'sms_format': fmt,
        },
        'checkin_type': 'sms',
        'notes': None,
        'medications': [],  # resolved from med events separately
    }
```

---

## Inbound Routing (extending `/api/sms/inbound`)

Current logic: check if body is Y/N → medication reply.
Extended logic (ordered):

```
1. Crisis keywords? → crisis response, stop.
2. Y/N/Yes/No? → medication reply handler (existing).
3. Contains ≥4 parseable numbers? → check-in parser (new).
4. "SKIP"? → log skip, send ack.
5. Anything else? → send invalid format hint if patient has a pending check-in session,
                    otherwise silently ignore.
```

The "pending check-in session" is tracked via a new `sms_checkin_sessions` table:
```sql
CREATE TABLE sms_checkin_sessions (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id  uuid NOT NULL REFERENCES profiles(id),
  sent_at     timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL,
  replied_at  timestamptz,
  checkin_id  uuid,  -- FK to checkins once created
  format      text   -- 'daily', 'weekly', 'onboarding'
);
```

---

## Anchor Labels for Patient Guidance

The five numbers should become second nature. The mnemonic is **M-E-S-Q-H**:

> **M**ood · **E**nergy · **S**tress · **Q**uality of sleep · **H**ours slept

After 3–4 days, most patients won't need the prompt label — they'll reply instinctively.

---

## What SMS Does NOT Capture (full check-in only)

| Missing field | Score impact | Mitigation |
|---|---|---|
| Dissociation | Stability ≈15% lower accuracy | Default 0; flag `dissociation_source='default'` in extended_data |
| Caffeine intake | Stim Load caffeine tier | Pull from med events for stimulant medications |
| Focus | Dopamine Efficiency partial | Trend from full check-ins when available |
| Sleep latency / awakenings | Sleep Disruption partial | Hours alone captures the most impactful factor (+2 if <6hrs) |
| Nutrition | Crash Risk weight shift | Formula falls back to 50/50 SD+NSL (already implemented) |
| Notes / free text | Journal / sentiment | Weekly enrichment prompt or voice SMS covers this |

---

## Recommended Send Schedule

| Cadence | Time | Format | Purpose |
|---|---|---|---|
| Daily (Mon–Fri) | 8:30 AM patient local time | 5-number short | Core daily signal |
| Weekly (Friday) | 8:30 AM | 6-number + optional word | Adds dissociation; weekly reflection |
| Ad-hoc | Provider-triggered | Short or full link | Pre-appointment or concern follow-up |
| First send | Day of enrollment | Onboarding (2 segments) | Teaches the format with full labels |

Weekend sends are intentionally omitted by default — reduces fatigue. Provider can override per patient.

---

## Integration Points

- **`sms_engine.py`**: Add `send_daily_checkin_sms()`, `parse_sms_checkin_reply()`, `send_checkin_confirmation()`
- **`app.py /api/sms/inbound`**: Extend routing to handle number-replies via new parse function
- **`database.py`**: Add `create_sms_checkin_session()`, `resolve_sms_checkin_session()`
- **Cron job**: Extend `/api/internal/send-appointment-sms` or add new `/api/internal/send-daily-checkin` endpoint
- **`create_checkin()`**: Already accepts `checkin_type` and `extended_data` — no schema changes needed
