# CognaSync Provider Quick-Start Guide

CognaSync gives you structured behavioral data from your patients between sessions — mood, sleep, stress, medication adherence, and journal themes — surfaced as plain-language patterns before you walk into the room. The AI describes what the data shows. Clinical interpretation is yours.

This guide covers the four things you'll actually do in the platform.

---

## Goal: Get oriented on your patient panel

When you log in, you land on the **Provider Dashboard**. Each row is one patient. At a glance you can see:

- **Last check-in** — days since their most recent submission. Gaps matter.
- **Mood avg** and **Stress avg** — rolling averages for the past 30 days
- **Adherence** — medication log adherence rate as a percentage
- **Alerts** — color-coded flags that have crossed clinical thresholds

**Alert levels:**
- 🔴 **Urgent** — statistically significant declining trend (R² ≥ 0.25, p ≤ 0.05) or active crisis signal
- 🟡 **Watch** — elevated stress trend, low adherence below 80%, or sustained Crash Risk
- 🔵 **Informational** — notable but not threshold-crossing patterns

A patient row with no alerts and recent check-ins is stable. Start with the flagged ones.

---

## Goal: Prepare for an appointment

This is the primary workflow. From the patient's detail page, click **Start Appointment Session** to open the appointment workspace.

**What the workspace gives you:**

**AI Clinical Summary (Mode C)** — generated from the patient's check-ins and shared journals over the selected review window. Click **Generate Summary** to produce it. It covers:
- Mood, stress, sleep, and energy averages with trend direction
- Medication adherence rate and timing consistency
- Advanced data averages (exercise, alcohol units, social quality, workload friction) — only if the patient has been using advanced check-ins
- 2–3 qualitative themes from journal language
- Flagged threshold crossings with supporting data

**AI-Suggested Questions** — 3–5 interview questions generated from this patient's specific data. These are derived from their actual numbers (e.g., "Mood has averaged 3.8/10 this period — what's been contributing to that?"), not generic prompts. Use them as starting points, not scripts.

**Journals** — shared journal entries from the review window appear in the workspace. You're reading what the patient chose to share.

**Notes and care plan** — the workspace has fields for session notes, care plan updates, guided Q&A, and action items. Everything autosaves. You can also log the next appointment date.

**To complete a session:** fill in your notes and click **Complete Appointment**. This closes the workspace and saves the record to the appointment history on the patient's detail page.

---

## Goal: Go deeper on a patient

From a patient's detail page, click **View Trends** to open the full trend chart view.

The trends page shows time-series charts for mood, sleep, stress, energy, and medication adherence. You can adjust the lookback window (7, 14, 30, 60, 90 days).

**Medication timing panel** — if the patient has been logging medication events with times, the timing panel shows:
- Average time taken per medication
- Timing variability (standard deviation in minutes)
- Days with high Stim Load (combined caffeine + stimulant intake ≥ 7/10)

Timing variability > 60 minutes across 7+ days is surfaced as a pattern. This is observational — it describes what was logged, not what it means clinically.

**Interaction flags** — if the patient's medication list contains combinations with known interaction signals, these appear on the detail page. These are reference flags, not clinical warnings.

---

## Goal: Respond to a crisis flag

A patient row with a 🔴 crisis indicator means their recent check-in or journal entry contained language matching crisis detection criteria (explicit statements of self-harm or suicidal ideation).

When this flag is active:
- The patient was shown only the static crisis resource block — no AI-generated content was returned to them
- The check-in or journal entry was still saved so you can see it
- The patient's row in your dashboard is highlighted

After you've followed up with the patient directly, you can clear the flag by opening their detail page and clicking **Resolve Crisis Flag**. This does not delete the underlying entry — it marks the flag as addressed in the record.

Do not use the resolve action before making contact with the patient.

---

## What the AI does and doesn't do

This matters for how you read the outputs.

**What it does:** describes patterns in numbers. Average mood over a period. Trend direction. Co-occurrences between variables. Language themes in journals.

**What it doesn't do:** diagnose, suggest medication changes, or claim causality. Phrases like "this indicates," "you are depressed," or "reduce your dose" are explicitly blocked from all outputs. If you see language like that, flag it — it's a bug.

**Minimum data requirements:** the AI will not generate trend language from fewer than 7 check-ins, will not call a pattern statistically significant without p ≤ 0.05 and R² ≥ 0.25, and will not generate a summary if there are no check-ins or journals in the selected window. Sparse data is stated as sparse — it's not extrapolated.

**Missing fields ≠ zero.** If a patient hasn't logged advanced check-in data, those fields are marked "not recorded" — not assumed to be zero. Absence of data is not the same as absence of the behavior.

The summaries and suggested questions are inputs to the clinical conversation. They don't replace your judgment — they give you a cleaner starting point.
