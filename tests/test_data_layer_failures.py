"""
Unit tests for the data-layer silent-failure fix.

The data layer must never let a *failed* read masquerade as genuinely empty
data: an empty list/dict returned from an exception handler is indistinguishable
from "no rows", and a clinical summary built on it looks authoritative while
silently omitting a safety signal, substance flag, or symptom pattern.

These tests pin the contract introduced by that fix:

  - clinical READ functions RAISE DataUnavailableError when the underlying
    Supabase call fails (they no longer return [] / {} / None on error);
  - the raised error chains the original cause and carries a `source`;
  - a genuinely-empty read still returns empty (NOT a raise) — the
    failed-vs-empty distinction holds;
  - clinical WRITE functions keep their boolean/None contract on failure
    (callers branch on the return) but no longer fail silently.

Run:
    python3 -m pytest tests/test_data_layer_failures.py -v
"""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Allow the suite to run without the real `supabase` package installed: the
# unit under test is database.py's error handling, which only needs a client
# object whose behavior we control. If supabase IS installed, we leave it.
try:  # pragma: no cover - environment dependent
    import supabase  # noqa: F401
except Exception:  # pragma: no cover
    _fake = types.ModuleType("supabase")
    _fake.create_client = lambda *a, **k: MagicMock()
    _fake.Client = MagicMock
    sys.modules["supabase"] = _fake

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_KEY", "test")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import database as db  # noqa: E402


def _failing_client():
    """A Supabase client whose every query chain raises on .table()."""
    c = MagicMock()
    c.table.side_effect = RuntimeError("db connection lost")
    return c


def _empty_client():
    """A Supabase client whose query chains resolve to .data == []."""
    c = MagicMock()
    # Any attribute chain ending in .execute() returns an object with .data = []
    exec_result = MagicMock()
    exec_result.data = []
    # MagicMock auto-creates the chain; make the terminal execute() return it.
    c.table.return_value = MagicMock()
    # Walk-through: configure execute() on the deep mock to return exec_result
    deep = c.table.return_value
    for attr in ("select", "insert", "update", "upsert", "delete",
                 "eq", "neq", "gte", "lte", "gt", "lt", "in_",
                 "order", "limit", "range", "single", "is_"):
        setattr(deep, attr, MagicMock(return_value=deep))
    deep.execute = MagicMock(return_value=exec_result)
    return c


class _ClientPatch:
    """Context manager that swaps both module-level Supabase clients."""

    def __init__(self, client):
        self.client = client

    def __enter__(self):
        self._orig_admin = db.supabase_admin
        self._orig = db.supabase
        db.supabase_admin = self.client
        db.supabase = self.client
        return self.client

    def __exit__(self, *exc):
        db.supabase_admin = self._orig_admin
        db.supabase = self._orig
        return False


# Representative clinical READ functions and how to call them. Each must RAISE
# DataUnavailableError on read failure rather than return an empty default.
READ_CASES = [
    ("get_patient_population_flags", lambda: db.get_patient_population_flags("pid")),
    ("get_checkins",                 lambda: db.get_checkins("pid", days=14)),
    ("get_checkin_streak",           lambda: db.get_checkin_streak("pid")),
    ("get_medication_events",        lambda: db.get_medication_events("uid", days=30)),
    ("get_medication_names",         lambda: db.get_medication_names()),
    ("find_symptom_correlations",    lambda: db.find_symptom_correlations("pid", days=60)),
    ("compute_engagement_stats",     lambda: db.compute_engagement_stats("pid", days=30)),
    ("get_summary_by_id",            lambda: db.get_summary_by_id("sid", "pid")),
]


class TestClinicalReadsRaiseOnFailure(unittest.TestCase):
    def test_each_read_raises_data_unavailable(self):
        for name, call in READ_CASES:
            with self.subTest(read=name):
                with _ClientPatch(_failing_client()):
                    with self.assertRaises(db.DataUnavailableError):
                        call()

    def test_error_chains_cause_and_carries_source(self):
        with _ClientPatch(_failing_client()):
            try:
                db.get_patient_population_flags("pid")
                self.fail("expected DataUnavailableError")
            except db.DataUnavailableError as e:
                # original exception preserved for debugging
                self.assertIsNotNone(e.__context__ or e.__cause__)
                self.assertEqual(e.source, "get_patient_population_flags")


class TestEmptyReadStillReturnsEmpty(unittest.TestCase):
    """A genuinely-empty result must NOT be turned into a failure."""

    def test_population_flags_empty(self):
        with _ClientPatch(_empty_client()):
            self.assertEqual(db.get_patient_population_flags("pid"), {})

    def test_medication_names_empty(self):
        with _ClientPatch(_empty_client()):
            out = db.get_medication_names()
            self.assertIsInstance(out, list)


# Clinical WRITE functions: on failure they keep their existing falsy contract
# (callers branch on the return value) — they must NOT raise, but must no
# longer fail silently (verified by the logging change, not asserted here).
WRITE_CASES = [
    ("set_patient_population_flags", lambda: db.set_patient_population_flags("pid", {"veteran": True}), False),
    ("set_checkin_reminders_enabled", lambda: db.set_checkin_reminders_enabled("uid", True), False),
]


class TestClinicalWritesKeepContract(unittest.TestCase):
    def test_writes_return_falsy_not_raise(self):
        for name, call, expected in WRITE_CASES:
            with self.subTest(write=name):
                with _ClientPatch(_failing_client()):
                    try:
                        self.assertEqual(call(), expected)
                    except db.DataUnavailableError:
                        self.fail(f"{name} should not raise; it must keep its falsy contract")


class TestPermissionGatedReaderFailsClosed(unittest.TestCase):
    """Readers gated by a permissions check fail CLOSED (deny), not by raising.

    `get_care_flags_for_provider` first resolves care-team permissions. That
    permissions read intentionally fails closed — on error it denies access and
    the reader returns an empty list. This is a deliberate security boundary,
    distinct from the silent-wrong-clinical-data mode the raise contract targets,
    so it is asserted separately rather than expected to raise.
    """

    def test_returns_empty_on_total_failure(self):
        with _ClientPatch(_failing_client()):
            self.assertEqual(db.get_care_flags_for_provider("prov", "pid"), [])


class TestErrorTypeShape(unittest.TestCase):
    def test_is_exception_subclass_and_accepts_source(self):
        self.assertTrue(issubclass(db.DataUnavailableError, Exception))
        e = db.DataUnavailableError("boom", source="x")
        self.assertEqual(e.source, "x")
        self.assertIn("boom", str(e))


if __name__ == "__main__":
    unittest.main()
