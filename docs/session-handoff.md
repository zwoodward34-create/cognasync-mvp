# CognaSync — Session Hand-off

**Purpose:** Self-contained context document for resuming CognaSync work in a fresh Claude session without re-establishing the full thread history. Paste this into a new session along with the specific task to continue.

**Last updated:** 2026-05-26 (updated to include safety audit, git snapshot strategy, and pivot architecture clarification)

---

## How to pick this up in a fresh session

Paste this document into a new session along with the specific task. Suggested opening:

> I'm picking up CognaSync work in a fresh session. Here's the hand-off document with full context. The specific thing I want to work on next is: [the task]. Please read `docs/five-problems-jonathan.md` and `CLAUDE.md` before responding, then confirm your understanding of the current state before we start.

Before any substantive work, verify you have read:
1. `CLAUDE.md` — master behavioral spec, 21 sections, authoritative on all AI behavior
2. `docs/five-problems-jonathan.md` — current strategic spine of the pivot
3. This file

---

## Who you are working with

Zach Woodward (`z.woodward34@gmail.com`), solo founder of CognaSync. He is the entire engineering and product team. William Graham is listed as co-founder but has contributed zero build work. This is an open strategic question to revisit after the pivot direction stabilizes (see Pending Work).

Zach's working preferences:
- Systems thinking, not symptom-fixing
- Depth over speed; honest assessment over comfort
- Prose over bullets unless content is genuinely list-like
- No filler ("Great question," "Absolutely," etc.)
- Push back when his framing is wrong rather than answering inside a flawed frame
- One clarifying question at a time, never multiple
- "Do not just tell me what you think I want to hear"

Modes: thinking (sparring partner), building (deliver something usable), decision (give the recommendation with reasoning), quick (fast direct answer when signaled). Default to thinking for open-ended, building for specific deliverables.

---

## What CognaSync is (the existing v1 platform)

A Flask + React + Supabase + Anthropic-API behavioral health pattern-tracking platform. Patients log daily check-ins (mood, sleep, stress, medications, advanced fields). AI generates four output modes: Mode A (patient post-check-in insight), Mode B (patient pre-appointment summary), Mode C (provider clinical summary), Mode D (provider dashboard threshold alert). Composite scores (Stability, Stim Load, Crash Risk, Nervous System Load, Sleep Disruption, Mood Distortion, Nutrition Stability, Dopamine Efficiency) are computed deterministically in Python before any AI call.

**The clinical-safety architecture is the moat.** Four non-negotiable rules embedded in every system prompt (never diagnose, never advise medication changes, describe data not clinical meaning, route crisis don't engage), forbidden-language post-processing sanitization, crisis interception before any AI call, methodology footer on every Mode C output. Full specification in `CLAUDE.md`.

**V1 is preserved and live.** The Render deployment reflects the current state of `main`. The v1 codebase is permanently tagged in git:
- `v1-original` → commit `f8efe73` — exact state before this session began
- `v1-safety-checkpoint` → commit `5ba6aba` — same codebase plus three safety fixes (see below)

To restore either: `git checkout v1-original` or `git checkout v1-safety-checkpoint`.

---

## Safety audit completed this session (Tier 1 fixes)

Three fixes were implemented in `claude_api.py` and committed to `main` as `v1-safety-checkpoint`. These are backward-compatible — they made the running app safer without changing any behavior.

**Fix 1 — CRISIS_KEYWORDS expanded (12 → 27 terms)**

Added to the keyword list:
- Spec §10 required (was missing): `'cut myself'`
- Algospeak / platform-evasion variants (entirely absent before): `'unalive'`, `'unaliving'`, `'kms'`, `'sewerslide'`
- IPTS burdensomeness language: `'better off without me'`, `'everyone would be better off'`, `'world would be better without me'`, `'burden to everyone'`
- Additional explicit phrases: `'take my own life'`, `'taking my own life'`, `'no reason to live'`, `'never wake up'`, `'sleep and never wake up'`, `'wish i was dead'`

**Fix 2 — Journal crisis interception in `generate_appointment_summary()`**

Before this fix, journal content passed to the model unscanned. Now:
- Scans the original `journal_data` content (not just 300-char excerpts) before any model invocation
- `audience='patient'` → immediate `CRISIS_RESPONSE` return; model is never called
- `audience='provider'` → crisis warning prepended as highest-priority flag in system prompt

**Fix 3 — `generate_therapy_summary()` brought to parity**

Before this fix, the therapy summary surface (full Mode C for therapists) had no safety coverage. Now:
- Function signature updated: `safety_flags=None, substance_flags=None` added
- Journal crisis interception added (provider-path only — therapy summaries are always clinician-facing)
- `substance_flags` wired into system prompt and user_content (same pattern as appointment summary provider path)
- `safety_flags` wired into system prompt and user_content (same pattern)

---

## Remaining spec divergences (Tier 2 — not yet fixed)

In priority order:

1. **Missing FORBIDDEN_PATTERNS entries** — `'you are manic'`, `'this explains your'`, `'reduce your dose'` are in the spec but absent from the list in `claude_api.py` line 45–54. Low-effort, high-compliance-value fix.

2. **`_sanitize_output()` fires silently** — when a forbidden pattern is caught, the function returns `None` with no log. Add `logging.getLogger(__name__).warning(...)` before the return so there's a record of what was caught and when.

3. **`max_tokens` mismatch in `generate_appointment_summary()`** — currently `1000`, spec §15 says `900`. One-line fix.

4. **Crash Risk formula mismatch** — `database.py:_compute_checkin_scores()` uses `(sd × 0.5) + (ns × 0.5)`. Spec §5 says `(SD × 0.4) + (NS × 0.4) + ((10 − Nutrition) × 0.2)`. Also uses `stress_score` where spec says `Anxiety`. Needs formula correction plus documented fallback when Nutrition is not available.

5. **`find_symptom_correlations()` minimum N** — code requires N≥3 on-days / N≥2 off-days; spec §8 says N≥10 matched observations for correlation claims. Raises false-confidence risk in outputs.

6. **`check_safety_signals()` has no date filter** — could surface signals from years ago as if recent. Add a `days` parameter filter to the journal query (spec default window: 60 days).

---

## The strategic pivot — confirmed direction

**What the pivot is:** Full replacement of CognaSync v1. Not an add-on, not a parallel product, not a patient-facing redesign. The patient-self-report-as-core-mechanic model is abandoned. The new product is a clinical intelligence layer sold to institutional buyers (VBC organizations first).

**What survives the pivot:** the deterministic scoring engine, all four safety rules, the forbidden-language sanitization, the symptom-correlation engine, the crisis interception layer, the interpersonal safety signal detector, the substance-pattern detector, the methodology footer architecture, Mode C provider summary surface, and the regulatory framework alignment.

**What the new product does:**

*Inputs:*
- 90-second weekly patient voice recording (the primary differentiator — captures affect, energy, pacing that text cannot)
- Integrations from pre-existing clinical tools (specific systems TBD — this needs to become a list of 3–4 named platforms before build begins: e.g. SimplePractice, Athena, a specific VBC care management platform)

*Outputs:*
- Pre-appointment brief for provider (Mode C equivalent — the primary product)
- Post-appointment summary for provider (documentation reduction)
- Post-appointment briefing for patient (plain-language recap)

**The gap to design for:** The appointment itself. If a transcript is obtainable (ambient recording, existing documentation tool), the post-appointment outputs become substantially more valuable. The architecture should leave room for transcript ingestion even if V1 doesn't require it.

**Why the 90-second voice note is the moat:** It is not transcription of what the provider said (Abridge, Nabla, Heidi, Microsoft DAX already do that). It is the patient's state between appointments captured in a form that carries signal text cannot. No competitor is doing this at the intersection of VBC + behavioral health.

**The integration question is currently open.** "Integrations from pre-existing tools" needs to resolve to a named list of 3–4 specific platforms before architecture work begins. The answer determines: who the actual buyer is, what the compliance requirements look like, what the sales motion is.

**Git branch for pivot work:** `pivot/intelligence-layer`. All new build work goes here. `main` stays on `v1-safety-checkpoint` (Render deployed) until pivot is ready to cut over.

---

## The strategic framing (five problems → three products → three buyers)

Source: `docs/five-problems-jonathan.md` — the most important strategic document in the repo.

**Five problems:**
1. Psychiatrists make medication decisions on incomplete, recall-based information
2. Half of psychiatric patients abandon medication within six months under conditions their provider never sees
3. Decompensation is detected too late, usually in the ED ($20K–$50K per hospitalization)
4. Patients cannot articulate what is happening to them between visits
5. Medication side effects present as patterns the patient cannot connect to the medication

**Three products (in build order):**
- Pre-visit brief (solves Problems 1 and 4)
- Persistence-risk early-warning (solves Problems 2 and 5)
- Decompensation-risk early-warning (solves Problem 3)

**Three buyers (in sales order):**
1. **VBC organizations first** — Headway, Talkiatry, LifeStance, Brave Health, Quartet. 3–6 month cycle. Buys the pre-visit brief. Proves operational ROI. Generates the case study.
2. **Pharma medical affairs / patient services second** — 18–24 month cycle, 7–8 figure contracts. Buys persistence-risk integration into manufacturer-funded patient support programs.
3. **Payers / regional Blues / Medicaid managed care third** — Longest cycle, largest contracts. Buys decompensation prevention. Requires real outcomes study.

---

## Meeting context (Graham / Cohen / Goldstein)

The 2026-05-25 meeting was a soft pass on CognaSync as currently conceived that became a real test of whether Zach can see the pivot. Jonathan Cohen's homework ask (five problems) was the test. The pilot proposal is the next test.

**Honest read:** The relationship is real. Jonathan is engaged. There is no near-term check. The product as currently conceived is not what he would fund. The product as it could be reshaped is what he is testing for.

**Open: John Graham's intent.** Not yet known whether John sees CognaSync as an Idealab Academy curriculum candidate, an angel investment opportunity, a Sunbelt Holdings strategic interest, or something else. Zach should reply directly and ask. Draft not yet written.

---

## Artifacts — where everything lives

All under `/Users/woodwardfamily/cognasync-mvp/`.

**Strategic:**
- `docs/five-problems-jonathan.md` — Strategic spine. Read this first.
- `docs/session-handoff.md` — This file.

**Meeting artifacts:**
- `docs/meeting-prep-graham-cohen.md` — Pre-meeting counterparty research and approach doc
- `docs/tomorrow-qa-prep.md` — Anticipated Q&A with prepared answers
- `docs/1-cognasync-executive-summary.pdf`, `docs/2-cognasync-mode-c-sample.pdf`, `docs/3-cognasync-safety-architecture.pdf` — PDFs printed for the meeting

**Positioning:**
- `/Users/woodwardfamily/Desktop/Zach's Vault/cognasync-bakers-dozen.docx` — Baker's Dozen 13-section positioning document (Idealab Academy format). Built and delivered this session.

**Core codebase:**
- `CLAUDE.md` — Master behavioral specification. 21 sections. Authoritative on all AI behavior.
- `claude_api.py` — All AI generation functions. Three safety fixes applied this session.
- `database.py` — Data access layer. Scoring engine, symptom correlations, substance patterns, safety signals.

**Research context (Passive Data Collection folder):**
- `/Users/woodwardfamily/Desktop/Passive Data Collection/AI Safety and Mental Health Language/` — Crisis language taxonomy (source for algospeak additions) and probabilistic safety architecture parameters

---

## Pending work — ordered by priority

**Immediate (build):**
1. Resolve the integration question: name the 3–4 specific platforms V1 will connect to. This unblocks architecture.
2. Design the voice recording ingestion pipeline — how the 90-second patient recording gets transcribed, scored, and fed into the pre-appointment brief.
3. Sketch the new data model — what does a "patient record" look like when the primary input is voice + integrations rather than daily check-ins?
4. Apply Tier 2 spec fixes to `claude_api.py` and `database.py` (listed above).

**Strategic / communications:**
5. Draft reply to John Graham asking for clarification on the Idealab Academy connection.
6. Draft reply to Jonathan Cohen delivering the five-problems document with a structured cadence proposal.
7. Draft reply to Alex Goldstein (brief, warm, confirms continued contact).
8. Build one-page pilot proposal for the VBC wedge (target org profile, pilot duration, success metrics, what each side commits).

**Longer-horizon:**
9. The William conversation — deliberate, not reactive. Revisit after pivot direction stabilizes. Match equity to ongoing contribution going forward.
10. Pharma RWE thesis validation — one conversation with a medical affairs / RWE lead asking whether they'd have a budget line for de-identified adherence and symptom-trajectory data on patients on their drug.

---

## Specifics worth remembering

**Idealab AZ deal mechanics.** Typical: $250K SAFE at $5–6M post-money cap + studio equity (workspace, advisors, network). Post-money cap = dilution is calculable at signing. Watch for studio equity >8–10% on top of the SAFE. At $5M post-money, a $250K SAFE = 5% dilution. Do not accept terms on the spot — 24–48 hours minimum on any equity decision.

**The competitive moat is the safety architecture, not the data collection.** Wearable ingestion is commoditized. The moat is: deterministic scoring discipline, clinical safety rules embedded in prompts, forbidden-language post-processing, methodology footer regulatory posture, symptom-correlation engine. Position these explicitly. Competitors do not have them.

**Ambient documentation competitors.** Abridge, Nabla, Heidi, Microsoft DAX are all transcribing what the provider said. CognaSync's voice note captures what the patient's state actually is between appointments. These are different things. Do not let the pivot description get conflated with the ambient documentation space.

---

## What this document does not cover

- The full meeting transcripts (CognaSync.docx) and the Idealab Academy deck. These were read in prior sessions; re-read if a specific question requires them.
- Detailed dilution scenarios and IP strategy. Live in `docs/tomorrow-qa-prep.md`.
- Specific contact information for target VBC organizations or pharma companies. None gathered.
- Any financial model. None built. Owed before the seed raise begins.

---

End of hand-off.
