"""Tests for stuck voice-note detection and recovery helpers (audio_engine).

A voice note is "stuck" when its background pipeline thread died mid-run
(deploy restart, worker OOM) leaving processing_status in a non-terminal
state with no clinical_session_id. These tests pin the eligibility rules
so the recovery path never picks up a live in-flight note and never
misses a dead one.
"""

from datetime import datetime, timedelta, timezone

from audio_engine import _note_is_stuck, _storage_path_from_url, STUCK_AFTER_MINUTES

NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)


def _note(minutes_old=120, status='processing', session_id=None):
    created = (NOW - timedelta(minutes=minutes_old)).isoformat()
    return {
        'id': 'abc-123',
        'created_at': created,
        'processing_status': status,
        'clinical_session_id': session_id,
    }


# ── _note_is_stuck ────────────────────────────────────────────────────────────

def test_old_processing_note_without_session_is_stuck():
    assert _note_is_stuck(_note(minutes_old=120, status='processing'), now=NOW)


def test_old_pending_note_without_session_is_stuck():
    assert _note_is_stuck(_note(minutes_old=120, status='pending'), now=NOW)


def test_fresh_processing_note_is_not_stuck():
    # A note inside the staleness window may still have a live thread.
    assert not _note_is_stuck(_note(minutes_old=5, status='processing'), now=NOW)


def test_note_just_past_threshold_is_stuck():
    assert _note_is_stuck(
        _note(minutes_old=STUCK_AFTER_MINUTES + 1, status='processing'), now=NOW)


def test_note_just_under_threshold_is_not_stuck():
    assert not _note_is_stuck(
        _note(minutes_old=STUCK_AFTER_MINUTES - 1, status='processing'), now=NOW)


def test_complete_note_is_not_stuck():
    assert not _note_is_stuck(_note(minutes_old=120, status='complete'), now=NOW)


def test_error_note_is_not_stuck():
    # Errors are terminal and surfaced with a reason — not recovery targets.
    assert not _note_is_stuck(_note(minutes_old=120, status='error'), now=NOW)


def test_note_with_clinical_session_is_not_stuck():
    assert not _note_is_stuck(
        _note(minutes_old=120, status='processing', session_id='sess-1'), now=NOW)


def test_unparseable_created_at_is_not_stuck():
    note = _note(minutes_old=120)
    note['created_at'] = 'not-a-date'
    assert not _note_is_stuck(note, now=NOW)


def test_postgres_timestamp_format_is_parsed():
    # Supabase returns '2026-06-11 03:03:28.524112+00' (space separator).
    note = _note(minutes_old=120)
    note['created_at'] = '2026-06-11 03:03:28.524112+00'
    assert _note_is_stuck(note, now=NOW)


# ── _storage_path_from_url ────────────────────────────────────────────────────

def test_storage_path_derived_from_public_url():
    url = ('https://qsnxrfefwwybiutkynzk.supabase.co/storage/v1/object/public/'
           'voice-notes/202a6659/47801377.webm')
    assert _storage_path_from_url(url) == '202a6659/47801377.webm'


def test_storage_path_strips_query_string():
    url = ('https://x.supabase.co/storage/v1/object/public/'
           'voice-notes/p1/n1.webm?token=abc')
    assert _storage_path_from_url(url) == 'p1/n1.webm'


def test_storage_path_returns_none_for_foreign_url():
    assert _storage_path_from_url('https://example.com/foo.webm') is None
    assert _storage_path_from_url('') is None
