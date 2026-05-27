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


def _submit_transcription_job(audio_url: str, speaker_labels: bool = True) -> str | None:
    """
    Submit a transcription job to AssemblyAI.
    Returns the job ID on success, None on failure.

    speaker_labels=True enables speaker diarization, which allows the
    extraction engine to distinguish patient speech from provider speech.
    """
    if not ASSEMBLYAI_API_KEY:
        logger.error("ASSEMBLYAI_API_KEY not set — transcription unavailable.")
        return None

    payload = {
        'audio_url':     audio_url,
        'speaker_labels': speaker_labels,
        'language_code': 'en',
    }

    try:
        resp = requests.post(
            f'{ASSEMBLYAI_BASE_URL}/transcript',
            json=payload,
            headers=_assemblyai_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        job_id = resp.json().get('id')
        logger.info("AssemblyAI job submitted: %s", job_id)
        return job_id
    except Exception as e:
        logger.error("AssemblyAI submission failed: %s", e)
        return None


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


def transcribe_audio_file(
    file_bytes: bytes,
    filename: str,
    patient_id: str,
    session_id: str,
) -> dict:
    """
    Full synchronous transcription pipeline:
      1. Upload audio to Supabase Storage
      2. Get a signed URL for AssemblyAI
      3. Submit transcription job
      4. Poll until complete

    This is the blocking version — suitable for short recordings or
    background threads. The public-facing route always calls the async wrapper.

    Returns:
        {
            'status':       'completed' | 'error' | 'timeout',
            'text':         str | None,
            'storage_path': str | None,
            'error':        str | None,
        }
    """
    if not ASSEMBLYAI_API_KEY:
        return {
            'status':       'error',
            'text':         None,
            'storage_path': None,
            'error':        'ASSEMBLYAI_API_KEY is not configured. Set this environment variable to enable audio transcription.',
        }

    # Step 1: Store audio
    storage_path = upload_audio_to_storage(file_bytes, filename, patient_id, session_id)
    if not storage_path:
        return {
            'status':       'error',
            'text':         None,
            'storage_path': None,
            'error':        'Failed to upload audio file to storage.',
        }

    # Step 2: Get signed URL for AssemblyAI
    signed_url = get_audio_signed_url(storage_path, expires_in=3600)
    if not signed_url:
        return {
            'status':       'error',
            'text':         None,
            'storage_path': storage_path,
            'error':        'Failed to generate a signed URL for the audio file.',
        }

    # Step 3: Submit transcription job
    job_id = _submit_transcription_job(signed_url)
    if not job_id:
        return {
            'status':       'error',
            'text':         None,
            'storage_path': storage_path,
            'error':        'Failed to submit transcription job to AssemblyAI.',
        }

    # Step 4: Poll until complete
    result = _poll_transcription_job(job_id)
    result['storage_path'] = storage_path
    return result


# ── Background processing ────────────────────────────────────────────────────

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
      transcribe → extract features → store features → update session status

    This runs after the upload route has returned 201 to the client.
    Session status progresses: 'transcribing' → 'extracting' → 'complete' | 'error'
    """
    import database as db
    from transcript_engine import extract_features

    logger.info("Background audio processing started: session=%s", session_id)

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
