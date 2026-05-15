import os
import hmac
import hashlib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = os.environ.get('SMTP_HOST', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASS = os.environ.get('SMTP_PASS', '')
FROM_EMAIL = os.environ.get('FROM_EMAIL', SMTP_USER)
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'zwoodward@cognasync.com')
APP_URL = os.environ.get('APP_URL', 'http://localhost:5002')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
# Resend requires a verified sender. Use their shared domain for testing,
# or set FROM_EMAIL to an address on your verified domain.
_RESEND_FROM = FROM_EMAIL or 'CognaSync <onboarding@resend.dev>'


def _send_via_resend(to: str, subject: str, html: str) -> bool:
    if not RESEND_API_KEY:
        return False
    import httpx
    try:
        resp = httpx.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {RESEND_API_KEY}',
                'Content-Type': 'application/json',
            },
            json={'from': _RESEND_FROM, 'to': [to], 'subject': subject, 'html': html},
            timeout=10.0,
        )
        if resp.status_code not in (200, 201):
            print(f"[email] Resend FAILED {resp.status_code} from={_RESEND_FROM!r} to={to!r}: {resp.text}")
            return False
        print(f"[email] Resend OK: {to!r}")
        return True
    except Exception as e:
        print(f"[email] Resend exception: {e}")
        return False


def _send(to, subject, html):
    if _send_via_resend(to, subject, html):
        return
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS]):
        # No provider configured — log links so admins can extract them from Render logs,
        # then raise so callers know delivery failed (email_sent = False).
        import re as _re
        links = _re.findall(r'href="(https?://[^"]+)"', html)
        print(f"[email] NO PROVIDER — to={to} subject={subject}")
        for link in links:
            print(f"[email] LINK: {link}")
        raise RuntimeError("No email provider configured")
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = FROM_EMAIL
    msg['To'] = to
    msg.attach(MIMEText(html, 'html'))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo()
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)


def approval_sig(user_id: str, secret_key: str) -> str:
    """HMAC signature that protects the one-click admin approval link."""
    return hmac.new(
        secret_key.encode(),
        f"cognasync:approve:{user_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def send_verification_email(to_email: str, full_name: str, token: str) -> None:
    url = f"{APP_URL}/verify-email?token={token}"
    html = f"""
    <p>Hi {full_name},</p>
    <p>Thanks for registering with CognaSync. Please verify your email address:</p>
    <p style="margin:24px 0">
      <a href="{url}" style="background:#000;color:#fff;padding:12px 24px;text-decoration:none;border-radius:4px">
        Verify my email
      </a>
    </p>
    <p>Or copy this link:<br><a href="{url}">{url}</a></p>
    <p>If you didn't create a CognaSync account, you can ignore this email.</p>
    """
    _send(to_email, "Verify your CognaSync email address", html)


def send_admin_notification(user_email: str, full_name: str, role: str,
                            user_id: str, secret_key: str) -> None:
    sig = approval_sig(user_id, secret_key)
    approve_url = f"{APP_URL}/admin/approve?id={user_id}&sig={sig}"
    html = f"""
    <p>A new user has registered and verified their email on CognaSync.</p>
    <table style="border-collapse:collapse;margin:16px 0">
      <tr><td style="padding:4px 12px 4px 0"><strong>Name</strong></td><td>{full_name}</td></tr>
      <tr><td style="padding:4px 12px 4px 0"><strong>Email</strong></td><td>{user_email}</td></tr>
      <tr><td style="padding:4px 12px 4px 0"><strong>Role</strong></td><td>{role.capitalize()}</td></tr>
    </table>
    <p style="margin:24px 0">
      <a href="{approve_url}" style="background:#000;color:#fff;padding:12px 24px;text-decoration:none;border-radius:4px">
        Approve this account
      </a>
    </p>
    <p>Or copy this link:<br><a href="{approve_url}">{approve_url}</a></p>
    <p style="color:#666;font-size:12px">This link is single-use and will only work once.</p>
    """
    _send(ADMIN_EMAIL, f"New CognaSync account request — {full_name} ({role})", html)


def send_password_reset_email(to_email: str, full_name: str, token: str) -> None:
    url = f"{APP_URL}/reset-password?token={token}"
    html = f"""
    <p>Hi {full_name},</p>
    <p>We received a request to reset your CognaSync password. Click the button below to set a new one:</p>
    <p style="margin:24px 0">
      <a href="{url}" style="background:#000;color:#fff;padding:12px 24px;text-decoration:none;border-radius:4px">
        Reset my password
      </a>
    </p>
    <p>Or copy this link:<br><a href="{url}">{url}</a></p>
    <p>This link expires in 1 hour. If you didn't request a reset, you can safely ignore this email.</p>
    """
    _send(to_email, "Reset your CognaSync password", html)


def send_account_approved_email(to_email: str, full_name: str) -> None:
    login_url = f"{APP_URL}/login"
    html = f"""
    <p>Hi {full_name},</p>
    <p>Your CognaSync account has been approved. You can now sign in:</p>
    <p style="margin:24px 0">
      <a href="{login_url}" style="background:#000;color:#fff;padding:12px 24px;text-decoration:none;border-radius:4px">
        Sign in to CognaSync
      </a>
    </p>
    <p>Welcome aboard.</p>
    """
    _send(to_email, "Your CognaSync account is approved", html)
