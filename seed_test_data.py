"""
Run once to populate the database with realistic test data.
Usage: python seed_test_data.py
"""
import json
import random
import sqlite3
from datetime import date, timedelta
from werkzeug.security import generate_password_hash

import database as db

PATIENT_PASSWORD = "password123"

TEST_USERS = [
    ("alex@test.com",      "Alex Johnson",   "patient"),
    ("jordan@test.com",    "Jordan Smith",   "patient"),
    ("morgan@test.com",    "Morgan Lee",     "patient"),
    ("dr.smith@test.com",  "Dr. Sarah Smith","provider"),
]

PATIENT_MEDS = {
    "alex@test.com": [
        {"name": "sertraline", "dose": "100mg", "frequency": "daily"},
        {"name": "alprazolam", "dose": "0.5mg", "frequency": "as-needed"},
    ],
    "jordan@test.com": [
        {"name": "bupropion", "dose": "150mg", "frequency": "daily"},
    ],
    "morgan@test.com": [
        {"name": "escitalopram", "dose": "20mg", "frequency": "daily"},
        {"name": "quetiapine",   "dose": "50mg",  "frequency": "daily"},
    ],
}

SAMPLE_JOURNALS = [
    ("Had a tough day today. Started the morning anxious about the team meeting at work. "
     "I keep thinking I'll say something wrong and everyone will judge me. "
     "The meeting went okay, but I still feel unsettled. "
     "Can't stop replaying moments in my head, wondering if I came across badly."),

    ("Woke up feeling pretty good actually. Got outside for a walk and the air was crisp. "
     "For a little while I forgot about everything weighing on me. "
     "I notice that on days when I move my body, the evening feels less heavy."),

    ("Couldn't sleep again last night. Kept thinking about finances, work, the future. "
     "My brain doesn't seem to have an off switch. Tried the breathing exercise my doctor suggested, "
     "which helped a little. Feel exhausted today and less patient than I'd like to be with people."),

    ("Something shifted today. I'm not sure what, but I feel more like myself. "
     "I laughed at something genuinely funny — a real laugh, not a polite one. "
     "Small thing, but it felt meaningful. I want to hold onto that feeling."),

    ("I've been canceling plans with friends lately. I tell myself it's because I'm tired, "
     "but honestly I think I'm afraid of not having energy to be 'on.' "
     "I miss connecting with people but the thought of it is exhausting."),

    ("Had an okay week. Work has been stressful but manageable. "
     "I've been taking my medication consistently, which I'm proud of. "
     "My mood has been a bit flat but not bad. Just... neutral. "
     "I wonder if this is what stable feels like and I just don't recognize it."),

    ("Panic attack this morning before my appointment. "
     "Heart pounding, couldn't catch my breath, felt certain something terrible was about to happen. "
     "It passed in about 15 minutes but left me shaky for hours. "
     "I hate how unpredictable these are. I thought I was getting better."),
]

SAMPLE_SYMPTOMS = [
    "mild anxiety",
    "fatigue",
    "difficulty concentrating",
    "some tension",
    "restlessness",
    "low energy",
    "racing thoughts",
    "headache",
    "good energy today",
    "",
]


def random_mood(base=6, variance=2):
    return max(1, min(10, base + random.randint(-variance, variance)))


def make_checkins(patient_id, days, base_mood=6, base_stress=5):
    today = date.today()
    for i in range(days):
        entry_date = today - timedelta(days=i)
        # Skip a few days to be realistic (80% completion)
        if random.random() < 0.2:
            continue

        mood = random_mood(base_mood)
        sleep = round(random.uniform(5.0, 9.0), 1)
        stress = random_mood(base_stress)

        # Mood-sleep correlation: better sleep → better mood next day (approximated)
        if sleep >= 7.5:
            mood = min(10, mood + 1)
        elif sleep < 6:
            mood = max(1, mood - 1)

        meds_json = json.dumps(PATIENT_MEDS.get(
            next((e for e, _, _ in TEST_USERS if _ == 'patient'), None), []
        ))

        db.create_checkin(
            patient_id=patient_id,
            date_str=entry_date.isoformat(),
            time_of_day=random.choice(["morning", "afternoon", "evening"]),
            mood_score=mood,
            medications=[],
            sleep_hours=sleep,
            stress_score=stress,
            symptoms=random.choice(SAMPLE_SYMPTOMS),
            notes="",
        )


def make_journals(patient_id, count):
    today = date.today()
    chosen = random.sample(SAMPLE_JOURNALS, min(count, len(SAMPLE_JOURNALS)))
    for i, entry in enumerate(chosen):
        # Fake an AI analysis (avoids Claude API calls during seeding)
        analysis = (
            "This entry reflects a pattern of self-monitoring and thoughtfulness about internal states. "
            "There's a sense of awareness that's worth building on. "
            "Consider discussing sleep patterns and how they relate to overall energy with your provider. "
            "The observations you're making are clinically useful."
        )
        conn = sqlite3.connect(db.DATABASE_PATH)
        entry_date = (today - timedelta(days=i * 3)).isoformat()
        conn.execute(
            'INSERT INTO journal_entries (patient_id, entry_type, raw_entry, ai_analysis, created_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (patient_id, 'free_flow', entry, analysis, entry_date, entry_date)
        )
        conn.commit()
        conn.close()


def make_summary(patient_id):
    today = date.today()
    start = today - timedelta(days=14)
    text = (
        "Over the past two weeks, mood has averaged approximately 6.5/10, showing modest variability "
        "correlating with sleep quality. On nights with 7+ hours of sleep, next-day mood scores were "
        "consistently higher. Stress levels have been moderate, averaging around 5/10, with brief spikes "
        "on workdays.\n\n"
        "Journal entries reflect themes of anticipatory anxiety (particularly before social and work obligations) "
        "and moments of genuine self-awareness. The patient notes that physical activity has a noticeable "
        "positive effect on mood, which may be worth discussing as a behavioral strategy.\n\n"
        "Medication adherence appears consistent. Key topics for the upcoming appointment: (1) sleep quality "
        "and its link to mood stability, (2) strategies for managing anticipatory anxiety, "
        "(3) social withdrawal patterns noted in two recent journal entries."
    )
    db.create_summary(
        patient_id=patient_id,
        summary_text=text,
        date_range_start=start.isoformat(),
        date_range_end=today.isoformat(),
        generated_by='seed',
    )


def main():
    db.init_db()
    print("Seeding test data…")

    provider_id = None
    patient_ids = {}

    # Create users
    for email, name, role in TEST_USERS:
        existing = db.get_user_by_email(email)
        if existing:
            print(f"  Skipping {email} (already exists)")
            uid = existing['id']
        else:
            uid = db.create_user(
                email=email,
                password_hash=generate_password_hash(PATIENT_PASSWORD),
                full_name=name,
                role=role,
            )
            print(f"  Created {role}: {name} ({email})")

        if role == 'provider':
            provider_id = uid
        else:
            patient_ids[email] = uid

    # Assign patients to provider
    if provider_id:
        for email, pid in patient_ids.items():
            db.assign_patient_to_provider(pid, provider_id)
            print(f"  Assigned {email} to provider")

    # Set patient medications in profiles
    for email, pid in patient_ids.items():
        meds = PATIENT_MEDS.get(email, [])
        if meds:
            db.update_patient_profile(pid, current_medications=meds)

    # Seeding config per patient
    configs = {
        "alex@test.com":   (30, 7,  5,  5),   # days, base_mood, base_stress, journal_count
        "jordan@test.com": (25, 6,  6,  3),
        "morgan@test.com": (30, 5,  7,  7),
    }

    for email, pid in patient_ids.items():
        cfg = configs.get(email, (20, 6, 5, 4))
        days, base_mood, base_stress, journal_count = cfg
        make_checkins(pid, days, base_mood, base_stress)
        make_journals(pid, journal_count)
        make_summary(pid)
        print(f"  Seeded data for {email}")

    print("\nDone! Test accounts:")
    print(f"  Patients: alex@test.com, jordan@test.com, morgan@test.com")
    print(f"  Provider: dr.smith@test.com")
    print(f"  Password: {PATIENT_PASSWORD}")


if __name__ == '__main__':
    main()
