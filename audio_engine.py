"""
audio_engine.py — CognaSync Audio Transcription Layer

Handles audio file upload, transcription, and handoff to the transcript
intelligence pipeline. Transcription is handled by AssemblyAI via their
REST API (no extra SDK dependency — uses requests, which ships with Flask).

DESIGN PRINCIPLES:
  1. The audio layer is a pre-processing step. Its only job is to produce
     transcript text. Once text is produced, extract_features() takes over
     with all its existing safety guarantees intact.
  2. Audio processing runs in a background thread so upload routes return
     immediately. Session status in clinical_sessions reflects progress.
  3. Audio files are stored in Supabase Storage before transcription begins
     so the raw file is always available for re-processing or audit.
  4. If ASSEMBLYAI_API_KEY is not set, transcription fails gracefully with
     a clear error stored on the session — no silent failures.

REQUIRED ENVIRONMENT VARIABLES:
  ASSEMBLYAI_API_KEY   — AssemblyAI API key (get one at assemblyai.com)
  SUPABASE_URL         — already set for database layer
  SUPABASE_SERVICE_KEY — already set for database layer

STORAGE SETUP:
  Create a Supabase Storage bucket named 'session-audio' with:
    - Private access (not public)
    - Max file size: 500 MB (covers ~8 hour sessions at 128kbps MP3)
  Run in Supabase SQL Editor:
    insert into storage.buckets (id, name, public) values ('session-audio', 'session-audio', false);
    create policy "Provider can upload audio" on storage.objects for insert
      to authenticated with check (bucket_id = 'session-audio');
    create policy "Provider can read audio" on storage.objects for select
      to authenticated using (bucket_id = 'session-audio');

ACCEPTED AUDIO FORMATS:
  MP3, MP4, WAV, M4A, FLAC, OGG, WebM
  AssemblyAI handles all of these natively.

TRANSCRIPTION TIMING:
  AssemblyAI processes audio at roughly 5x real-time.
  A 50-minute session (~3000 seconds) takes ~600 seconds to transcribe.
  The background thread polls every 5 seconds up to MAX_POLL_SECONDS.
"""

import io
import logging
import os
import threading
import time
import uuid

import requests

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

ASSEMBLYAI_API_KEY   = os.environ.get('ASSEMBLYAI_API_KEY', '')
ASSEMBLYAI_BASE_URL  = 'https://api.assemblyai.com/v2'
MAX_POLL_SECONDS     = 900    # 15 minutes — covers a 75-minute session
POLL_INTERVAL        = 5      # seconds between status checks
MAX_AUDIO_BYTES      = 500 * 1024 * 1024   # 500 MB hard limit

ACCEPTED_MIME_TYPES = {
    'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/m4a',
    'audio/wav', 'audio/wave', 'audio/x-wav',
    'audio/flac', 'audio/ogg', 'audio/webm',
    'video/mp4', 'video/webm',   # some recorders export video containers
}

ACCEPTED_EXTENSIONS = {
    '.mp3', '.mp4', '.m4a', '.wav', '.flac', '.ogg', '.webm', '.aac',
}


# ── Validation ───────────────────────────────────────────────────────────────

def validate_audio_file(filename: str, file_bytes: bytes, mime_type: str | None = None) -> tuple[bool, str]:
    """
    Validate an uploaded audio file.
    Returns (is_valid, error_message). error_message is '' on success.
    """
    if not file_bytes:
        return False, 'File is empty.'

    if len(file_bytes) > MAX_AUDIO_BYTES:
        mb = len(file_bytes) / (1024 * 1024)
        return False, f'File too large ({mb:.0f} MB). Maximum is 500 MB.'

    ext = os.path.splitext(filename.lower())[1] if filename else ''
    if ext not in ACCEPTED_EXTENSIONS:
        if mime_type and mime_type.split(';')[0].strip() in ACCEPTED_MIME_TYPES:
            pass   # MIME type confirms audio even if extension is odd
        else:
            return False, f'Unsupported file type ({ext or "unknown"}). Accepted: MP3, M4A, WAV, FLAC, OGG, WebM.'

    return True, ''


# ── Supabase Storage ─────────────────────────────────────────────────────────

def upload_audio_to_storage(
    file_bytes: bytes,
    filename: str,
    patient_id: str,
    session_id: str,
) -> str | None:
    """
    Upload audio bytes to Supabase Storage bucket 'session-audio'.
    Returns the storage path (not a public URL) on success, None on failure.

    Path format: <patient_id>/<session_id>/<filename>
    This structure groups audio by patient and session for easy retrieval.
    """
    from database import supabase_admin   # imported here to avoid circular import

    ext      = os.path.splitext(filename)[1].lower() or '.audio'
    safe_name = f"{session_id}{ext}"
    path      = f"{patient_id}/{session_id}/{safe_name}"

    try:
        supabase_admin.storage.from_('session-audio').upload(
            path,
            file_bytes,
            file_options={'content-type': _mime_for_ext(ext), 'upsert': 'false'},
        )
        logger.info("Audio uploaded to storage: %s", path)
        return path
    except Exception as e:
        logger.error("Audio storage upload failed (path=%s): %s", path, e)
        return None


def get_audio_signed_url(storage_path: str, expires_in: int = 3600) -> str | None:
    """
    Create a short-lived signed URL for a stored audio file.
    AssemblyAI requires a publicly accessible URL for transcription.
    """
    from database import supabase_admin

    try:
        result = supabase_admin.storage.from_('session-audio').create_signed_url(
            storage_path, expires_in
        )
        return result.get('signedURL') or result.get('signed_url')
    except Exception as e:
        logger.error("Failed to create signed URL for %s: %s", storage_path, e)
        return None


# ── AssemblyAI transcription ─────────────────────────────────────────────────

def _assemblyai_headers() -> dict:
    return {'authorization': ASSEMBLYAI_API_KEY, 'content-type': 'application/json'}


def _submit_transcription_job(audio_url: str) -> tuple:
    """
    Submit a transcription job to AssemblyAI.
    Returns (job_id, error_message). job_id is None on failure.
    """
    if not ASSEMBLYAI_API_KEY:
        return None, 'ASSEMBLYAI_API_KEY is not configured.'

    # speaker_labels is a paid feature — omit it so free-tier keys work.
    # speech_models is now required by AssemblyAI; universal-2 works on all tiers.
    payload = {
        'audio_url':    audio_url,
        'speech_models': ['universal-2'],
        'language_code': 'en',
    }

    try:
        resp = requests.post(
            f'{ASSEMBLYAI_BASE_URL}/transcript',
            json=payload,
            headers=_assemblyai_headers(),
            timeout=30,
        )
        if not resp.ok:
            body = resp.text[:300]
            logger.error("AssemblyAI submission HTTP %s: %s", resp.status_code, body)
            return None, f'AssemblyAI returned {resp.status_code}: {body}'
        job_id = resp.json().get('id')
        if not job_id:
            return None, f'AssemblyAI response missing job id: {resp.text[:200]}'
        logger.info("AssemblyAI job submitted: %s", job_id)
        return job_id, None
    except Exception as e:
        logger.error("AssemblyAI submission failed: %s", e)
        return None, str(e)


def _poll_transcription_job(job_id: str) -> dict:
    """
    Poll AssemblyAI until the job completes or times out.

    Returns:
        {
            'status':     'completed' | 'error' | 'timeout',
            'text':       str | None,           # full transcript text
            'utterances': list | None,          # speaker-diarized utterances
            'error':      str | None,
        }
    """
    deadline = time.time() + MAX_POLL_SECONDS
    url = f'{ASSEMBLYAI_BASE_URL}/transcript/{job_id}'

    while time.time() < deadline:
        try:
            resp = requests.get(url, headers=_assemblyai_headers(), timeout=15)
            resp.raise_for_status()
            data = resp.json()
            status = data.get('status')

            if status == 'completed':
                transcript_text = data.get('text', '')
                utterances = data.get('utterances') or []

                # Format with speaker labels if diarization succeeded
                if utterances:
                    transcript_text = _format_utterances(utterances)

                logger.info("AssemblyAI job %s completed (%d chars)", job_id, len(transcript_text))
                return {'status': 'completed', 'text': transcript_text, 'utterances': utterances, 'error': None}

            elif status == 'error':
                err = data.get('error', 'Unknown transcription error')
                logger.error("AssemblyAI job %s failed: %s", job_id, err)
                return {'status': 'error', 'text': None, 'utterances': None, 'error': err}

            # Still queued or processing — wait and retry
            logger.debug("AssemblyAI job %s status: %s", job_id, status)
            time.sleep(POLL_INTERVAL)

        except Exception as e:
            logger.warning("Poll error for job %s: %s — retrying", job_id, e)
            time.sleep(POLL_INTERVAL)

    logger.error("AssemblyAI job %s timed out after %ds", job_id, MAX_POLL_SECONDS)
    return {'status': 'timeout', 'text': None, 'utterances': None,
            'error': f'Transcription timed out after {MAX_POLL_SECONDS // 60} minutes.'}


def _format_utterances(utterances: list) -> str:
    """
    Convert AssemblyAI speaker-diarized utterances to a labeled transcript.
    Speaker A → PATIENT, Speaker B → PROVIDER (heuristic: assume A speaks first
    and is typically the patient, B is the clinician).

    The heuristic is imperfect. Providers can relabel if needed.
    More robust labeling requires knowing who speaks first from external context.
    """
    label_map = {'A': 'PATIENT', 'B': 'PROVIDER'}
    lines = []
    for u in utterances:
        speaker = u.get('speaker', 'UNKNOWN')
        label   = label_map.get(speaker, f'SPEAKER_{speaker}')
        text    = u.get('text', '').strip()
        if text:
            lines.append(f'{label}: {text}')
    return '\n'.join(lines)


def _upload_bytes_to_assemblyai(file_bytes: bytes) -> str | None:
    """
    Upload raw audio bytes directly to AssemblyAI's upload endpoint.
    Returns the temporary CDN URL AssemblyAI provides, or None on failure.
    This avoids the Supabase Storage dependency entirely.
    """
    try:
        resp = requests.post(
            f'{ASSEMBLYAI_BASE_URL}/upload',
            headers={'authorization': ASSEMBLYAI_API_KEY},
            data=file_bytes,
            timeout=120,
        )
        resp.raise_for_status()
        url = resp.json().get('upload_url')
        logger.info("Audio uploaded to AssemblyAI CDN (%d bytes)", len(file_bytes))
        return url
    except Exception as e:
        logger.error("AssemblyAI binary upload failed: %s", e)
        return None


def transcribe_audio_file(
    file_bytes: bytes,
    filename: str,
    patient_id: str,
    session_id: str,
) -> dict:
    """
    Full synchronous transcription pipeline using direct binary upload to AssemblyAI.
    No Supabase Storage bucket required.

    Returns:
        {
            'status':       'completed' | 'error' | 'timeout',
            'text':         str | None,
            'storage_path': None,          # reserved for future storage
            'error':        str | None,
        }
    """
    if not ASSEMBLYAI_API_KEY:
        return {
            'status':       'error',
            'text':         None,
            'storage_path': None,
            'error':        'ASSEMBLYAI_API_KEY is not configured. Add it to your Render environment variables.',
        }

    # Upload bytes directly to AssemblyAI (no Supabase Storage needed)
    audio_url = _upload_bytes_to_assemblyai(file_bytes)
    if not audio_url:
        return {
            'status':       'error',
            'text':         None,
            'storage_path': None,
            'error':        'Failed to upload audio to AssemblyAI.',
        }

    # Submit transcription job
    job_id, submit_err = _submit_transcription_job(audio_url)
    if not job_id:
        return {
            'status':       'error',
            'text':         None,
            'storage_path': None,
            'error':        submit_err or 'Failed to submit transcription job to AssemblyAI.',
        }

    # Poll until complete
    result = _poll_transcription_job(job_id)
    result['storage_path'] = None
    return result


# ── Background processing ────────────────────────────────────────────────────

def _run_acoustic_extraction(file_bytes: bytes, filename: str,
                              session_id: str, session_date: str) -> dict | None:
    """
    Write audio bytes to a temp file, run the acoustic biomarker extractor,
    and map the raw measurements to the §24 controlled vocabulary.

    Returns the vocabulary-mapped dict (with 'session_date' added) on success,
    or None if extraction fails for any reason.  Failures are non-fatal — the
    transcript pipeline continues regardless.

    The temp file is deleted whether or not extraction succeeds.
    """
    import tempfile
    try:
        from acoustic_engine import extract_acoustic_features, map_features_to_vocabulary
    except ImportError as e:
        logger.warning("acoustic_engine unavailable — skipping acoustic extraction: %s", e)
        return None

    ext      = os.path.splitext(filename)[1].lower() or '.audio'
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        raw     = extract_acoustic_features(tmp_path)
        vocab   = map_features_to_vocabulary(raw)
        vocab['session_date'] = session_date

        logger.info(
            "Acoustic extraction complete: session=%s quality=%s speech_rate=%s "
            "prosody=%s pauses=%s arousal=%s pattern=%s",
            session_id,
            raw.get('quality'),
            vocab.get('speech_rate'),
            vocab.get('prosody'),
            vocab.get('pauses'),
            vocab.get('arousal'),
            vocab.get('clinical_pattern_type'),
        )

        # ── Acoustic affect (VAD) inference ───────────────────────────────────
        # Runs the pre-trained wav2vec2 regression model on the decoded waveform.
        # Produces continuous valence/arousal/dominance scores — provider-only,
        # never surfaced to patients, framed as acoustic correlates not diagnoses.
        affect_result = None
        try:
            from affect_model import run_affect_inference
            # Re-use the already-decoded waveform from acoustic_engine internals.
            # We decode again here to keep affect_model independent — the decode
            # is fast and deterministic.
            import subprocess
            proc = subprocess.run(
                ['ffmpeg', '-v', 'quiet', '-nostdin', '-i', tmp_path,
                 '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'],
                capture_output=True,
            )
            if proc.returncode == 0 and proc.stdout:
                import numpy as np
                y = np.frombuffer(proc.stdout, dtype=np.float32).copy()
                y = np.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
                affect_result = run_affect_inference(y)
                affect_result['session_date'] = session_date
                logger.info(
                    "Affect inference complete: session=%s valence=%.3f arousal=%.3f "
                    "dominance=%.3f pattern=%s model_available=%s",
                    session_id,
                    affect_result.get('valence') or 0,
                    affect_result.get('arousal') or 0,
                    affect_result.get('dominance') or 0,
                    affect_result.get('pattern'),
                    affect_result.get('model_available'),
                )
        except Exception as ae:
            logger.warning("Affect inference failed for session %s: %s", session_id, ae)
            affect_result = None

        return {'vocabulary': vocab, 'raw': raw, 'affect': affect_result}

    except Exception as e:
        logger.warning("Acoustic extraction failed for session %s: %s", session_id, e)
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _background_process_audio(
    session_id: str,
    patient_id: str,
    file_bytes: bytes,
    filename: str,
    session_date: str,
    session_type: str,
) -> None:
    """
    Background thread target. Full pipeline:
      acoustic extraction (waveform) + transcribe → extract features →
      merge acoustic data → store features → update session status

    Acoustic extraction runs on the raw bytes before transcription begins —
    the two analyses are independent and measuring different things.
    Transcription failure aborts the pipeline; acoustic failure is non-fatal.

    Session status progresses: 'transcribing' → 'extracting' → 'complete' | 'error'
    """
    import database as db
    from transcript_engine import extract_features

    logger.info("Background audio processing started: session=%s", session_id)
    try:
        _run_audio_pipeline(db, extract_features, session_id, patient_id,
                            file_bytes, filename, session_date, session_type)
    except Exception as exc:
        logger.exception("Unhandled exception in audio pipeline for session %s", session_id)
        try:
            db.update_clinical_session_status(session_id, 'error',
                                              error_message=f'Internal error: {exc}')
        except Exception:
            pass


def _run_baseline_lifecycle(db, patient_id, session_id, session_date,
                             acoustic_result, voice_recording_role):
    """
    Branch on voice_recording_role to create, update, or compare against baseline.
    Populates acoustic_result['vocabulary']['baseline_deviation'] for Phase 3.
    Non-fatal — failures are logged but do not abort the pipeline.
    """
    raw_features = acoustic_result.get('raw') or {}
    vocab        = acoustic_result.get('vocabulary') or {}
    recorded_at  = f'{session_date}T00:00:00'

    try:
        if voice_recording_role == 'voice_memo_anchor':
            quality = raw_features.get('quality', 'poor')
            if quality in ('good', 'fair'):
                db.create_voice_baseline_from_anchor(
                    patient_id=patient_id,
                    session_id=session_id,
                    recorded_at=recorded_at,
                    acoustic_features=raw_features,
                )
                logger.info("Voice baseline anchor created: patient=%s session=%s quality=%s",
                            patient_id, session_id, quality)
            else:
                db._tag_session_voice_role(session_id, 'voice_memo_excluded')
                logger.warning(
                    "Anchor excluded — quality too low (%s): patient=%s session=%s",
                    quality, patient_id, session_id,
                )

        elif voice_recording_role == 'voice_memo_baseline':
            role, promoted = db.add_baseline_training_recording(
                patient_id=patient_id,
                session_id=session_id,
                recorded_at=recorded_at,
                acoustic_features=raw_features,
            )
            if promoted:
                logger.info("Voice baseline ESTABLISHED: patient=%s", patient_id)
            elif role == 'voice_memo_excluded':
                logger.info("Phase 2 recording excluded: patient=%s session=%s", patient_id, session_id)

        elif voice_recording_role == 'voice_memo_standard':
            baseline = db.get_voice_baseline(patient_id)
            if baseline and baseline.get('status') in ('established', 'stale'):
                deviation = db.compute_baseline_deviation(raw_features, baseline)
                if deviation:
                    vocab['baseline_deviation'] = deviation
                    acoustic_result['vocabulary'] = vocab
                    logger.info("Baseline deviation computed: session=%s", session_id)
            db._tag_session_voice_role(session_id, 'voice_memo_standard')

    except Exception as e:
        logger.warning("Baseline lifecycle error (non-fatal): session=%s error=%s", session_id, e)


def _merge_acoustic_into_extraction(extraction, acoustic_result, session_id):
    """
    Merge acoustic biomarker results into an extract_features() result dict so
    store_session_features() persists them alongside transcript-derived scores.

    Mutates `extraction` in place. No-op when acoustic_result is falsy.
    Shared by _run_audio_pipeline (clinical session uploads) and
    process_voice_note (voice-note uploads from any entry point).
    """
    if not acoustic_result:
        return

    if extraction.get('scores') is None:
        extraction['scores'] = {}
    extraction['scores']['acoustic_features'] = acoustic_result
    # Store affect dimensions separately for clean retrieval
    if acoustic_result.get('affect'):
        extraction['scores']['affect_dimensions'] = acoustic_result['affect']

    # If transcript speech_features are low-confidence or null, promote the
    # acoustic vocabulary labels so the brief has something to work with.
    transcript_sf = (extraction.get('scores') or {}).get('speech_features')
    if not transcript_sf or transcript_sf.get('confidence') == 'low':
        acoustic_vocab = acoustic_result.get('vocabulary', {})
        if extraction.get('scores') is not None:
            extraction['scores']['speech_features'] = {
                k: acoustic_vocab.get(k)
                for k in ('speech_rate', 'prosody', 'pauses', 'speech_coherence',
                          'arousal', 'vocal_affect', 'severity_note', 'confidence',
                          'baseline_deviation')
            }
            extraction['scores']['speech_features']['source'] = 'acoustic'
        logger.info(
            "Using acoustic-derived speech features for session %s "
            "(transcript speech_features were %s)",
            session_id,
            'absent' if not transcript_sf else 'low-confidence',
        )


def _run_audio_pipeline(db, extract_features, session_id, patient_id,
                         file_bytes, filename, session_date, session_type):
    """Inner pipeline extracted so the outer function can wrap it with a safety net."""
    logger.info("Pipeline started: session=%s", session_id)

    # ── Acoustic biomarker extraction (waveform, §24) ──────────────────────
    # Runs on raw bytes before transcription — independent of transcript content.
    # Result merged into extraction dict so store_session_features persists it.
    acoustic_result = _run_acoustic_extraction(file_bytes, filename,
                                               session_id, session_date)

    # ── Baseline lifecycle (voice memos only) ──────────────────────────────
    # Determines Phase 1/2/3, creates/updates baseline, and populates
    # baseline_deviation in the acoustic vocabulary before the merge below.
    # Clinical session uploads (provider-uploaded audio) skip this entirely.
    if session_type == 'voice_note':
        voice_recording_role = db.determine_voice_recording_role(patient_id)
        if acoustic_result:
            _run_baseline_lifecycle(db, patient_id, session_id, session_date,
                                    acoustic_result, voice_recording_role)
    else:
        db._tag_session_voice_role(session_id, 'clinical_session')

    # ── Transcription ─────────────────────────────────────────────
    db.update_clinical_session_status(session_id, 'transcribing')
    transcription = transcribe_audio_file(file_bytes, filename, patient_id, session_id)

    if transcription['status'] != 'completed' or not transcription['text']:
        error_msg = transcription.get('error') or 'Transcription failed.'
        logger.error("Transcription failed for session %s: %s", session_id, error_msg)
        db.update_clinical_session_status(session_id, 'error', error_message=error_msg)
        return

    transcript_text = transcription['text']
    logger.info("Transcription complete for session %s (%d chars)", session_id, len(transcript_text))

    # Store the transcript text on the session record
    db.store_session_transcript(session_id, transcript_text, transcription.get('storage_path'))

    # ── Feature extraction ────────────────────────────────────────
    db.update_clinical_session_status(session_id, 'extracting')
    # Fetch population flags so the graduated crisis scorer (spec §23) can apply
    # population-aware modifiers. Returns {} if no flags are set — safe default.
    population_flags = db.get_patient_population_flags(patient_id)
    extraction = extract_features(
        transcript_text=transcript_text,
        session_date=session_date,
        session_type=session_type,
        population_flags=population_flags or None,
    )

    # ── Merge acoustic features into extraction result ────────────────────────
    # Both acoustic_features and affect_dimensions stored in scores so
    # store_session_features persists them alongside transcript-derived scores.
    _merge_acoustic_into_extraction(extraction, acoustic_result, session_id)

    # ── Persist features ──────────────────────────────────────────
    db.store_session_features(
        session_id=session_id,
        patient_id=patient_id,
        extraction_result=extraction,
        extraction_model=os.environ.get('CLAUDE_MODEL', 'claude-haiku-4-5-20251001'),
    )

    # store_session_features calls update_clinical_session_status internally
    # via the processing_status field, but we force 'complete' or 'error' here
    # to be explicit about the audio pipeline outcome.
    if extraction.get('error'):
        db.update_clinical_session_status(session_id, 'error', error_message=extraction['error'])
        logger.error("Feature extraction failed for session %s: %s", session_id, extraction['error'])
    else:
        db.update_clinical_session_status(session_id, 'complete')
        logger.info("Audio processing complete: session=%s", session_id)


def process_audio_session_async(
    session_id: str,
    patient_id: str,
    file_bytes: bytes,
    filename: str,
    session_date: str,
    session_type: str,
) -> None:
    """
    Start background transcription + extraction for an uploaded audio session.
    Returns immediately. Progress is tracked via clinical_sessions.processing_status.

    Status lifecycle visible to the provider UI:
      'pending'      → session created, audio not yet uploaded
      'transcribing' → audio uploaded, AssemblyAI job running
      'extracting'   → transcript ready, feature extraction in progress
      'complete'     → features stored, session ready for brief generation
      'error'        → something failed; processing_error has details
    """
    t = threading.Thread(
        target=_background_process_audio,
        args=(session_id, patient_id, file_bytes, filename, session_date, session_type),
        daemon=True,
        name=f'audio-{session_id[:8]}',
    )
    t.start()
    logger.info("Audio processing thread started: session=%s thread=%s", session_id, t.name)


# ── Voice-note pipeline (shared by SMS patient flow + provider upload) ───────

def process_voice_note(
    voice_note_id: str,
    patient_id: str,
    provider_id: str | None,
    file_bytes: bytes,
    filename: str,
    session_date: str | None = None,
    audio_already_stored_url: str | None = None,
) -> None:
    """
    Unified synchronous voice-note pipeline. Used by both audio entry points:
      - SMS patient flow (api_voice_submit) — audio already stored, pass
        audio_already_stored_url so the storage step is skipped.
      - Provider upload flow (api_provider_upload_voice_note) — audio stored here.

    Steps:
      1. Store audio in the 'voice-notes' bucket (non-fatal on failure)
      2. Transcribe via AssemblyAI (fatal on failure)
      3. Acoustic biomarker extraction from the waveform (non-fatal)
      4. Create clinical_sessions row (session_type='voice_note')
      5. Baseline lifecycle (Phase 1/2/3 voice memo handling)
      6. Semantic feature extraction via Claude + acoustic merge
      7. Persist session_features and link voice_notes.clinical_session_id

    Progress is tracked via voice_notes.processing_status:
      'pending' → 'processing' → 'complete' | 'error'
    """
    import database as db
    from transcript_engine import extract_features

    if not session_date:
        from datetime import datetime as _dt
        session_date = _dt.utcnow().date().isoformat()

    def _vn_error(reason: str) -> None:
        try:
            db.supabase_admin.table('voice_notes').update({
                'processing_status': 'error',
                'processing_error':  reason,
            }).eq('id', voice_note_id).execute()
        except Exception as ue:
            logger.error("voice_notes error-status update failed: id=%s error=%s",
                         voice_note_id, ue)

    try:
        # ── 1. Audio storage (skipped when the caller already uploaded) ──────
        if not audio_already_stored_url:
            ext          = os.path.splitext(filename)[1].lower() or '.webm'
            storage_path = f"{patient_id}/{voice_note_id}{ext}"
            try:
                db.supabase_admin.storage.from_('voice-notes').upload(
                    path=storage_path,
                    file=file_bytes,
                    file_options={'content-type': _mime_for_ext(ext)},
                )
                audio_url = db.supabase_admin.storage.from_('voice-notes').get_public_url(storage_path)
                if audio_url:
                    db.supabase_admin.table('voice_notes').update(
                        {'audio_url': audio_url}).eq('id', voice_note_id).execute()
            except Exception as se:
                logger.warning("Voice-note storage upload failed (non-fatal): id=%s error=%s",
                               voice_note_id, se)

        # ── 2. Transcription (fatal on failure) ──────────────────────────────
        result = transcribe_audio_file(
            file_bytes=file_bytes,
            filename=filename,
            patient_id=patient_id,
            session_id=str(voice_note_id),
        )
        if not (result.get('status') == 'completed' and result.get('text')):
            _vn_error(result.get('error') or 'Transcription failed')
            return

        transcript_text = result['text']
        db.supabase_admin.table('voice_notes').update({
            'transcript':        transcript_text,
            'processing_status': 'processing',
        }).eq('id', voice_note_id).execute()

        # ── 3. Acoustic biomarker extraction (non-fatal) ─────────────────────
        # Runs on raw bytes — independent of transcript content. The session_id
        # is only used for logging here; the clinical session does not exist yet.
        acoustic_result = _run_acoustic_extraction(
            file_bytes=file_bytes,
            filename=filename,
            session_id=str(voice_note_id),
            session_date=session_date,
        )

        # ── 4. Resolve provider + create clinical session ─────────────────────
        # clinical_sessions.provider_id is NOT NULL — fall back to the patient's
        # active provider relationship when the caller didn't supply one.
        if not provider_id:
            provider = db.get_provider_for_patient(patient_id)
            provider_id = provider.get('id') if provider else None
        if not provider_id:
            _vn_error('No provider linked to patient — cannot create clinical session')
            return

        session_id = db.store_clinical_session(
            provider_id=provider_id,
            patient_id=patient_id,
            session_date=session_date,
            session_type='voice_note',
            transcript_raw=transcript_text,
            transcript_source='voice_note',
        )
        if not session_id:
            _vn_error('Failed to create clinical session record')
            return

        # ── 5. Baseline lifecycle (voice memos only, non-fatal internally) ───
        if acoustic_result:
            voice_recording_role = db.determine_voice_recording_role(patient_id)
            _run_baseline_lifecycle(db, patient_id, session_id, session_date,
                                    acoustic_result, voice_recording_role)

        # ── 6. Semantic extraction via Claude + acoustic merge ───────────────
        extraction = extract_features(
            transcript_text=transcript_text,
            session_date=session_date,
            session_type='voice_note',
            population_flags=db.get_patient_population_flags(patient_id) or None,
        )
        _merge_acoustic_into_extraction(extraction, acoustic_result, session_id)

        # ── 7. Persist features + link voice note to its clinical session ────
        db.store_session_features(
            session_id=session_id,
            patient_id=patient_id,
            extraction_result=extraction,
        )
        db.supabase_admin.table('voice_notes').update({
            'processing_status':   'complete',
            'clinical_session_id': str(session_id),
        }).eq('id', voice_note_id).execute()

        logger.info("Voice-note pipeline complete: voice_note=%s session=%s",
                    voice_note_id, session_id)

    except Exception as exc:
        logger.exception("Voice-note pipeline failed: voice_note=%s", voice_note_id)
        _vn_error(str(exc))


def process_voice_note_async(
    voice_note_id: str,
    patient_id: str,
    provider_id: str | None,
    file_bytes: bytes,
    filename: str,
    session_date: str | None = None,
    audio_already_stored_url: str | None = None,
) -> None:
    """
    Start background processing for a voice note. Returns immediately.
    Progress is tracked via voice_notes.processing_status.
    """
    t = threading.Thread(
        target=process_voice_note,
        args=(voice_note_id, patient_id, provider_id, file_bytes, filename,
              session_date, audio_already_stored_url),
        daemon=True,
        name=f'voice-note-{str(voice_note_id)[:8]}',
    )
    t.start()
    logger.info("Voice-note processing thread started: voice_note=%s thread=%s",
                voice_note_id, t.name)


# ── Utilities ────────────────────────────────────────────────────────────────

def _mime_for_ext(ext: str) -> str:
    return {
        '.mp3':  'audio/mpeg',
        '.mp4':  'audio/mp4',
        '.m4a':  'audio/mp4',
        '.wav':  'audio/wav',
        '.flac': 'audio/flac',
        '.ogg':  'audio/ogg',
        '.webm': 'audio/webm',
        '.aac':  'audio/aac',
    }.get(ext, 'audio/octet-stream')
