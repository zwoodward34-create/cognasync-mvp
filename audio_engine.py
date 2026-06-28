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
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

ASSEMBLYAI_API_KEY   = os.environ.get('ASSEMBLYAI_API_KEY', '')
ASSEMBLYAI_BASE_URL  = 'https://api.assemblyai.com/v2'
MAX_POLL_SECONDS     = 900    # 15 minutes — covers a 75-minute session
POLL_INTERVAL        = 5      # seconds between status checks
MAX_AUDIO_BYTES      = 500 * 1024 * 1024   # 500 MB hard limit

# Set ASSEMBLYAI_ENHANCED=true in Render env vars to enable paid-tier features:
# speaker_labels, sentiment_analysis, entity_detection, auto_highlights.
# Leave unset (or set to false/0) to run on free-tier keys without error.
ASSEMBLYAI_ENHANCED = os.environ.get('ASSEMBLYAI_ENHANCED', '').lower() in ('1', 'true', 'yes')

# Boost strength for the clinical word_boost vocabulary: 'low' | 'default' | 'high'.
# 'default' balances recovering missed drug names against the risk of the model
# inventing medication names that were never said (false positives that would
# poison §16 medication-context detection). Raise to 'high' via this env var and
# re-run scripts/benchmark_transcription.py to measure both recall AND false
# positives before setting it in the Render production environment.
ASSEMBLYAI_BOOST_PARAM = (os.environ.get('ASSEMBLYAI_BOOST_PARAM', 'default').strip().lower()
                          or 'default')
if ASSEMBLYAI_BOOST_PARAM not in ('low', 'default', 'high'):
    ASSEMBLYAI_BOOST_PARAM = 'default'

# How the clinical vocabulary is injected into the transcription request:
#   'keyterms'   → keyterms_prompt (universal-2's actual term-boosting parameter;
#                  also boosts related variations of each term)
#   'word_boost' → legacy word_boost + boost_param
#   'off'        → no vocabulary injection (clean baseline)
# Benchmark finding (2026-06-27): word_boost/boost_param had ZERO measurable
# effect on universal-2 output — default and high produced byte-identical results
# — so word_boost appears inert on this model. Production default is kept at
# 'word_boost' (a known no-op that cannot error) until 'keyterms' is validated
# against scripts/benchmark_transcription.py and promoted via this env var.
ASSEMBLYAI_VOCAB_MODE = (os.environ.get('ASSEMBLYAI_VOCAB_MODE', 'word_boost').strip().lower()
                         or 'word_boost')
if ASSEMBLYAI_VOCAB_MODE not in ('keyterms', 'word_boost', 'off'):
    ASSEMBLYAI_VOCAB_MODE = 'word_boost'

ACCEPTED_MIME_TYPES = {
    'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/m4a',
    'audio/wav', 'audio/wave', 'audio/x-wav',
    'audio/flac', 'audio/ogg', 'audio/webm',
    'video/mp4', 'video/webm',   # some recorders export video containers
}

ACCEPTED_EXTENSIONS = {
    '.mp3', '.mp4', '.m4a', '.wav', '.flac', '.ogg', '.webm', '.aac',
}

# ── Custom transcription vocabulary ──────────────────────────────────────────
# Passed to AssemblyAI as `word_boost` on every job. General ASR routinely
# mangles low-frequency clinical tokens — especially psychiatric drug names —
# and those exact tokens drive downstream medication-context and symptom
# correlation signals (CLAUDE.md §16). Boosting them protects accuracy on the
# words that matter most clinically.
#
# Kept under 200 entries so it stays compatible with the universal-2
# `keyterms_prompt` feature if we migrate to it later. To extend this with the
# patient's actual medication list at call time, merge rows from the
# `medications` table into the payload in _submit_transcription_job().
CLINICAL_VOCAB = [
    # Antidepressants — SSRIs / SNRIs / atypicals (generic)
    'Fluoxetine', 'Sertraline', 'Paroxetine', 'Citalopram', 'Escitalopram',
    'Fluvoxamine', 'Venlafaxine', 'Desvenlafaxine', 'Duloxetine', 'Bupropion',
    'Mirtazapine', 'Trazodone', 'Vortioxetine', 'Vilazodone', 'Amitriptyline',
    'Nortriptyline', 'Clomipramine', 'Imipramine',
    # Mood stabilizers
    'Lithium', 'Lamotrigine', 'Valproate', 'Divalproex', 'Carbamazepine',
    'Oxcarbazepine', 'Topiramate',
    # Antipsychotics
    'Aripiprazole', 'Risperidone', 'Quetiapine', 'Olanzapine', 'Ziprasidone',
    'Lurasidone', 'Paliperidone', 'Clozapine', 'Haloperidol', 'Cariprazine',
    'Brexpiprazole', 'Asenapine',
    # Stimulants / ADHD
    'Methylphenidate', 'Dexmethylphenidate', 'Amphetamine', 'Lisdexamfetamine',
    'Atomoxetine', 'Guanfacine',
    # Anxiolytics / benzodiazepines
    'Alprazolam', 'Lorazepam', 'Clonazepam', 'Diazepam', 'Buspirone',
    'Hydroxyzine',
    # Sleep agents
    'Zolpidem', 'Eszopiclone', 'Ramelteon',
    # Common brand names
    'Prozac', 'Zoloft', 'Lexapro', 'Effexor', 'Cymbalta', 'Wellbutrin',
    'Remeron', 'Abilify', 'Seroquel', 'Zyprexa', 'Risperdal', 'Latuda',
    'Klonopin', 'Xanax', 'Ativan', 'Lamictal', 'Depakote', 'Vyvanse',
    'Adderall', 'Ritalin', 'Concerta', 'Strattera', 'Trintellix',
    # Clinical terms commonly mistranscribed
    'anhedonia', 'hypomania', 'dysphoria', 'dissociation', 'rumination',
    'psychomotor', 'akathisia', 'titration', 'titrate', 'milligram',
    'milligrams',
]


def _patient_medication_terms(patient_id: str | None) -> list[str]:
    """Medication-name terms from the patient's own profile for word_boost.

    Reads patient_profiles.current_medications (JSONB array of
    {name, dose, dose_unit}) and returns each distinct name plus its individual
    alphabetic tokens — so 'Wellbutrin XL' boosts both the phrase and
    'Wellbutrin'. The patient's actual regimen is the highest-value boost: these
    are the exact names that must transcribe correctly for §16
    medication-context detection. Non-fatal — any error returns [].
    """
    if not patient_id:
        return []
    try:
        import database as db
        profile = db.get_patient_profile(patient_id)
    except Exception as e:
        logger.warning("word_boost: medication lookup failed for patient %s: %s", patient_id, e)
        return []
    if not profile:
        return []

    terms: list[str] = []
    for m in (profile.get('current_medications') or []):
        if not isinstance(m, dict):
            continue
        name = (m.get('name') or '').strip()
        if not name:
            continue
        terms.append(name)
        for tok in name.replace('/', ' ').split():
            tok = tok.strip('.,()')
            if len(tok) > 3 and tok.isalpha():
                terms.append(tok)
    return terms


def _build_word_boost(patient_id: str | None, max_terms: int = 190) -> list[str]:
    """Merge the static clinical vocab with the patient's own medication names.

    De-duplicates case-insensitively and caps the total so it stays within
    AssemblyAI limits and remains compatible with the universal-2
    keyterms_prompt path (≤200). Patient-specific medication terms are added
    FIRST so that if the cap trims anything it trims the least-critical tail of
    the static vocab, never the patient's actual regimen.
    """
    seen: set[str] = set()
    merged: list[str] = []
    for term in _patient_medication_terms(patient_id) + CLINICAL_VOCAB:
        key = term.lower()
        if key and key not in seen:
            seen.add(key)
            merged.append(term)
    return merged[:max_terms]


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


def _submit_transcription_job(audio_url: str, patient_id: str | None = None) -> tuple:
    """
    Submit a transcription job to AssemblyAI.
    Returns (job_id, error_message). job_id is None on failure.

    When patient_id is provided, the patient's own medication names are merged
    into the word_boost vocabulary (highest-value, patient-specific boost).
    """
    if not ASSEMBLYAI_API_KEY:
        return None, 'ASSEMBLYAI_API_KEY is not configured.'

    # speech_models is now required by AssemblyAI; universal-2 works on all tiers.
    # Enhanced features (speaker_labels, sentiment_analysis, entity_detection,
    # auto_highlights) require a paid plan — gated by ASSEMBLYAI_ENHANCED env var.
    payload = {
        'audio_url':     audio_url,
        'speech_models': ['universal-2'],
        'language_code': 'en',
    }
    # Inject the clinical vocabulary (static list + patient meds) using whichever
    # mechanism ASSEMBLYAI_VOCAB_MODE selects. keyterms_prompt is universal-2's
    # real term-boosting parameter; word_boost is the legacy (and empirically
    # inert) path; 'off' is the clean baseline. The vocabulary list is identical
    # across modes so the benchmark isolates the *mechanism*, not the word list.
    _vocab = _build_word_boost(patient_id)
    if _vocab and ASSEMBLYAI_VOCAB_MODE == 'keyterms':
        payload['keyterms_prompt'] = _vocab
    elif _vocab and ASSEMBLYAI_VOCAB_MODE == 'word_boost':
        payload['word_boost'] = _vocab
        payload['boost_param'] = ASSEMBLYAI_BOOST_PARAM
    # 'off' → inject nothing.
    if ASSEMBLYAI_ENHANCED:
        payload['speaker_labels']      = True
        payload['sentiment_analysis']  = True
        payload['entity_detection']    = True
        payload['auto_highlights']     = True

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
                return {
                    'status':            'completed',
                    'text':              transcript_text,
                    'utterances':        utterances,
                    'words':             data.get('words') or [],
                    'entities':          data.get('entities') or [],
                    'auto_highlights':   (data.get('auto_highlights_result') or {}).get('results') or [],
                    'sentiment_results': data.get('sentiment_analysis_results') or [],
                    'error':             None,
                }

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

    Label assignment uses a word-count heuristic:
    - Count total words spoken by each speaker across all utterances.
    - The speaker with the MOST words is labeled PATIENT. Patients consistently
      produce more verbal content in therapy/psychiatry sessions; providers ask
      questions while patients elaborate.
    - If the top two speakers are within 20% of each other in word count the
      data is too ambiguous to override, so the function falls back to the
      original first-utterance order (A → PATIENT, B → PROVIDER).
    - The fallback also applies when there is only one speaker with any words.
    - Any speakers beyond the two most active are labeled SPEAKER_C, SPEAKER_D,
      etc. (unchanged behavior for 3+ speaker recordings).

    Edge cases handled:
    - Empty utterance list → returns empty string.
    - Single speaker → that speaker is labeled PATIENT.
    - More than 2 speakers → top two are assigned by word count (with the
      20% ambiguity check); extras become SPEAKER_<letter>.
    """
    if not utterances:
        return ''

    # --- build per-speaker word counts and first-appearance order ---
    word_counts: dict[str, int] = {}
    first_order: list[str] = []          # speakers in order of first utterance
    for u in utterances:
        speaker = u.get('speaker', 'UNKNOWN')
        text    = u.get('text', '').strip()
        if not text:
            continue
        words = len(text.split())
        word_counts[speaker] = word_counts.get(speaker, 0) + words
        if speaker not in first_order:
            first_order.append(speaker)

    # --- determine label map ---
    if not word_counts:
        return ''

    # Sort speakers by descending word count
    ranked = sorted(word_counts.keys(), key=lambda s: word_counts[s], reverse=True)

    label_map: dict[str, str] = {}

    if len(ranked) == 1:
        # Only one speaker — label as PATIENT regardless of letter
        label_map[ranked[0]] = 'PATIENT'
    else:
        top, second = ranked[0], ranked[1]
        top_words    = word_counts[top]
        second_words = word_counts[second]

        # Ambiguity check: are the two most active speakers within 20% of each other?
        ambiguous = (top_words > 0 and
                     abs(top_words - second_words) / top_words <= 0.20)

        if ambiguous:
            # Fall back to first-utterance order: first speaker → PATIENT
            fallback_patient  = first_order[0] if len(first_order) > 0 else top
            fallback_provider = first_order[1] if len(first_order) > 1 else second
            label_map[fallback_patient]  = 'PATIENT'
            label_map[fallback_provider] = 'PROVIDER'
        else:
            # Word-count heuristic: most words → PATIENT
            label_map[top]    = 'PATIENT'
            label_map[second] = 'PROVIDER'

        # Any additional speakers get positional labels (C, D, …)
        extras = [s for s in ranked[2:]]
        for i, spk in enumerate(extras):
            label_map[spk] = f'SPEAKER_{chr(ord("C") + i)}'

    # --- build transcript lines ---
    lines = []
    for u in utterances:
        speaker = u.get('speaker', 'UNKNOWN')
        text    = u.get('text', '').strip()
        if text:
            label = label_map.get(speaker, f'SPEAKER_{speaker}')
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

    # Submit transcription job (patient_id merges their meds into word_boost)
    job_id, submit_err = _submit_transcription_job(audio_url, patient_id=patient_id)
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
                              session_id: str, session_date: str,
                              session_type: str | None = None) -> dict | None:
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
        from acoustic_engine import (extract_acoustic_features,
                                     map_features_to_vocabulary,
                                     infer_capture_channel)
    except ImportError as e:
        logger.warning("acoustic_engine unavailable — skipping acoustic extraction: %s", e)
        return None

    ext      = os.path.splitext(filename)[1].lower() or '.audio'
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        channel = infer_capture_channel(filename, session_type)
        raw     = extract_acoustic_features(tmp_path)
        vocab   = map_features_to_vocabulary(raw, capture_channel=channel)
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

    # Reconcile the two independent arousal estimates (RMS-amplitude heuristic
    # vs. wav2vec2 VAD) into one first-class field instead of leaving them in
    # separate silos. Convergent → higher confidence; divergent → its own
    # signal (CLAUDE.md §5). Non-fatal.
    try:
        from acoustic_engine import reconcile_arousal
        extraction['scores']['arousal_reconciliation'] = reconcile_arousal(
            acoustic_result.get('vocabulary'), acoustic_result.get('affect'),
        )
    except Exception as _ar:
        logger.warning("Arousal reconciliation failed (non-fatal) for session %s: %s",
                       session_id, _ar)

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
                                               session_id, session_date,
                                               session_type=session_type)

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
        # For clinical sessions, attempt a baseline comparison if a baseline exists.
        # _run_baseline_lifecycle() is intentionally NOT called here — it is designed
        # for the voice-note Phase 1/2/3 lifecycle only.
        acoustic_baseline_context = None
        if acoustic_result is not None:
            try:
                baseline = db.get_voice_baseline(patient_id)
                if baseline and baseline.get('status') in ('established', 'stale'):
                    deviation = db.compute_baseline_deviation(
                        acoustic_result.get('raw') or {}, baseline
                    )
                    if deviation:
                        acoustic_baseline_context = deviation
                        logger.info(
                            "Clinical session baseline deviation computed: session=%s",
                            session_id,
                        )
            except Exception as _bl_err:
                logger.warning(
                    "Clinical session baseline lookup failed (non-fatal): "
                    "session=%s error=%s",
                    session_id, _bl_err,
                )

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

    # ── Refine acoustic speech rate with ASR word timestamps ──────────────
    # The energy-envelope syllable proxy is the least reliable acoustic feature
    # yet it solely drives the speech_rate label (and the depressive/mania
    # pattern split). AssemblyAI word timings give a far better articulation
    # rate from data already paid for. Non-fatal; falls back to the proxy.
    if acoustic_result and acoustic_result.get('vocabulary'):
        try:
            from acoustic_engine import (
                compute_transcript_timing, refine_speech_rate_with_transcript,
            )
            _timing = compute_transcript_timing(transcription.get('words'))
            if _timing:
                refine_speech_rate_with_transcript(
                    acoustic_result['vocabulary'], _timing,
                    baseline=db.get_voice_baseline(patient_id),
                )
                acoustic_result['transcript_timing'] = _timing
                logger.info(
                    "Speech rate refined from transcript: session=%s artic=%.2f sps "
                    "label=%s cross_check=%s",
                    session_id, _timing['articulation_rate_sps'],
                    acoustic_result['vocabulary'].get('speech_rate'),
                    acoustic_result['vocabulary'].get('speech_rate_cross_check'),
                )
        except Exception as _re:
            logger.warning("Transcript speech-rate refine failed (non-fatal): "
                           "session=%s error=%s", session_id, _re)

    # ── Feature extraction ────────────────────────────────────────
    db.update_clinical_session_status(session_id, 'extracting')
    # Fetch population flags so the graduated crisis scorer (spec §23) can apply
    # population-aware modifiers. Returns {} if no flags are set — safe default.
    population_flags = db.get_patient_population_flags(patient_id)
    assemblyai_hints  = {
        'entities':          transcription.get('entities') or [],
        'auto_highlights':   transcription.get('auto_highlights') or [],
        'sentiment_results': transcription.get('sentiment_results') or [],
    } if ASSEMBLYAI_ENHANCED else None
    extraction = extract_features(
        transcript_text=transcript_text,
        session_date=session_date,
        session_type=session_type,
        population_flags=population_flags or None,
        assemblyai_hints=assemblyai_hints,
        acoustic_baseline_context=acoustic_baseline_context if session_type != 'voice_note' else None,
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
    existing_transcript: str | None = None,
) -> None:
    """
    Unified synchronous voice-note pipeline. Used by both audio entry points:
      - SMS patient flow (api_voice_submit) — audio already stored, pass
        audio_already_stored_url so the storage step is skipped.
      - Provider upload flow (api_provider_upload_voice_note) — audio stored here.
      - Recovery path (reprocess_stuck_voice_notes) — audio re-downloaded from
        storage; existing_transcript skips the AssemblyAI re-call.

    Steps:
      1. Store audio in the 'voice-notes' bucket (non-fatal on failure)
      2. Transcribe via AssemblyAI (fatal on failure; skipped when
         existing_transcript is provided)
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

    # In-flight guard — prevents double-processing the same note within this
    # worker (e.g. recovery re-enqueue racing a click-spam re-enqueue).
    note_key = str(voice_note_id)
    with _IN_FLIGHT_LOCK:
        if note_key in _IN_FLIGHT_NOTES:
            logger.info("Voice note %s already in flight — skipping duplicate run", note_key)
            return
        _IN_FLIGHT_NOTES.add(note_key)

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
        if not audio_already_stored_url and file_bytes:
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

        # ── 2. Transcription (fatal on failure; skipped on recovery re-runs) ─
        _transcription_result = {}   # may be populated below for assemblyai_hints
        if existing_transcript:
            transcript_text = existing_transcript
            db.supabase_admin.table('voice_notes').update({
                'processing_status': 'processing',
                'processing_error':  None,
            }).eq('id', voice_note_id).execute()
        else:
            result = transcribe_audio_file(
                file_bytes=file_bytes,
                filename=filename,
                patient_id=patient_id,
                session_id=str(voice_note_id),
            )
            if not (result.get('status') == 'completed' and result.get('text')):
                _vn_error(result.get('error') or 'Transcription failed')
                return

            _transcription_result = result
            transcript_text = result['text']
            db.supabase_admin.table('voice_notes').update({
                'transcript':        transcript_text,
                'processing_status': 'processing',
            }).eq('id', voice_note_id).execute()

        # ── 3. Acoustic biomarker extraction (non-fatal) ─────────────────────
        # Runs on raw bytes — independent of transcript content. The session_id
        # is only used for logging here; the clinical session does not exist yet.
        # Skipped when no audio bytes are available (transcript-only recovery).
        acoustic_result = None
        if file_bytes:
            acoustic_result = _run_acoustic_extraction(
                file_bytes=file_bytes,
                filename=filename,
                session_id=str(voice_note_id),
                session_date=session_date,
                session_type='voice_note',
            )

        # Refine speech rate from ASR word timestamps (more reliable than the
        # energy-envelope proxy). Skipped on transcript-only recovery runs where
        # no word timings exist. Non-fatal.
        if acoustic_result and acoustic_result.get('vocabulary'):
            try:
                from acoustic_engine import (
                    compute_transcript_timing, refine_speech_rate_with_transcript,
                )
                _timing = compute_transcript_timing(_transcription_result.get('words'))
                if _timing:
                    refine_speech_rate_with_transcript(
                        acoustic_result['vocabulary'], _timing,
                        baseline=db.get_voice_baseline(patient_id),
                    )
                    acoustic_result['transcript_timing'] = _timing
            except Exception as _re:
                logger.warning("Transcript speech-rate refine failed (non-fatal): "
                               "voice_note=%s error=%s", voice_note_id, _re)

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
        _vn_hints = {
            'entities':          _transcription_result.get('entities') or [],
            'auto_highlights':   _transcription_result.get('auto_highlights') or [],
            'sentiment_results': _transcription_result.get('sentiment_results') or [],
        } if ASSEMBLYAI_ENHANCED else None
        extraction = extract_features(
            transcript_text=transcript_text,
            session_date=session_date,
            session_type='voice_note',
            population_flags=db.get_patient_population_flags(patient_id) or None,
            assemblyai_hints=_vn_hints,
        )
        _merge_acoustic_into_extraction(extraction, acoustic_result, session_id)

        # ── 6.5 Crisis escalation (patient-facing safety net) ────────────────
        # Voice is async and patient-initiated, so a self-harm disclosure here
        # previously surfaced only as a delayed provider-side flag. Run the binary
        # patient-channel check (maximum caution) AND honor the graduated scorer's
        # blocking decision, then escalate via the shared handler: crisis SMS to
        # the patient + provider alert + care flag. Guarded so it never breaks the
        # pipeline.
        try:
            from claude_api import _check_crisis as _binary_crisis
            import sms_engine as _sms_mod
            if _binary_crisis(transcript_text or '') or extraction.get('crisis_detected'):
                logger.critical(
                    "Voice-note CRISIS detected: patient=%s session=%s",
                    patient_id, session_id,
                )
                _sms_mod.escalate_crisis(db, patient_id, source='voice')
        except Exception as _ce:
            logger.error(
                "Voice-note crisis escalation error: patient=%s err=%s",
                patient_id, _ce,
            )

        # ── 7. Persist features + link voice note to its clinical session ────
        features_stored = db.store_session_features(
            session_id=session_id,
            patient_id=patient_id,
            extraction_result=extraction,
            extraction_model=os.environ.get('CLAUDE_MODEL', 'claude-haiku-4-5-20251001'),
        )
        if extraction.get('error') or not features_stored:
            # The clinical session exists — link it even on failure so the
            # transcript remains usable and debugging is easier. But do NOT
            # claim 'complete' when extraction or persistence failed.
            try:
                db.supabase_admin.table('voice_notes').update(
                    {'clinical_session_id': str(session_id)}
                ).eq('id', voice_note_id).execute()
            except Exception as le:
                logger.warning("voice_notes clinical_session_id link failed: id=%s error=%s",
                               voice_note_id, le)
            _vn_error(extraction.get('error') or 'Failed to persist session features')
            return

        db.supabase_admin.table('voice_notes').update({
            'processing_status':   'complete',
            'clinical_session_id': str(session_id),
        }).eq('id', voice_note_id).execute()

        logger.info("Voice-note pipeline complete: voice_note=%s session=%s",
                    voice_note_id, session_id)

    except Exception as exc:
        logger.exception("Voice-note pipeline failed: voice_note=%s", voice_note_id)
        _vn_error(str(exc))
    finally:
        with _IN_FLIGHT_LOCK:
            _IN_FLIGHT_NOTES.discard(note_key)


def process_voice_note_async(
    voice_note_id: str,
    patient_id: str,
    provider_id: str | None,
    file_bytes: bytes,
    filename: str,
    session_date: str | None = None,
    audio_already_stored_url: str | None = None,
    existing_transcript: str | None = None,
) -> None:
    """
    Start background processing for a voice note. Returns immediately.
    Progress is tracked via voice_notes.processing_status.
    """
    t = threading.Thread(
        target=process_voice_note,
        args=(voice_note_id, patient_id, provider_id, file_bytes, filename,
              session_date, audio_already_stored_url, existing_transcript),
        daemon=True,
        name=f'voice-note-{str(voice_note_id)[:8]}',
    )
    t.start()
    logger.info("Voice-note processing thread started: voice_note=%s thread=%s",
                voice_note_id, t.name)


# ── Stuck-note recovery ───────────────────────────────────────────────────────
# Background threads are not durable: a Render deploy, worker restart, or OOM
# kills them silently, stranding voice_notes in a non-terminal status
# ('pending'/'processing') with no error and no clinical session. These helpers
# detect that state and re-enqueue the pipeline from the stored audio.

_IN_FLIGHT_LOCK   = threading.Lock()
_IN_FLIGHT_NOTES: set[str] = set()

STUCK_STATUSES      = ('pending', 'processing')
STUCK_AFTER_MINUTES = 30   # max plausible pipeline runtime (poll cap 15 min + extraction)


def _note_is_stuck(note: dict, now: datetime | None = None) -> bool:
    """
    True when a voice note sits in a non-terminal status long past any
    plausible pipeline runtime — i.e. its background thread is dead.
    Notes inside the staleness window may still have a live thread and are
    never touched. Unparseable timestamps are treated as not-stuck (safe side).
    """
    if note.get('clinical_session_id'):
        return False
    if note.get('processing_status') not in STUCK_STATUSES:
        return False

    created_raw = (note.get('created_at') or '').strip().replace('Z', '+00:00')
    # Supabase returns '2026-06-11 03:03:28.524112+00' — the bare '+00' offset
    # is rejected by fromisoformat on Python < 3.11. Normalize it.
    if len(created_raw) >= 3 and created_raw[-3] in '+-' and created_raw[-2:].isdigit():
        created_raw += ':00'
    try:
        ts = datetime.fromisoformat(created_raw)
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    now = now or datetime.now(timezone.utc)
    return (now - ts).total_seconds() > STUCK_AFTER_MINUTES * 60


def _storage_path_from_url(audio_url: str) -> str | None:
    """
    Derive the 'voice-notes' bucket object path from a stored public URL.
    Returns None when the URL is not a voice-notes storage URL.
    """
    if not audio_url:
        return None
    marker = '/voice-notes/'
    idx = audio_url.find(marker)
    if idx == -1:
        return None
    return audio_url[idx + len(marker):].split('?')[0] or None


def _download_voice_note_audio(note: dict) -> tuple[bytes | None, str]:
    """
    Download a voice note's stored audio from the 'voice-notes' bucket.
    Returns (bytes, filename) — (None, '') when unavailable. Non-fatal:
    recovery falls back to transcript-only processing.
    """
    import database as db

    path = _storage_path_from_url(note.get('audio_url') or '')
    if not path:
        return None, ''
    try:
        data = db.supabase_admin.storage.from_('voice-notes').download(path)
        if data:
            return data, os.path.basename(path)
    except Exception as e:
        logger.warning("Voice-note audio download failed: id=%s path=%s error=%s",
                       note.get('id'), path, e)
    return None, ''


def reprocess_stuck_voice_notes(notes: list, default_provider_id: str | None = None) -> int:
    """
    Re-enqueue processing for voice notes whose pipeline thread died mid-run.

    For each stuck note (see _note_is_stuck):
      - re-download the stored audio for full acoustic re-extraction
      - reuse the existing transcript to skip the AssemblyAI re-call
      - fall back to transcript-only processing when the audio is gone
      - skip entirely when there is neither audio nor transcript (mark error
        so the note stops presenting as recoverable)

    Returns the number of notes re-enqueued. Safe to call on every
    voice-biomarkers request — non-stuck notes are untouched and the
    in-flight guard in process_voice_note prevents duplicate runs.
    """
    import database as db

    enqueued = 0
    for note in notes or []:
        if not _note_is_stuck(note):
            continue

        note_id    = str(note.get('id'))
        transcript = (note.get('transcript') or '').strip() or None
        file_bytes, filename = _download_voice_note_audio(note)

        if not file_bytes and not transcript:
            # Nothing to recover from — make the state terminal and honest.
            try:
                db.supabase_admin.table('voice_notes').update({
                    'processing_status': 'error',
                    'processing_error':  'Processing was interrupted and no audio or transcript was retained.',
                }).eq('id', note_id).execute()
            except Exception as ue:
                logger.error("Stuck-note error-status update failed: id=%s error=%s", note_id, ue)
            continue

        logger.info("Recovering stuck voice note: id=%s status=%s has_audio=%s has_transcript=%s",
                    note_id, note.get('processing_status'), bool(file_bytes), bool(transcript))
        process_voice_note_async(
            voice_note_id=note_id,
            patient_id=str(note.get('patient_id')),
            provider_id=note.get('provider_id') or default_provider_id,
            file_bytes=file_bytes or b'',
            filename=filename or 'voice_note.webm',
            session_date=(note.get('created_at') or '')[:10] or None,
            audio_already_stored_url=note.get('audio_url'),
            existing_transcript=transcript,
        )
        enqueued += 1

    return enqueued


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
