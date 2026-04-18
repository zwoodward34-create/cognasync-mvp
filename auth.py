import secrets
import functools
from flask import request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
import database as db


def register_user(email, password, full_name, role):
    if role not in ('patient', 'provider'):
        return None, 'Invalid role'
    if not email or not password or not full_name:
        return None, 'All fields required'
    if len(password) < 8:
        return None, 'Password must be at least 8 characters'

    password_hash = generate_password_hash(password)
    user_id = db.create_user(email.lower().strip(), password_hash, full_name.strip(), role)
    if user_id is None:
        return None, 'Email already exists'

    token = secrets.token_hex(32)
    db.create_session(user_id, token)
    return {'user_id': user_id, 'email': email, 'role': role,
            'full_name': full_name, 'session_token': token}, None


def login_user(email, password):
    user = db.get_user_by_email(email.lower().strip())
    if not user:
        return None, 'Invalid email or password'
    if not check_password_hash(user['password_hash'], password):
        return None, 'Invalid email or password'

    token = secrets.token_hex(32)
    db.create_session(user['id'], token)
    return {
        'session_token': token,
        'user_id': user['id'],
        'role': user['role'],
        'full_name': user['full_name'],
    }, None


def logout_user(token):
    db.delete_session(token)


def get_current_user(token):
    if not token:
        return None
    return db.get_user_from_token(token)


def require_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = (
            (request.get_json(silent=True) or {}).get('session_token')
            or request.args.get('session_token')
            or request.headers.get('X-Session-Token')
        )

        user = get_current_user(token)
        if not user:
            return jsonify({'error': 'Authentication required'}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def require_provider(f):
    @functools.wraps(f)
    @require_auth
    def decorated(*args, **kwargs):
        if request.current_user['role'] != 'provider':
            return jsonify({'error': 'Provider access required'}), 403
        return f(*args, **kwargs)
    return decorated


def change_password(user_id, current_password, new_password):
    user = db.get_user_by_id(user_id)
    if not user:
        return False, 'User not found'
    if not check_password_hash(user['password_hash'], current_password):
        return False, 'Current password is incorrect'
    if len(new_password) < 8:
        return False, 'New password must be at least 8 characters'
    new_hash = generate_password_hash(new_password)
    db.update_user_password(user_id, new_hash)
    return True, 'Password updated'
