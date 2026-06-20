"""Offline tests for the signed brief print token (supabase_auth.generate/verify_brief_token).

The token hides patient/brief UUIDs from the printed footer URL. It is a privacy
measure, not a bearer credential — the route still enforces provider login +
ownership. These tests cover the crypto: round-trip, opacity, tamper rejection,
expiry, and wrong-secret rejection. Run with:

    python3 tests/test_brief_token.py      (or pytest)
"""
import importlib.util
import os
import sys
import types

# Stub the heavy SDK imports so supabase_auth loads offline.
for name, attrs in (('supabase', {'create_client': lambda *a, **k: None, 'Client': object}),
                    ('jwt', {}),
                    ('flask', {'request': object()}),
                    ('email_utils', {})):
    if name not in sys.modules:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location('supabase_auth',
                                               os.path.join(_REPO, 'supabase_auth.py'))
sa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sa)

SECRET = 'test-secret-key-long-enough'
PATIENT = '202a6659-48a8-4785-b9a3-58fe8ebf8922'
BRIEF = '1dd1594f-9e86-4ae8-b444-e3d2ce0ac3a9'


def test_round_trip():
    tok = sa.generate_brief_token(PATIENT, BRIEF, 14, SECRET)
    out = sa.verify_brief_token(tok, SECRET)
    assert out == {'patient_id': PATIENT, 'brief_id': BRIEF, 'days': 14}


def test_token_is_opaque_no_uuid_in_clear():
    # The whole point: neither UUID may appear verbatim in the token string.
    tok = sa.generate_brief_token(PATIENT, BRIEF, 14, SECRET)
    assert PATIENT not in tok and BRIEF not in tok


def test_tampered_payload_rejected():
    tok = sa.generate_brief_token(PATIENT, BRIEF, 14, SECRET)
    blob, sig = tok.split('.', 1)
    # Flip a character in the signature, and separately in the blob.
    assert sa.verify_brief_token(blob + '.' + ('0' if sig[0] != '0' else '1') + sig[1:], SECRET) is None
    assert sa.verify_brief_token(('A' if blob[0] != 'A' else 'B') + blob[1:] + '.' + sig, SECRET) is None


def test_wrong_secret_rejected():
    tok = sa.generate_brief_token(PATIENT, BRIEF, 14, SECRET)
    assert sa.verify_brief_token(tok, 'a-different-secret') is None


def test_expired_rejected(monkeypatch=None):
    # Force expiry by generating with the TTL temporarily negative.
    original = sa._BRIEF_TTL
    try:
        sa._BRIEF_TTL = -10
        tok = sa.generate_brief_token(PATIENT, BRIEF, 14, SECRET)
    finally:
        sa._BRIEF_TTL = original
    assert sa.verify_brief_token(tok, SECRET) is None


def test_missing_brief_id_ok():
    tok = sa.generate_brief_token(PATIENT, None, 30, SECRET)
    out = sa.verify_brief_token(tok, SECRET)
    assert out == {'patient_id': PATIENT, 'brief_id': None, 'days': 30}


def test_garbage_token_rejected():
    for bad in ('', 'not-a-token', 'a.b', '....', 'x' * 50):
        assert sa.verify_brief_token(bad, SECRET) is None


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failures = []
    for t in tests:
        try:
            t()
            print('PASS', t.__name__)
        except AssertionError as e:
            print('FAIL', t.__name__, '-', e)
            failures.append(t.__name__)
    print('\nRESULT:', 'ALL PASS' if not failures else f'{len(failures)} FAILED -> {failures}')
    sys.exit(1 if failures else 0)
