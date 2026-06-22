"""
Seed the database with synthetic test data for local/dev use (Supabase-native).

Creates test patients (as Supabase auth users + profiles), assigns them to the
local dev provider (`provider@dev.local` if it exists, else creates
`dr.smith@test.com`), and seeds enriched check-ins, journals, medication logs,
and a summary for each.

What "enriched" means (added 2026-06-22, per docs/session-handoff-2026-06-21.md
"Next up #1 — Enrich the seed"):

  1. Every check-in carries an `extended_data` blob with the advanced fields that
     drive CLAUDE.md §5 derived scores — energy, dissociation, caffeine, sleep
     architecture, nutrition, and the §6 behavioral fields. Without these the
     Stability / NS Load / Crash Risk / Stim Load charts render empty (the Jordan
     brief's blank panels were missing fixtures, not a bug).

  2. Medications are logged as `taken` so the medication-adherence signal and the
     stimulant component of Stim Load populate.

  3. A dedicated showcase patient (`zach@test.com`) reproduces the "Zach scenario"
     the P0 safety fixes regression-guard against: elevated/stable check-in mood,
     then a multi-day silence, a low-affect clinical session carrying hopelessness
     language (crisis_detected = False — the production-faithful shape), cheerful
     journals (so self-report diverges from the flat session), an SMS engagement
     gap, and active suicidality/mood monitoring targets. That convergence trips
     `_compute_voice_divergence` and the ≥2-of-3 `_compute_suicidality_escalation`
     gate in claude_api.py — so the consolidation + voice-divergence fixes can be
     regression-tested by clicking locally instead of mailing a PDF.

Idempotent at the user level: re-running skips users that already exist, and the
Zach scenario's heavy rows (clinical session, SMS tokens) are only seeded when no
clinical session is already present for him.

Usage: python seed_test_data.py
"""
import random
from datetime import date, datetime, timedelta, timezone

import database as db

PATIENT_PASSWORD = "DevPass123!"
LOCAL_PROVIDER_EMAIL = "provider@dev.local"   # created by scripts/local.sh seed

TEST_PATIENTS = [
    ("alex@test.com",   "Alex Johnson"),
    ("jordan@test.com", "Jordan Smith"),
    ("morgan@test.com", "Morgan Lee"),
]
FALLBACK_PROVIDER = ("dr.smith@test.com", "Dr. Sarah Smith")
SHOWCASE_EMAIL = "zach@test.com"
SHOWCASE_NAME  = "Zach Demo"

PATIENT_MEDS = {
    "alex@test.com": [
        {"name": "sertraline", "dose": "100", "dose_unit": "mg"},
        {"name": "alprazolam", "dose": "0.5", "dose_unit": "mg"},
    ],
    "jordan@test.com": [
        {"name": "bupropion", "dose": "150", "dose_unit": "mg"},
    ],
    "morgan@test.com": [
        {"name": "escitalopram", "dose": "20", "dose_unit": "mg"},
        {"name": "quetiapine",   "dose": "50", "dose_unit": "mg"},
    ],
    SHOWCASE_EMAIL: [
        {"name": "sertraline", "dose": "50", "dose_unit": "mg"},
    ],
}

SAMPLE_JOURNALS = [
    ("Had a tough day today. Started the morning anxious about the team meeting at work. "
     "I keep thinking I'll say something wrong and everyone will judge me. The meeting went "
     "okay, but I still feel unsettled."),
    ("Woke up feeling pretty good actually. Got outside for a walk and the air was crisp. "
     "On days when I move my body, the evening feels less heavy."),
    ("Couldn't sleep again last night. Kept thinking about finances, work, the future. My "
     "brain doesn't seem to have an off switch. Feel exhausted today."),
    ("Something shifted today. I feel more like myself. I laughed at something genuinely "
     "funny — a real laugh. Small thing, but it felt meaningful."),
    ("I've been canceling plans with friends lately. I tell myself it's because I'm tired, "
     "but I think I'm afraid of not having energy to be 'on.'"),
    ("Had an okay week. I've been taking my medication consistently, which I'm proud of. My "
     "mood has been a bit flat but not bad. Just... neutral."),
    ("Panic attack this morning before my appointment. Heart pounding, couldn't catch my "
     "breath. It passed in about 15 minutes but left me shaky for hours."),
]

# Cheerful / upbeat entries for the showcase patient — these must NOT contain
# hopelessness language. The whole point of the Zach scenario is that the written
# self-report reads fine while the clinical session presents flat and low.
SHOWCASE_JOURNALS = [
    ("Good week overall. Got through my to-do list and even had energy left over in the "
     "evenings. Feeling pretty steady."),
    ("Slept well, woke up early, knocked out a workout before breakfast. Little wins add up — "
     "I feel like I'm on top of things right now."),
    ("Caught up with a friend over coffee and laughed a lot. Honestly things feel manageable "
     "this week."),
]

SAMPLE_SYMPTOMS = [
    "mild anxiety", "fatigue", "difficulty concentrating", "some tension",
    "restlessness", "low energy", "racing thoughts", "headache", "", "",
]

# notable_symptoms (§6) — array-valued; recur enough to cross the ≥3-day threshold
NOTABLE_SYMPTOM_POOL = [
    [], [], ["headache"], ["brain fog"], ["fatigue"], ["headache", "fatigue"],
    ["nausea"], [], ["brain fog"], [],
]


def _clamp(v, lo=0, hi=10):
    return max(lo, min(hi, v))


def random_mood(base=6, variance=2):
    return max(1, min(10, base + random.randint(-variance, variance)))


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def meds_log(email, adherence=0.9):
    """Return a check-in medication log: each configured med, mostly `taken`."""
    log = []
    for m in PATIENT_MEDS.get(email, []):
        log.append({
            "name":      m["name"],
            "dose":      m["dose"],
            "dose_unit": m.get("dose_unit", "mg"),
            "taken":     random.random() < adherence,
            "time_taken": random.choice(["08:00", "08:30", "09:00", "21:00"]),
        })
    return log


def make_extended_data(mood, stress, sleep_hours, *, elevated=False):
    """Build a rich extended_data blob so §5 derived scores + charts populate.

    Fields are correlated with mood/stress/sleep so the computed scores move
    realistically rather than being random noise. `elevated=True` produces a
    high-stability / low-crash-risk profile (used for the showcase patient's
    rosy self-report).
    """
    if elevated:
        energy        = _clamp(mood + random.randint(-1, 0))
        dissociation  = _clamp(random.randint(0, 1))
        anxiety       = _clamp(stress + random.randint(-1, 1))
        irritability  = _clamp(random.randint(0, 2))
        motivation    = _clamp(mood + random.randint(-1, 1))
        caffeine_mg   = random.choice([0, 80, 95, 120])
        sleep_quality = _clamp(7 + random.randint(0, 2))
        latency       = random.choice([5, 10, 12, 15])
        awakenings    = random.choice([0, 0, 1])
        fell_easily   = True
        protein       = random.randint(6, 9)
        sugar         = random.randint(1, 4)
        hydration     = random.choice([70, 80, 90, 100])
        alcohol       = 0
        exercise      = random.choice([30, 40, 45, 60])
        sunlight      = round(random.uniform(1.0, 3.0), 1)
        screen        = round(random.uniform(3.0, 6.0), 1)
        social        = _clamp(7 + random.randint(0, 2))
        workload      = _clamp(random.randint(2, 4))
    else:
        energy        = _clamp(mood + random.randint(-2, 1))
        dissociation  = _clamp(random.randint(0, 4))
        anxiety       = _clamp(stress + random.randint(-1, 2))
        irritability  = _clamp(random.randint(0, 5))
        motivation    = _clamp(mood + random.randint(-2, 1))
        caffeine_mg   = random.choice([0, 95, 150, 200, 280, 350])
        sleep_quality = _clamp(int(round(sleep_hours)) + random.randint(-2, 1))
        latency       = random.choice([10, 20, 35, 50, 65])
        awakenings    = random.choice([0, 1, 2, 3])
        fell_easily   = sleep_hours >= 6.5 and random.random() < 0.7
        protein       = random.randint(3, 8)
        sugar         = random.randint(2, 9)
        hydration     = random.choice([40, 55, 60, 70, 85])
        alcohol       = random.choice([0, 0, 0, 1, 2, 3])
        exercise      = random.choice([0, 0, 20, 30, 45])
        sunlight      = round(random.uniform(0.2, 2.5), 1)
        screen        = round(random.uniform(4.0, 10.0), 1)
        social        = _clamp(random.randint(2, 8))
        workload      = _clamp(random.randint(3, 9))

    return {
        # core advanced affect (§6)
        "energy":        energy,
        "focus":         _clamp(energy + random.randint(-1, 1)),
        "anxiety":       anxiety,
        "dissociation":  dissociation,
        "irritability":  irritability,
        "motivation":    motivation,
        "perceived_stress": _clamp(stress + random.randint(-1, 1)),
        # stim load inputs
        "caffeine_mg":   caffeine_mg,
        "booster_used":  0,
        # sleep architecture (sleep disruption score)
        "sleep_quality":          sleep_quality,
        "sleep_latency_minutes":  latency,
        "night_awakenings":       awakenings,
        "fell_asleep_easily":     fell_easily,
        # nutrition stability
        "protein_servings": protein,
        "sugar_servings":   sugar,
        "hydration_oz":     hydration,
        # behavioral / lifestyle (§6)
        "alcohol_units":     alcohol,
        "cannabis_sessions": 0,
        "nicotine_count":    0,
        "exercise_minutes":  exercise,
        "sunlight_hours":    sunlight,
        "screen_time_hours": screen,
        "social_quality":    social,
        "workload_friction": workload,
        "coping_activities": {
            "breathing":  random.random() < 0.4,
            "meditation": random.random() < 0.3,
            "movement":   exercise > 0,
        },
        "notable_symptoms": [] if elevated else random.choice(NOTABLE_SYMPTOM_POOL),
    }


def ensure_user(email, name, role):
    """Return (user_id, created_bool); create the auth user + profile if needed."""
    existing = db.get_user_by_email(email)
    if existing:
        print(f"  exists: {email} ({existing['role']})")
        return existing["id"], False
    res = db.supabase_admin.auth.admin.create_user({
        "email": email.lower().strip(),
        "password": PATIENT_PASSWORD,
        "email_confirm": True,
    })
    uid = res.user.id
    db.supabase_admin.table("profiles").insert({
        "id": uid,
        "email": email.lower().strip(),
        "full_name": name,
        "role": role,
        "status": "approved",   # seeded accounts skip email-verify + admin-approval gates
    }).execute()
    print(f"  created {role}: {name} ({email})")
    return uid, True


def make_checkins(patient_id, email, days, base_mood, base_stress):
    today = date.today()
    n = 0
    for i in range(days):
        if random.random() < 0.2:        # ~80% completion, realistic gaps
            continue
        entry_date = today - timedelta(days=i)
        sleep = round(random.uniform(5.0, 9.0), 1)
        mood = random_mood(base_mood)
        if sleep >= 7.5:
            mood = min(10, mood + 1)
        elif sleep < 6:
            mood = max(1, mood - 1)
        stress = random_mood(base_stress)
        db.create_checkin(
            patient_id=patient_id,
            date_str=entry_date.isoformat(),
            time_of_day=random.choice(["morning", "afternoon", "evening"]),
            mood_score=mood,
            medications=meds_log(email),
            sleep_hours=sleep,
            stress_score=stress,
            symptoms=random.choice(SAMPLE_SYMPTOMS),
            notes="",
            checkin_type="full",
            extended_data=make_extended_data(mood, stress, sleep),
        )
        n += 1
    return n


def make_journals(patient_id, count, pool=SAMPLE_JOURNALS):
    analysis = (
        "This entry reflects self-monitoring and awareness of internal states. "
        "Worth discussing sleep patterns and energy with your provider."
    )
    for entry in random.sample(pool, min(count, len(pool))):
        db.create_journal(patient_id, "free_flow", entry, ai_analysis=analysis)


def make_summary(patient_id):
    today = date.today()
    start = today - timedelta(days=14)
    text = (
        "Over the past two weeks, mood averaged ~6.5/10 with variability correlating with "
        "sleep quality. Stress was moderate (~5/10) with workday spikes. Journals reflect "
        "anticipatory anxiety and moments of self-awareness; physical activity had a positive "
        "effect on mood. Medication adherence appears consistent. Discussion topics: sleep "
        "and mood stability, managing anticipatory anxiety, social withdrawal patterns."
    )
    db.create_summary(patient_id, text, start.isoformat(), today.isoformat())


# ── Showcase: the "Zach scenario" ────────────────────────────────────────────

def _insert_sms_token(patient_id, flow_type, sent_day, answered):
    """Insert one sms_tokens row with an explicit created_at / used_at.

    create_sms_token() always stamps `now()` and leaves used_at NULL, so to
    backdate a prompt and mark it (un)answered we insert directly.
    """
    import uuid as _uuid
    created = datetime.combine(sent_day, datetime.min.time(),
                               tzinfo=timezone.utc) + timedelta(hours=9)
    row = {
        "token":      str(_uuid.uuid4()),
        "patient_id": str(patient_id),
        "flow_type":  flow_type,
        "metadata":   {"seeded": True},
        "created_at": created.isoformat(),
        "expires_at": (created + timedelta(hours=24)).isoformat(),
        "used_at":    (created + timedelta(minutes=30)).isoformat() if answered else None,
    }
    db.supabase_admin.table("sms_tokens").insert(row).execute()


def _zach_session_features():
    """Extracted-features dict for the low-affect, hopeless clinical session.

    Shaped to match the production session that the 06-18 brief mishandled:
    hopelessness lives in patient_mood_description / themes (NOT raw transcript),
    crisis_detected is False, and the speech_features cluster is flat / low arousal
    / depressive — which `_session_is_low_affect` and `_compute_suicidality_
    escalation` both key on.
    """
    return {
        "patient_mood_description": (
            "Overwhelmed and hopeless about the job search; a lot of self-blame this week. "
            "Says it is hard to see the point of pushing forward."
        ),
        "energy_description": "Low energy, slowed, hard to get going in the mornings.",
        "functional_status": "Withdrawing from routines; skipping some daily activities.",
        "themes": ["job search distress", "self-blame", "hopelessness about the future"],
        "stressors": ["unemployment", "finances"],
        "clinical_pattern_type": "depressive",
        "speech_features": {
            "speech_rate":     "slowed",
            "prosody":         "flat",
            "pauses":          "increased",
            "speech_coherence": "intact",
            "arousal":         "low",
            "vocal_affect":    "flat",
            "clinical_pattern_type": "depressive",
            "confidence":      "medium",
            "severity_note":   "Patient voiced feeling hopeless about the future.",
        },
    }


def seed_zach_scenario(provider_id):
    """Seed the showcase patient that reproduces the P0 regression scenario."""
    zid, created = ensure_user(SHOWCASE_EMAIL, SHOWCASE_NAME, "patient")
    db.assign_patient_to_provider(zid, provider_id)
    db.update_patient_profile(zid, current_medications=PATIENT_MEDS[SHOWCASE_EMAIL])

    # Active monitoring targets — upsert, always safe to re-run.
    db.set_provider_focus_config(
        provider_id, zid, ["suicidality", "mood"],
        notes="Monitoring suicidality and mood after recent job loss.",
        set_by_role="psychiatrist", weeks=4,
    )

    # Idempotency guard for the heavy rows: only seed once.
    if not created and db.get_clinical_sessions_for_period(zid):
        print(f"  showcase {SHOWCASE_EMAIL}: scenario rows already present — skipping")
        return zid

    today = date.today()

    # 1) Elevated / stable check-ins, then a 9-day trailing silence.
    elevated = [(13, 9), (12, 10), (11, 9), (10, 10), (9, 9)]   # (days_ago, mood)
    for days_ago, mood in elevated:
        d = today - timedelta(days=days_ago)
        sleep = round(random.uniform(7.5, 8.5), 1)
        stress = random.randint(1, 3)
        db.create_checkin(
            patient_id=zid,
            date_str=d.isoformat(),
            time_of_day="morning",
            mood_score=mood,
            medications=meds_log(SHOWCASE_EMAIL, adherence=1.0),
            sleep_hours=sleep,
            stress_score=stress,
            symptoms="",
            notes="",
            checkin_type="full",
            extended_data=make_extended_data(mood, stress, sleep, elevated=True),
        )
    # (days_ago 8..0 left silent → max_consecutive_gap = 9)

    # 2) Cheerful journals (self-report stays rosy).
    make_journals(zid, 3, pool=SHOWCASE_JOURNALS)

    # 3) Low-affect clinical session mid-gap (nearest check-in is 9 days ago → 3d gap).
    session_date = (today - timedelta(days=6)).isoformat()
    sid = db.store_clinical_session(
        provider_id=str(provider_id),
        patient_id=str(zid),
        session_date=session_date,
        session_type="voice_note",
        transcript_raw=("Patient voice note. Reflective, low and flat affect throughout; "
                        "describes feeling overwhelmed and hopeless about the job search."),
        duration_minutes=4,
        transcript_source="voice_memo",
    )
    if sid:
        db.store_session_features(
            session_id=sid,
            patient_id=str(zid),
            extraction_result={
                "crisis_detected": False,
                "features": _zach_session_features(),
                "scores": {},
            },
            extraction_model="seed-fixture",
        )

    # 4) SMS engagement gap: medication answered through the active period, then
    #    9 unanswered days; a few unanswered voice prompts give selective-channel
    #    divergence and push the overall response rate under the insufficient-data bar.
    for days_ago in range(13, -1, -1):           # 14 daily medication prompts
        day = today - timedelta(days=days_ago)
        answered = days_ago >= 9                 # answered only during the active window
        _insert_sms_token(zid, "medication", day, answered)
    for days_ago in (13, 10, 6, 2):              # voice prompts: never answered
        _insert_sms_token(zid, "voice", today - timedelta(days=days_ago), answered=False)

    make_summary(zid)  # stored summary for the patient hub (brief is generated live)
    print(f"  seeded showcase {SHOWCASE_EMAIL}: 5 elevated check-ins, 3 journals, "
          f"1 low-affect session ({session_date}), 18 SMS prompts (9-day gap), "
          f"focus=[suicidality, mood]")
    return zid


def main():
    db.init_db()
    print("Seeding synthetic test data…")

    # Prefer the local dev provider so the seeded patients show up when you log in
    # as provider@dev.local; fall back to creating a provider if it isn't there.
    existing_provider = db.get_user_by_email(LOCAL_PROVIDER_EMAIL)
    if existing_provider:
        provider_id = existing_provider["id"]
        print(f"  using local provider: {LOCAL_PROVIDER_EMAIL}")
    else:
        provider_id, _ = ensure_user(*FALLBACK_PROVIDER, "provider")

    configs = {
        "alex@test.com":   (30, 7, 5, 5),   # days, base_mood, base_stress, journal_count
        "jordan@test.com": (25, 6, 6, 3),
        "morgan@test.com": (30, 5, 7, 7),
    }

    for email, name in TEST_PATIENTS:
        pid, _ = ensure_user(email, name, "patient")
        db.assign_patient_to_provider(pid, provider_id)
        meds = PATIENT_MEDS.get(email, [])
        if meds:
            db.update_patient_profile(pid, current_medications=meds)
        days, base_mood, base_stress, journal_count = configs.get(email, (20, 6, 5, 4))
        n = make_checkins(pid, email, days, base_mood, base_stress)
        make_journals(pid, journal_count)
        make_summary(pid)
        print(f"  seeded {email}: {n} check-ins, {journal_count} journals, 1 summary")

    seed_zach_scenario(provider_id)

    login = LOCAL_PROVIDER_EMAIL if existing_provider else FALLBACK_PROVIDER[0]
    print("\nDone. Log in as the provider to see the seeded patients:")
    print(f"  Provider: {login}")
    print(f"  Patients: alex@test.com, jordan@test.com, morgan@test.com, {SHOWCASE_EMAIL} "
          f"(password: {PATIENT_PASSWORD})")
    print(f"  Showcase: {SHOWCASE_EMAIL} reproduces the suicidality-consolidation + "
          f"voice-divergence scenario — generate his psychiatry brief to verify.")


if __name__ == '__main__':
    main()
