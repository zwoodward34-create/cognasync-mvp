#!/usr/bin/env python3
"""
Create a provider account directly via the Supabase service key.

Usage:
    python3 scripts/create_provider.py <email> <password> <full_name>

Example:
    python3 scripts/create_provider.py dr.smith@example.com MyPassword123 "Dr. Smith"
"""
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    sys.exit('Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env')

if len(sys.argv) != 4:
    sys.exit(f'Usage: python3 {sys.argv[0]} <email> <password> <full_name>')

email, password, full_name = sys.argv[1], sys.argv[2], sys.argv[3]

if len(password) < 8:
    sys.exit('Error: password must be at least 8 characters')

admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

try:
    auth_response = admin.auth.admin.create_user({
        'email': email.lower().strip(),
        'password': password,
        'email_confirm': True,
    })
    user_id = auth_response.user.id
    print(f'Auth user created: {user_id}')
except Exception as e:
    sys.exit(f'Failed to create auth user: {e}')

try:
    admin.table('profiles').insert({
        'id': user_id,
        'email': email.lower().strip(),
        'full_name': full_name.strip(),
        'role': 'provider',
    }).execute()
    print(f'Profile created with role=provider')
except Exception as e:
    # Clean up the auth user so we don't leave an orphan
    try:
        admin.auth.admin.delete_user(user_id)
    except Exception:
        pass
    sys.exit(f'Failed to create profile: {e}')

print(f'\nProvider account ready:')
print(f'  Email:    {email}')
print(f'  Name:     {full_name}')
print(f'  Role:     provider')
print(f'  User ID:  {user_id}')
