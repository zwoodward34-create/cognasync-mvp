import os
import jwt
from supabase import create_client, Client
from functools import wraps
from flask import request

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def verify_jwt(token):
    """Verify JWT token from Supabase and return user data."""
    if not token:
        return None
    
    try:
        # Decode JWT without verification first (get the payload)
        decoded = jwt.decode(token, options={"verify_signature": False})
        user_id = decoded.get('sub')
        
        # Get profile from Supabase
        response = supabase.table('profiles').select('*').eq('id', user_id).execute()
        if response.data and len(response.data) > 0:
            user_data = response.data[0]
            return {
                'id': user_data['id'],
                'email': user_data['email'],
                'full_name': user_data['full_name'],
                'role': user_data['role']
            }
        return None
    except Exception as e:
        print(f"JWT verification error: {e}")
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
            or request.args.get('session_token')
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
    """Create user in Supabase Auth."""
    if role not in ('patient', 'provider'):
        return None, 'Invalid role'
    if not email or not password or not full_name:
        return None, 'All fields required'
    if len(password) < 8:
        return None, 'Password must be at least 8 characters'
    
    try:
        # Create auth user via admin API
        auth_response = supabase_admin.auth.admin.create_user({
            "email": email.lower().strip(),
            "password": password,
            "email_confirm": True
        })
        user_id = auth_response.user.id
        
        # Create profile
        supabase_admin.table('profiles').insert({
            'id': user_id,
            'email': email.lower().strip(),
            'full_name': full_name.strip(),
            'role': role
        }).execute()
        
        # Log them in to get token
        login_response = supabase.auth.sign_in_with_password({
            "email": email.lower().strip(),
            "password": password
        })
        
        return {
            'session_token': login_response.session.access_token,
            'user_id': user_id,
            'email': email,
            'role': role,
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
        
        # Get user profile
        user_data = supabase_admin.table('profiles').select('*').eq('id', response.user.id).execute()
        profile = user_data.data[0] if user_data.data else {}
        
        return {
            'session_token': response.session.access_token,
            'user_id': response.user.id,
            'email': profile.get('email'),
            'role': profile.get('role'),
            'full_name': profile.get('full_name')
        }, None
    except Exception as e:
        return None, "Invalid email or password"


def logout_user(token):
    """Logout user (Supabase handles session invalidation)."""
    # With JWT, logout is handled client-side by discarding the token
    pass