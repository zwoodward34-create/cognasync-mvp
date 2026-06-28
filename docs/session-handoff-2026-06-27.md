# CognaSync — Session Hand-off (2026-06-27)

**Purpose:** Self-contained context to resume CognaSync work in a fresh Claude
session (including a different account). Paste this in along with the specific
task. Everything below reflects the actual state of the code as of this session.

**Relationship to the older hand-off:** `docs/session-handoff.md` (dated
2026-05-26) is the strategic spine (the pivot, the five-problems framing, buyers).
It is still useful for *strategy*, but its "Tier 2 spec divergences — not yet
fixed" list is now **mostly stale** — see "Already-fixed items" below. This
document supersedes it for the current engineering state.

---

## What this session worked on

Three threads, in order:

1. **Audio transcription accuracy** — assessed it, then improved it. This was the
   main thrust and is where the lasting value is.
2. **A spec-compliance repair** in the symptom-correlation engine (§8 minimum-N).
3. **Surfacing and committing prior uncommitted work** that was sitting in the
   working tree (a security/anti-abuse batch the user didn't realize was
   uncommitted), plus reviewing it.

---

## Thread 1 — Transcription accuracy (the headline work)

### Background
CognaSync transcribes patient/clinical audio via **AssemblyAI** (`audio_engine.py`),
model `universal-2`, with `ASSEMBLYAI_ENHANCED` set in Render (so diarization,
sentiment, entities, highlights are live). The transcript then feeds the
intelligence layer (`transcript_engine.py`) and acoustic biomarker layer
(`acoustic_engine.py`). The §16 medication-context and symptom signals depend on
medication **names** transcribing correctly.

### What was built
- **Clinical custom vocabulary.** Added `CLINICAL_VOCAB` (~86 psychiatric
  generics + brand names + clinical terms) in `audio_engine.py`, merged with the
  patient's own `current_medications` at call time (`_build_word_boost`,
  `_patient_medication_terms`). Patient meds are merged first so a 190-term cap
  never trims them.
- **A real benchmark harness** — `scripts/benchmark_transcription.py`. Runs audio
  through the actual transcription path and scores it against human reference
  transcripts on: **WER**, **clinical-term recall** (did medication names
  survive?), and **false positives** (did it invent drug names?). Includes
  **brand≡generic equivalence** (Wellbutrin counts as Bupropion) but keeps
  genuinely different drugs (Brexpiprazole ≠ Aripiprazole) as errors.
- **15 read-aloud reference scripts** in `data/benchmark/` (`note01.txt`…
  `note15.txt`) — realistic patient voice notes seeded with many drug names. The
  script IS the answer key, so reading one aloud and saving the matching audio
  (`note01.m4a`) gives a scorable pair. Plus `README.md` and `SETUP_api_key.md`
  (plain-language run + key-setup guides).
- **Env-controlled vocabulary mechanism** so production stays safe while
  experimenting:
  - `ASSEMBLYAI_VOCAB_MODE` = `keyterms` | `word_boost` | `off`
  - `ASSEMBLYAI_BOOST_PARAM` = `low` | `default` | `high` (only used by word_boost)

### The key finding (this is the important part)
Benchmark on 12 read-aloud recordings:

| Setting | WER | Clinical-term recall | Invented names |
|---|---|---|---|
| `word_boost` (default) | 4.9% | 66.7% (24/36) | 0 |
| `word_boost` (high) | 4.9% | 66.7% | 0 |
| **`keyterms`** | **4.5%** | **80.6% (29/36)** | 1 (Brexpiprazole) |

- `word_boost` is **empirically inert** on `universal-2` — `default` and `high`
  produced byte-identical output. `keyterms_prompt` is the parameter the model
  actually honors (and it boosts related variations too).
- Switching to `keyterms` lifted medication-name capture from 66.7% → 80.6% and
  even improved WER. **This is the validated improvement.**
- The 1 false positive: the model wrote *Brexpiprazole* where the script said
  *Aripiprazole* — a real wrong-drug swap (lookalike antipsychotic). Rare (1/12),
  and in production §16 cross-references the patient's actual med list, so an
  invented drug the patient isn't on generally won't create a false context.
- Caveat: read-aloud speech is cleaner than spontaneous patient speech, so these
  are best-case-floor numbers — strongest as a medication-name and
  voice/device-robustness test. Scoring real spontaneous recordings is the next
  fidelity step.

### ACTION REQUIRED to turn the win on in production
The production default is still `word_boost` (the safe no-op) so nothing changed
for live users automatically. **Set `ASSEMBLYAI_VOCAB_MODE=keyterms` in Render →
Environment** to activate the improvement. This was validated but may not be set
yet — verify.

### Decisions ratified (do not relitigate)
- `keyterms_prompt` over `word_boost` (data-backed).
- Production default kept at `word_boost` until `keyterms` was benchmark-proven,
  to avoid shipping an untested param that could error.

---

## Thread 2 — Symptom-correlation §8 repair

`find_symptom_correlations()` in `database.py` surfaced co-occurrence signals on
as few as 3 symptom-days, violating spec §8 (correlation claims need ≥10 matched
observations). Fixed the inner gate to `len(on_vals) < 10` (was `< 3`). The
symptom-level ≥3-day surfacing (§16, raw frequency) is unchanged.

`CLAUDE.md` §16 was updated to match (rule text `n ≥ 3` → `n ≥ 10` with an §8
cross-reference, and three worked examples bumped so they're internally
consistent).

**Decision ratified:** suppress sub-10 co-occurrences rather than surface them
tagged "preliminary." Rationale: under-surfacing is the only safe failure
direction for a clinical tool; a "preliminary" flag ignored downstream renders
identical to a confirmed correlation — exactly the false-confidence failure §8
exists to prevent.

---

## Thread 3 — Prior uncommitted work (surfaced + reviewed)

The working tree contained a coherent **security/anti-abuse batch** the user
hadn't realized was uncommitted. It is now committed as `e24c659`:
`feat(security): registration gating + honeypot, noindex, invite-token expiry,
SMS session TTL`. (That commit also swept in all of `database.py`, so the Thread-2
symptom gate landed there too — functionally fine, just bundled under the
security message.)

### Security review findings (batch is solid; nothing blocking)
- **Cleared on verification:** invite `expires_at` is `NOT NULL DEFAULT now()+7
  days`, so the new expiry filter can't strand invites (no back-fill needed);
  `patient_email` is `NOT NULL`, so the invite-email binding always has a value.
  The only behavioral change: invites now expire after **7 days** (was: valid
  indefinitely until consumed).
- **Remaining hardening (optional, none urgent):** `BETA_ACCESS_CODE` uses plain
  `==` (consider `hmac.compare_digest`); no tests for the registration gate /
  honeypot / email-mismatch (the committed test covers SMS short-checkin
  routing); `get_sms_session` uses naive `datetime.utcnow()` (fine if `sent_at`
  is UTC).

---

## Commit / repo status (VERIFY on the Mac with `git log --oneline -5`)

- `e24c659` — security batch + all of `database.py` (incl. the §8 symptom gate). **Committed.**
- Transcription commit — `audio_engine.py`, `CLAUDE.md` (§16), `scripts/benchmark_transcription.py`,
  `data/benchmark/` (reference `.txt` + guides), `.gitignore`. **Was being run at end of session;
  confirm it landed.** Suggested it excludes recordings/outputs via `.gitignore`
  (`*.m4a`, `*.hyp.txt`, `benchmark_results.json`).
- This hand-off doc — being (re)created; the first attempt never landed in the repo.

### Tooling gotchas learned this session (save the next session pain)
- The Claude sandbox **cannot write to `.git`** (stuck `index.lock`, permission
  denied) and **can't reach GitHub** (proxy 403). All `git add/commit/push` must
  be run by the user on their Mac. The sandbox's git view can also be **stale**,
  so don't trust it to confirm what's committed — check on the Mac.
- zsh (interactive) does **not** treat `#` lines as comments — pasted comment
  lines error with "command not found: #". Give paste blocks without `#` comments.
- `git add` **aborts entirely** if any listed path doesn't exist (`fatal:
  pathspec … did not match`) — so don't list files that may be missing.

---

## Already-fixed items (do NOT redo — the old hand-off lists these as open)
Verified fixed in current code: `FORBIDDEN_PATTERNS` entries (`you are manic`,
`this explains your`, `reduce your dose`); `_sanitize_output()` now logs on
substitution; Crash Risk formula matches spec §5 (`0.4/0.4/0.2` with documented
`0.5/0.5` fallback); `check_safety_signals()` has a `days` date filter. The
symptom §8 gate (Thread 2) was the last genuinely-open item from that list.

---

## Recommended next steps (priority order)

1. **Activate keyterms in production** — set `ASSEMBLYAI_VOCAB_MODE=keyterms` in
   Render (if not already done). This is the payoff of all the Thread-1 work.
2. **Re-score with brand≡generic equivalence** (free, no re-transcription):
   `ASSEMBLYAI_VOCAB_MODE=keyterms python scripts/benchmark_transcription.py
   --audio-dir data/benchmark --score-only` — gives the truer (≥80.6%) number to
   quote to buyers.
3. **Transcript confidence gating** — AssemblyAI returns a top-level `confidence`;
   it's captured nowhere. The acoustic side gates on recording quality, but the
   transcript text doesn't, so a garbled transcript silently feeds the
   lexical-diversity / coherence analysis. Capture, store, gate.
4. **Diarization role assignment** — `_format_utterances()` still labels
   PATIENT/PROVIDER by who-spoke-more-words. Fragile in psychiatry; let the
   provider confirm labels in the UI for clinical uploads.
5. **Score real spontaneous recordings** through the benchmark (with
   hand-corrected references) for the everyday accuracy number, not just the
   read-aloud floor.
6. **If keyterms recall plateaus**, evaluate **Universal-3 Pro** — the ceiling
   then is the acoustic model, not the vocabulary.
7. **Durable job queue** (RQ/Celery + Redis) before clinical volume — the async
   pipeline currently runs on daemon threads with a stuck-note recovery patch.
8. **Provider transcript/brief correction UI** — fixes records, builds trust, and
   generates labeled data for steps 2/5.

---

## How to resume in a fresh session

Paste this doc + the task. Suggested opener:

> Picking up CognaSync in a fresh session. Here's the hand-off. Before
> responding, read `CLAUDE.md` (§8, §16), `audio_engine.py` (the
> `ASSEMBLYAI_VOCAB_MODE` / `keyterms_prompt` logic), and
> `scripts/benchmark_transcription.py`, then confirm the current state. Next I
> want to: [task].

If continuing the most valuable thread, the task is **step 3 (transcript
confidence gating)** or **step 5 (benchmark real spontaneous audio)**.

---

End of hand-off.
