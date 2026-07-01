# Spec: Process voice notes on arrival, not at brief time

Status: proposed · Author: pairing session 2026-07-01 · Scope: `app.py`, `audio_engine.py`, `database.py`

## Desired outcome

A patient voice note becomes a fully-processed `clinical_session` (features + speech/acoustic signals extracted) **within seconds of its transcript being ready**, independent of whether any provider ever opens the patient or generates a brief. "Processed" means `processing_status = 'complete'` with a `session_features` row.

Success test: submit a voice note → within one processing cycle, its `clinical_session` is `complete` and selectable in the intel dashboard, with no brief generated and no provider having viewed the patient.

## Current state (why this exists)

Two things are true in prod today:

1. A voice note's transcript is produced by the audio pipeline and stored on the `voice_notes` row, but the `voice_notes` row is **not** itself a `clinical_session`. The two are bridged by `voice_notes.clinical_session_id` (nullable FK).

2. The **only** runtime path that promotes a voice note into a `clinical_session` and extracts features is the brief-time "orphan backfill" loop (`app.py`, `api_intel_generate_brief`). That loop has two defects:
   - It creates the `clinical_session` row *before* extraction succeeds, so a failure between create and store strands the row at `processing_status = 'pending'` with no features.
   - It builds its `known_dates` skip-set from **all** existing sessions (including `pending` ones), so once a date has a stranded session, every future brief run `continue`s past it. The strand is permanent.

Consequence observed in prod: five voice-note sessions sat `pending` for up to two weeks, invisible to selection and absent from briefs, until manually backfilled.

The reconciler added on 2026-07-01 (`_reconcile_pending_sessions`, triggered on intel-dashboard load and summary generation) is a **safety net**, not the fix. It unsticks rows when a provider happens to view the patient. A patient nobody opens still waits. This spec closes that gap.

Supporting evidence the platform was *designed* for arrival-time processing: `clinical_sessions` already carries a partial index `idx_clinical_sessions_pending` on `(processing_status, created_at) WHERE processing_status = 'pending'` — a queue index for a worker that was never fully wired.

## The change

Move promotion + extraction to the moment the transcript lands, and reuse the same claim-and-extract primitive the reconciler uses.

### Inputs / trigger point

The transcript-ready event is where `audio_engine` writes a transcript back onto a `voice_notes` row (the voice-note pipeline that already runs for SMS and provider audio). At that point, and in the same code path:

1. **Promote once (idempotent).** If `voice_notes.clinical_session_id` is null, create a `clinical_session` (`transcript_source='voice_note'`, `session_type='voice_note'`, `transcript_raw=<transcript>`) and write its id back to `voice_notes.clinical_session_id`. If it is already set, skip creation. This makes the bridge the single source of truth for "has this voice note been promoted?" and removes the date-based dedup entirely.
2. **Process immediately.** Run the existing `claim_session_for_processing(session_id)` → `extract_features(...)` → `store_session_features(...)` sequence in a background thread (the pattern `process_audio_session_async` already establishes). On failure, the row lands in `error`, which the UI now surfaces with a Retry.

### Handoffs / ordering

- The atomic `pending → extracting` claim (added 2026-07-01) already guarantees the arrival-time processor and the reconciler safety net can never both extract the same row. No new locking needed.
- Promotion keys on `voice_notes.clinical_session_id`, not on `session_date` — this is what kills the `known_dates` trap. Two voice notes on the same day now both promote, each to its own session.

### Changes to the orphan loop

Delete the create-and-extract responsibility from `api_intel_generate_brief`'s orphan loop. Briefs should *read* completed sessions, not *produce* them. If a voice note is somehow still unpromoted at brief time (e.g. a note that arrived before this change shipped), the reconciler safety net covers it. Keep the reconciler; retire the orphan loop's write path.

## Failure points to design for

- **Transcript write succeeds, promotion/extract thread dies.** Row is `pending` with no features. Covered by the reconciler safety net on next dashboard/summary load, and by a periodic sweep (below).
- **Duplicate promotion under concurrency.** Guard the promotion with a conditional update on `voice_notes.clinical_session_id IS NULL` (mirror the `claim_session_for_processing` pattern) so only one writer wins.
- **Extraction consistently fails on a specific transcript** (e.g. empty/garbled). `store_session_features` already routes to `error`; do not auto-retry in a loop. The UI Retry is the human escape hatch.

## Backstop: periodic sweep

Even with arrival-time processing, add a low-frequency job (cron/worker) that runs `get_pending_transcript_sessions()` across all patients and reconciles anything older than, say, 15 minutes. This is the true decoupling — it makes processing independent of *any* user action, not just brief generation or dashboard views. The `idx_clinical_sessions_pending` index exists precisely to make this query cheap.

## Rollout & verification

1. Ship arrival-time promotion+processing behind the existing background-thread pattern; keep the reconciler and add the sweep.
2. Retire the orphan loop's write path in the same release (leave briefs read-only over sessions).
3. Verify: submit a voice note in dev, confirm the `clinical_session` reaches `complete` with a `session_features` row **without** loading the dashboard or generating a brief. Then confirm a deliberately-failed extraction lands in `error` and Retry recovers it.
4. Monitor: alert if any `clinical_session` stays `pending` with a non-empty `transcript_raw` for > 30 minutes. That condition should now be impossible; if it fires, the arrival path regressed.

## Out of scope

Audio that never transcribed (the `audio_upload` transcription failure case) belongs to the audio pipeline's own error handling, not this ingestion path. This spec covers transcript-ready → features only.
