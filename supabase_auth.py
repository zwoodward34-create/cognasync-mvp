import os
import jwt
from supabase import create_client, Client
from functools import wraps
from flask import request

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

    try:
        if SUPABASE_JWT_SECRET:
            decoded = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
            user_id = decoded.get('sub')
        else:
            # Fall back to Supabase API validation (slightly slower but no secret needed)
            resp = supabase_admin.auth.get_user(token)
            if not resp or not resp.user:
                return None
            user_id = resp.user.id

        if not user_id:
            return None

        response = supabase_admin.table('profiles').select('*').eq('id', user_id).execute()
        if response.data:
            user_data = response.data[0]
            return {
                'id': user_data['id'],
                'email': user_data['email'],
                'full_name': user_data['full_name'],
                'role': user_data['role'],
            }
        return None
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception:
        import logging
        logging.exception("JWT verification error")
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
    """Create user in Supabase Auth. Providers cannot self-register."""
    if role not in ('patient', 'provider'):
        return None, 'Invalid role'
    if role == 'provider':
        return None, 'Provider accounts require administrator approval. Contact support.'
    if not email or not password or not full_name:
        return None, 'All fields required'
    if len(password) < 8:
        return None, 'Password must be at least 8 characters'

    try:
        auth_response = supabase_admin.auth.admin.create_user({
            "email": email.lower().strip(),
            "password": password,
            "email_confirm": True
        })
        user_id = auth_response.user.id

        supabase_admin.table('profiles').insert({
            'id': user_id,
            'email': email.lower().strip(),
            'full_name': full_name.strip(),
            'role': 'patient',  # always patient regardless of form input
        }).execute()

        login_response = supabase.auth.sign_in_with_password({
            "email": email.lower().strip(),
            "password": password
        })

        return {
            'session_token': login_response.session.access_token,
            'user_id': user_id,
            'email': email,
            'role': 'patient',
            'full_name': full_name
        }, None
    except Exception as e:
        return None, str(e)


def login_user(email, password):
    """Login user with Supabase."""
    try:
        response = supabase.auth.sign_in_with_password({
            "email": email.lower().strip(),
            "password": password
        })

        user_data = supabase_admin.table('profiles').select('*').eq('id', response.user.id).execute()
        profile = user_data.data[0] if user_data.data else {}

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
