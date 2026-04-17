"""
Email service for OTP verification using Gmail SMTP.
"""

import os
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL_USER = os.environ.get("GMAIL_USER", "abhineetraj2005@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")


def generate_otp() -> str:
    """Generate a 6-digit OTP."""
    return str(random.randint(100000, 999999))


def send_otp_email(to_email: str, username: str, otp: str) -> bool:
    """Send OTP verification email. Returns True on success."""
    if not GMAIL_APP_PASSWORD:
        print(f"[EMAIL] GMAIL_APP_PASSWORD not set — OTP for {username}: {otp}")
        return True  # Allow local dev without email

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Your Agent Marketplace verification code: {otp}"
        msg["From"] = GMAIL_USER
        msg["To"] = to_email

        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; background: #0f0f0f; color: #fff; padding: 32px; border-radius: 12px;">
            <h2 style="color: #6366f1;">Agent Marketplace</h2>
            <p>Hi <strong>{username}</strong>,</p>
            <p>Your verification code is:</p>
            <div style="font-size: 40px; font-weight: bold; letter-spacing: 8px; color: #6366f1; margin: 24px 0;">
                {otp}
            </div>
            <p style="color: #aaa;">This code expires in 10 minutes. Do not share it with anyone.</p>
        </div>
        """
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, to_email, msg.as_string())

        return True
    except Exception as e:
        print(f"[EMAIL] Failed to send to {to_email}: {e}")
        return False
