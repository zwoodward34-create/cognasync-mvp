import os
import uuid
import time
import hmac
import hashlib
import jwt
from supabase import create_client, Client
from functools import wraps
from flask import request
import email_utils

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')
SUPABASE_JWT_SECRET = os.environ.get('SUPABASE_JWT_SECRET')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def verify_jwt(token):
    """Verify a Supabase JWT and return the user profile.

    If SUPABASE_JWT_SECRET is configured the signature is verified locally
    (fast, no network call).  If the secret is absent we fall back to
    Supabase's get_user API, which validates the token server-side.
    """
    if not token:
        return None

    user_id = None

    # Try fast local verification first when the secret is configured
    if SUPABASE_JWT_SECRET:
        try:
            decoded = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
            user_id = decoded.get('sub')
        except jwt.ExpiredSignatureError:
            return None  # Expired — don't bother with API fallback
        except jwt.InvalidTokenError:
            pass  # Wrong secret or malformed — fall through to API check

    # Fall back to Supabase API validation (authoritative, slightly slower)
    if not user_id:
        try:
            resp = supabase_admin.auth.get_user(token)
            if not resp or not resp.user:
                return None
            user_id = resp.user.id
        except Exception:
            return None

    if not user_id:
        return None

    try:
        response = supabase_admin.table('profiles').select('*').eq('id', user_id).execute()
        if response.data:
            user_data = response.data[0]
            return {
                'id':         user_data['id'],
                'email':      user_data['email'],
                'full_name':  user_data['full_name'],
                'role':       user_data['role'],
                'created_at': user_data.get('created_at', ''),
            }
    except Exception:
        pass
    return None


def get_current_user(token):
    """Get current user from JWT token."""
    if not token:
        return None
    return verify_jwt(token)


def require_auth(f):
    """Decorator to require authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = (
            (request.get_json(silent=True) or {}).get('session_token')
            or request.headers.get('Authorization', '').replace('Bearer ', '')
        )
        user = get_current_user(token)
        if not user:
            return {'error': 'Authentication required'}, 401
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def require_provider(f):
    """Decorator to require provider role."""
    @wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        if request.current_user['role'] != 'provider':
            return {'error': 'Provider access required'}, 403
        return f(*args, **kwargs)
    return decorated


def register_user(email, password, full_name, role):
    """Create a pending account. The user must verify email; admin must then approve.

    Steps are separated so that a failure in any one step can be handled cleanly:
      1. Check for existing (possibly partial) registrations first.
      2. Create Supabase Auth user — if this fails, nothing was written.
      3. Create profile row — if this fails, delete the auth user (rollback).
      4. Send verification email — non-fatal; account exists either way,
         and the user can request a resend.
    """
    if role not in ('patient', 'provider'):
        return None, 'Invalid role'
    if not email or not password or not full_name:
        return None, 'All fields required'
    if len(password) < 8:
        return None, 'Password must be at least 8 characters'

    email = email.lower().strip()
    full_name = full_name.strip()

    # ── Step 0: Handle partially-created or duplicate accounts ────────
    try:
        existing = supabase_admin.table('profiles').select(
            'id, status, email_verify_token, full_name'
        ).eq('email', email).limit(1).execute()
    except Exception:
        existing = None

    if existing and existing.data:
        profile = existing.data[0]
        status = profile.get('status', '')

        if status == 'pending_email':
            # Account exists but email was never verified — resend the link.
            token = profile.get('email_verify_token') or str(uuid.uuid4())
            if not profile.get('email_verify_token'):
                try:
                    supabase_admin.table('profiles').update(
                        {'email_verify_token': token}
                    ).eq('id', profile['id']).execute()
                except Exception:
                    pass
            try:
                email_utils.send_verification_email(
                    email, profile.get('full_name', full_name), token
                )
            except Exception as mail_err:
                print(f"[register] Resend verification failed for {email}: {mail_err}")
            return None, (
                'An account for this email is already registered but not yet verified. '
                'We\'ve resent the verification link — check your inbox (and spam folder).'
            )

        if status in ('pending_approval', 'approved'):
            return None, (
                'An account with this email already exists. '
                'Try signing in, or use "Forgot password" if you\'ve lost access.'
            )

        # Any other status — treat as duplicate
        return None, 'An account with this email already exists.'

    verify_token = str(uuid.uuid4())
    user_id = None

    # ── Step 1: Create the Supabase Auth user ─────────────────────────
    try:
        print(f"[register] Step 1: creating auth user for {email}")
        auth_response = supabase_admin.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,   # confirms within Supabase Auth; our flow
        })                           # uses its own token stored in profiles

        # Defensive: some client versions return None user instead of raising
        if not auth_response or not auth_response.user or not auth_response.user.id:
            print(f"[register] WARNING: create_user returned no user object for {email}. "
                  f"Response: {auth_response!r}")
            # The auth user may or may not have been created. Check by looking for
            # a possible duplicate profile situation on retry, not here.
            return None, 'Registration failed — could not create account. Please try again in a moment.'

        user_id = auth_response.user.id
        print(f"[register] Step 1 OK: auth user {user_id} created for {email}")

    except Exception as e:
        err_str = str(e).lower()
        print(f"[register] Step 1 EXCEPTION for {email}: {e!r}")
        if any(kw in err_str for kw in (
            'already registered', 'already exists', 'duplicate',
            'email_exists', 'user_already_exists', 'email already',
        )):
            # Auth user already exists. Check for orphaned account (auth user but no complete profile).
            try:
                users_resp = supabase_admin.auth.admin.list_users()
                auth_users = users_resp if isinstance(users_resp, list) else getattr(users_resp, 'users', [])
                orphan = next(
                    (u for u in auth_users if (getattr(u, 'email', '') or '').lower() == email),
                    None
                )
                if orphan:
                    uid = orphan.id
                    prof = supabase_admin.table('profiles').select(
                        'id, status, email_verify_token'
                    ).eq('id', str(uid)).execute()
                    if not prof.data or not prof.data[0].get('status'):
                        # Orphaned auth user with no/incomplete profile — create it now
                        token = str(uuid.uuid4())
                        supabase_admin.table('profiles').upsert({
                            'id':                 uid,
                            'email':              email,
                            'full_name':          full_name,
                            'role':               role,
                            'status':             'pending_email',
                            'email_verify_token': token,
                        }).execute()
                        email_sent = True
                        try:
                            email_utils.send_verification_email(email, full_name, token)
                        except Exception as mail_err:
                            email_sent = False
                            print(f"[register] Recovery email failed for {email}: {mail_err}")
                        print(f"[register] Recovered orphaned auth user {uid} for {email}")
                        return {
                            'user_id': uid, 'email': email, 'role': role,
                            'full_name': full_name, 'pending': True, 'email_sent': email_sent,
                        }, None
                    elif prof.data[0].get('status') == 'pending_email':
                        # Complete profile exists but unverified — resend link
                        token = prof.data[0].get('email_verify_token') or str(uuid.uuid4())
                        if not prof.data[0].get('email_verify_token'):
                            supabase_admin.table('profiles').update(
                                {'email_verify_token': token}
                            ).eq('id', str(uid)).execute()
                        try:
                            email_utils.send_verification_email(email, full_name, token)
                        except Exception:
                            pass
                        return None, (
                            'An account for this email is already registered but not yet verified. '
                            "We've resent the verification link — check your inbox (and spam folder)."
                        )
            except Exception as recovery_err:
                print(f"[register] Recovery attempt failed for {email}: {recovery_err}")

            return None, (
                'An account with this email already exists. '
                'Try signing in, or use "Forgot password" if you\'ve lost access.'
            )
        return None, f'Registration failed — please try again. ({e})'

    # ── Step 2: Create the profile row (upsert tolerates trigger-created rows) ──
    try:
        print(f"[register] Step 2: upserting profile for {user_id}")
        supabase_admin.table('profiles').upsert({
            'id':                 user_id,
            'email':              email,
            'full_name':          full_name,
            'role':               role,
            'status':             'pending_email',
            'email_verify_token': verify_token,
        }).execute()
        print(f"[register] Step 2 OK: profile upserted for {email}")
    except Exception as e:
        # Profile insert failed — roll back the auth user so the address is free to retry.
        print(f"[register] Step 2 FAILED for {email}: {e!r} — attempting rollback")
        try:
            supabase_admin.auth.admin.delete_user(user_id)
            print(f"[register] Rolled back auth user {user_id} after profile insert failure.")
        except Exception as del_err:
            print(f"[register] WARNING: could not delete orphaned auth user {user_id}: {del_err}")
        return None, f'Registration failed — please try again. ({e})'

    # ── Step 3: Send verification email (non-fatal) ───────────────────
    email_sent = True
    try:
        print(f"[register] Step 3: sending verification email to {email}")
        email_utils.send_verification_email(email, full_name, verify_token)
        print(f"[register] Step 3 OK: verification email sent to {email}")
    except Exception as mail_err:
        email_sent = False
        print(f"[register] Step 3 FAILED (non-fatal) for {email}: {mail_err}")
        # Account is fully created — don't fail registration, just warn.

    return {
        'user_id':    user_id,
        'email':      email,
        'role':       role,
        'full_name':  full_name,
        'pending':    True,
        'email_sent': email_sent,
    }, None


def login_user(email, password):
    """Login user with Supabase. Blocked if account is not yet approved."""
    try:
        response = supabase.auth.sign_in_with_password({
            "email": email.lower().strip(),
            "password": password
        })

        user_data = supabase_admin.table('profiles').select('*').eq('id', response.user.id).execute()
        profile = user_data.data[0] if user_data.data else {}

        status = profile.get('status', 'approved')
        if status == 'pending_email':
            return None, 'Please verify your email address before signing in. Check your inbox for the verification link.'
        if status == 'pending_approval':
            return None, 'Your account is pending administrator approval. You will receive an email when approved.'

        return {
            'session_token': response.session.access_token,
            'user_id': response.user.id,
            'email': profile.get('email'),
            'role': profile.get('role'),
            'full_name': profile.get('full_name')
        }, None
    except Exception:
        return None, "Invalid email or password"


def logout_user(token):
    """Invalidate the session in Supabase."""
    try:
        if token:
            supabase.auth.sign_out()
    except Exception:
        pass


def change_password(user_id, current_password, new_password):
    """Change a user's password after verifying the current one."""
    if len(new_password) < 8:
        return False, 'New password must be at least 8 characters'
    try:
        profile = supabase_admin.table('profiles').select('email').eq('id', str(user_id)).execute()
        if not profile.data:
            return False, 'User not found'
        email = profile.data[0]['email']
        # Re-authenticate to verify current password
        supabase.auth.sign_in_with_password({"email": email, "password": current_password})
        # Update via admin API
        supabase_admin.auth.admin.update_user_by_id(str(user_id), {"password": new_password})
        return True, 'Password updated successfully'
    except Exception:
        return False, 'Current password is incorrect'


# ── Password reset (HMAC-signed, time-limited tokens, no DB column needed) ────

_RESET_TTL = 3600  # 1 hour


def _reset_sig(user_id: str, expires: int, nonce: str, secret: str) -> str:
    payload = f"reset:{user_id}:{expires}:{nonce}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def generate_reset_token(user_id: str, secret: str) -> str:
    expires = int(time.time()) + _RESET_TTL
    nonce = uuid.uuid4().hex[:12]
    sig = _reset_sig(user_id, expires, nonce, secret)
    return f"{user_id}:{expires}:{nonce}:{sig}"


def verify_reset_token(token: str, secret: str):
    """Return user_id if valid and unexpired, else None."""
    try:
        parts = token.split(':', 3)
        if len(parts) != 4:
            return None
        user_id, expires_str, nonce, sig = parts
        if time.time() > int(expires_str):
            return None
        expected = _reset_sig(user_id, int(expires_str), nonce, secret)
        if not hmac.compare_digest(sig, expected):
            return None
        return user_id
    except Exception:
        return None


def initiate_password_reset(email: str):
    """Look up the email and return (user_id, None) if a resetable account exists.
    Always returns (None, None) for unknown emails to prevent enumeration."""
    try:
        result = supabase_admin.table('profiles').select('id, full_name, status').eq(
            'email', email.lower().strip()
        ).limit(1).execute()
        if not result.data:
            return None, None
        profile = result.data[0]
        if profile.get('status') not in ('approved', 'pending_approval', 'pending_email'):
            return None, None
        return profile['id'], profile.get('full_name', '')
    except Exception as e:
        print(f"[password_reset] Error finding user {email}: {e}")
        return None, None


def reset_password_with_token(token: str, new_password: str, secret: str):
    """Validate token and update password. Returns (True, None) or (False, error_msg)."""
    if len(new_password) < 8:
        return False, 'Password must be at least 8 characters'
    user_id = verify_reset_token(token, secret)
    if not user_id:
        return False, 'This reset link has expired or is invalid. Please request a new one.'
    try:
        supabase_admin.auth.admin.update_user_by_id(str(user_id), {"password": new_password})
        # If the account was stuck in pending_email, the reset email proves ownership —
        # advance to pending_approval so admin review can complete the flow.
        try:
            supabase_admin.table('profiles').update(
                {'status': 'pending_approval', 'email_verify_token': None}
            ).eq('id', str(user_id)).eq('status', 'pending_email').execute()
        except Exception:
            pass
        return True, None
    except Exception as e:
        print(f"[password_reset] Error updating password for {user_id}: {e}")
        return False, 'Failed to update password — please try again.'
