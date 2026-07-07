"""DEAD MODULE — safe to delete (`git rm auth.py`).

Every function that lived here (register_user, login_user, logout_user,
get_current_user, require_auth, require_provider, change_password) has a
replacement in supabase_auth.py, and app.py's `auth_module` alias points at
supabase_auth — nothing imports this module (verified 2026-07-06, zero
references repo-wide). It is kept only because the Cowork sandbox cannot
unlink files on this mount; delete it from a normal checkout.

Deleting this file requires no other change: it was already removed from
scripts/check_repo_integrity.py's CRITICAL_MODULES, and the pre-commit hook
will ask for ALLOW_DELETIONS=1 (expected — this deletion is intentional).
"""
