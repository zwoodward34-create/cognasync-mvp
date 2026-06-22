"""
Seed the database with synthetic test data for local/dev use (Supabase-native).

Creates 3 patients (as Supabase auth users + profiles), assigns them to the local
dev provider (`provider@dev.local` if it exists, else creates `dr.smith@test.com`),
and seeds check-ins, journals, and a summary for each.

Idempotent: re-running skips users that already exist.

Usage: python seed_test_data.py
"""
import random
from datetime import date, timedelta

import database as db

PATIENT_PASSWORD = "DevPass123!"
LOCAL_PROVIDER_EMAIL = "provider@dev.local"   # created by scripts/local.sh seed

TEST_PATIENTS = [
    ("alex@test.com",   "Alex Johnson"),
    ("jordan@test.com", "Jordan Smith"),
    ("morgan@test.com", "Morgan Lee"),
]
FALLBACK_PROVIDER = ("dr.smith@test.com", "Dr. Sarah Smith")

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

SAMPLE_SYMPTOMS = [
    "mild anxiety", "fatigue", "difficulty concentrating", "some tension",
    "restlessness", "low energy", "racing thoughts", "headache", "", "",
]


def random_mood(base=6, variance=2):
    return max(1, min(10, base + random.randint(-variance, variance)))


def ensure_user(email, name, role):
    """Return the user id, creating the Supabase auth user + profile if needed."""
    existing = db.get_user_by_email(email)
    if existing:
        print(f"  exists: {email} ({existing['role']})")
        return existing["id"]
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
    }).execute()
    print(f"  created {role}: {name} ({email})")
    return uid


def make_checkins(patient_id, days, base_mood, base_stress):
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
        db.create_checkin(
            patient_id=patient_id,
            date_str=entry_date.isoformat(),
            time_of_day=random.choice(["morning", "afternoon", "evening"]),
            mood_score=mood,
            medications=[],
            sleep_hours=sleep,
            stress_score=random_mood(base_stress),
            symptoms=random.choice(SAMPLE_SYMPTOMS),
            notes="",
            checkin_type="full",
        )
        n += 1
    return n


def make_journals(patient_id, count):
    analysis = (
        "This entry reflects self-monitoring and awareness of internal states. "
        "Worth discussing sleep patterns and energy with your provider."
    )
    for entry in random.sample(SAMPLE_JOURNALS, min(count, len(SAMPLE_JOURNALS))):
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
        provider_id = ensure_user(*FALLBACK_PROVIDER, "provider")

    configs = {
        "alex@test.com":   (30, 7, 5, 5),   # days, base_mood, base_stress, journal_count
        "jordan@test.com": (25, 6, 6, 3),
        "morgan@test.com": (30, 5, 7, 7),
    }

    for email, name in TEST_PATIENTS:
        pid = ensure_user(email, name, "patient")
        db.assign_patient_to_provider(pid, provider_id)
        meds = PATIENT_MEDS.get(email, [])
        if meds:
            db.update_patient_profile(pid, current_medications=meds)
        days, base_mood, base_stress, journal_count = configs.get(email, (20, 6, 5, 4))
        n = make_checkins(pid, days, base_mood, base_stress)
        make_journals(pid, journal_count)
        make_summary(pid)
        print(f"  seeded {email}: {n} check-ins, {journal_count} journals, 1 summary")

    login = LOCAL_PROVIDER_EMAIL if existing_provider else FALLBACK_PROVIDER[0]
    print("\nDone. Log in as the provider to see the seeded patients:")
    print(f"  Provider: {login}")
    print(f"  Patients: alex@test.com, jordan@test.com, morgan@test.com (password: {PATIENT_PASSWORD})")


if __name__ == '__main__':
    main()
