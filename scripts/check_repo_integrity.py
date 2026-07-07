#!/usr/bin/env python3
"""Static repo-integrity smoke check — stdlib only (no app import, no secrets, no pip).

Catches the "a stale-tree commit silently deleted a file" failure class that bit
this repo (templates/landing.html, sms_engine.py, voice_note.html). It verifies:

  1. Every template referenced via a string literal in the app exists under templates/.
  2. Every critical first-party module file still exists.

Deliberately does NOT import app.py — so it needs no env vars, no DB, no API keys,
and no third-party packages. Fast and deterministic, suitable for a pre-deploy gate.

Exit code 0 = all good; 1 = something referenced by the app is missing.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCLUDE_DIRS = {'.venv', 'venv', 'env', 'site-packages', 'node_modules',
                '.git', '__pycache__', 'client'}

# The app's own modules. If any of these vanish, the app won't boot.
# (auth.py was removed 2026-07: fully dead — app.py's auth_module aliases
# supabase_auth, and nothing imported auth.)
CRITICAL_MODULES = [
    'app.py', 'database.py', 'claude_api.py', 'supabase_auth.py',
    'email_utils.py', 'sms_engine.py', 'twilio_client.py', 'transcript_engine.py',
    'audio_engine.py', 'acoustic_engine.py', 'affect_model.py',
]

# Captures a string-literal first argument to the template renderer.
# Dynamic names (variables/f-strings) are intentionally skipped — no false positives.
RENDER_RE = re.compile(r"""render_template\(\s*['"]([^'"]+)['"]""")

# Skip this checker itself — its documentation naturally contains example calls
# that would otherwise be picked up as phantom template references.
SELF = os.path.abspath(__file__)


def iter_py_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            full = os.path.join(dirpath, fn)
            if os.path.abspath(full) == SELF:
                continue
            yield full


def main():
    problems = []

    referenced = set()
    for path in iter_py_files():
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                text = fh.read()
        except OSError:
            continue
        referenced.update(RENDER_RE.findall(text))

    for tpl in sorted(referenced):
        if not os.path.isfile(os.path.join(ROOT, 'templates', tpl)):
            problems.append(f"missing template: templates/{tpl}")

    for mod in CRITICAL_MODULES:
        if not os.path.isfile(os.path.join(ROOT, mod)):
            problems.append(f"missing module:   {mod}")

    if problems:
        print("REPO INTEGRITY CHECK FAILED:")
        for p in problems:
            print("  -", p)
        print(f"\n{len(problems)} problem(s). A file the app references is missing — "
              "likely a stale-tree commit deleted it. Restore it before deploying.")
        return 1

    print(f"Repo integrity OK: {len(referenced)} template references + "
          f"{len(CRITICAL_MODULES)} critical modules all present.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
