"""Maison Henius — branded transactional emails via Resend."""
import os
import resend
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

resend.api_key = os.getenv("RESEND_API_KEY", "")

FROM_EMAIL = "Maison Henius <noreply@maisonhenius.com>"


def _base_html(headline: str, body_content: str, cta_text: str, cta_url: str, footer_note: str) -> str:
    """Shared branded email shell. All 3 templates use this."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{headline} — Maison Henius</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;1,300&family=Montserrat:wght@300;400&display=swap');
  </style>
</head>
<body style="margin:0;padding:0;background:#0a0a08;font-family:'Montserrat',Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a08;">
    <tr>
      <td align="center" style="padding:40px 20px;">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">
          <!-- Logo -->
          <tr>
            <td align="center" style="padding-bottom:32px;">
              <span style="font-family:'Cormorant Garamond',Georgia,serif;font-size:28px;font-weight:300;font-style:italic;color:#e9db90;letter-spacing:0.05em;">Maison Henius</span>
            </td>
          </tr>
          <!-- Headline -->
          <tr>
            <td align="center" style="padding-bottom:16px;">
              <h1 style="margin:0;font-family:'Cormorant Garamond',Georgia,serif;font-size:32px;font-weight:300;font-style:italic;color:#faf9f6;letter-spacing:0.02em;">{headline}</h1>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td align="center" style="padding-bottom:32px;">
              <p style="margin:0;font-family:'Montserrat',Helvetica,Arial,sans-serif;font-size:14px;font-weight:300;color:rgba(250,249,246,0.7);line-height:1.7;letter-spacing:0.02em;max-width:440px;">{body_content}</p>
            </td>
          </tr>
          <!-- CTA Button -->
          <tr>
            <td align="center" style="padding-bottom:40px;">
              <a href="{cta_url}" style="display:inline-block;padding:14px 40px;background:#e9db90;color:#0a0a08;font-family:'Montserrat',Helvetica,Arial,sans-serif;font-size:12px;font-weight:400;letter-spacing:0.2em;text-transform:uppercase;text-decoration:none;border:1px solid #e9db90;">{cta_text}</a>
            </td>
          </tr>
          <!-- Divider -->
          <tr>
            <td style="padding-bottom:24px;">
              <hr style="border:none;border-top:1px solid rgba(233,219,144,0.15);margin:0;">
            </td>
          </tr>
          <!-- Footer note -->
          <tr>
            <td align="center" style="padding-bottom:16px;">
              <p style="margin:0;font-family:'Montserrat',Helvetica,Arial,sans-serif;font-size:11px;font-weight:300;color:rgba(250,249,246,0.3);letter-spacing:0.02em;">{footer_note}</p>
            </td>
          </tr>
          <!-- Tagline -->
          <tr>
            <td align="center">
              <p style="margin:0;font-family:'Cormorant Garamond',Georgia,serif;font-size:13px;font-style:italic;color:rgba(233,219,144,0.4);letter-spacing:0.05em;">Essences Beyond Time.</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _build_signup_html(confirmation_link: str, name: str = "") -> str:
    greeting = f"Welcome, {name}" if name else "Welcome"
    return _base_html(
        headline=greeting,
        body_content="Thank you for joining Maison Henius. Please confirm your email address to complete your registration and begin your journey with us.",
        cta_text="Confirm Your Account",
        cta_url=confirmation_link,
        footer_note="If you didn\u2019t create an account, you can safely ignore this email.",
    )


def _build_reset_html(reset_link: str) -> str:
    return _base_html(
        headline="Reset Your Password",
        body_content="We received a request to reset the password for your Maison Henius account. Click below to choose a new password.",
        cta_text="Reset Password",
        cta_url=reset_link,
        footer_note="This link expires in 1 hour. If you didn\u2019t request this, ignore this email.",
    )


def _build_admin_link_html(magic_link: str) -> str:
    return _base_html(
        headline="Your Login Link",
        body_content="Click below to securely access the Maison Henius admin dashboard.",
        cta_text="Sign In",
        cta_url=magic_link,
        footer_note="This link expires in 10 minutes. Do not share it with anyone.",
    )


def send_signup_confirmation(to_email: str, confirmation_link: str, name: str = ""):
    """Send branded signup confirmation email via Resend."""
    return resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": "Confirm Your Account \u2014 Maison Henius",
        "html": _build_signup_html(confirmation_link, name),
    })


def send_password_reset(to_email: str, reset_link: str):
    """Send branded password reset email via Resend."""
    return resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": "Reset Your Password \u2014 Maison Henius",
        "html": _build_reset_html(reset_link),
    })


def send_admin_login_link(to_email: str, magic_link: str):
    """Send branded admin magic link email via Resend."""
    return resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": "Your Login Link \u2014 Maison Henius",
        "html": _build_admin_link_html(magic_link),
    })


# --- Order status notification emails ---

_ORDER_STATUS_CONFIG = {
    "shipped": {
        "subject": "Your Order Is On Its Way \u2014 Maison Henius",
        "headline": "Your Order Is On Its Way",
        "body": "Order <strong>{order_id}</strong> has been shipped. Your Maison Henius fragrance is on its way to you.",
        "cta_text": "View Your Account",
        "cta_path": "/profile",
        "footer": "You\u2019ll receive another email once your order has been delivered.",
    },
    "delivered": {
        "subject": "Your Order Has Arrived \u2014 Maison Henius",
        "headline": "Your Order Has Arrived",
        "body": "Order <strong>{order_id}</strong> has been delivered. We hope your Maison Henius fragrance brings you joy with every wear.",
        "cta_text": "Explore More Fragrances",
        "cta_path": "/#fragrances",
        "footer": "Thank you for choosing Maison Henius.",
    },
    "cancelled": {
        "subject": "Order Cancelled \u2014 Maison Henius",
        "headline": "Order Cancelled",
        "body": "Order <strong>{order_id}</strong> has been cancelled. If you have any questions, please don\u2019t hesitate to reach out to us.",
        "cta_text": "Contact Us",
        "cta_path": "/#contact",
        "footer": "If this was a mistake, please contact us and we\u2019ll be happy to help.",
    },
}


def send_order_status_email(to_email: str, order_id: str, customer_name: str, new_status: str, base_url: str = "https://maisonhenius.com"):
    """Send branded order status notification email via Resend.
    Only sends for shipped, delivered, and cancelled statuses.
    Returns the Resend response dict or None if status doesn't trigger email."""
    config = _ORDER_STATUS_CONFIG.get(new_status)
    if not config:
        return None

    greeting = f"Dear {customer_name}," if customer_name else ""
    body_html = config["body"].format(order_id=order_id)
    if greeting:
        body_html = f"{greeting}<br><br>{body_html}"

    html = _base_html(
        headline=config["headline"],
        body_content=body_html,
        cta_text=config["cta_text"],
        cta_url=f"{base_url}{config['cta_path']}",
        footer_note=config["footer"],
    )

    return resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": config["subject"],
        "html": html,
    })
