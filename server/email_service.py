"""Maison Henius — branded transactional emails via Resend."""
import html
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


def send_order_status_email(to_email: str, order_id: str, customer_name: str, new_status: str, base_url: str = "https://maisonhenius.com", courier: str = "", tracking: str = ""):
    """Send branded order status notification email via Resend.
    Only sends for shipped, delivered, and cancelled statuses.
    Returns the Resend response dict or None if status doesn't trigger email."""
    config = _ORDER_STATUS_CONFIG.get(new_status)
    if not config:
        return None

    greeting = f"Dear {customer_name}," if customer_name else ""
    body_html = config["body"].format(order_id=order_id)
    # Shipped emails sent from the Fulfilment page carry the courier + tracking
    # number the warehouse entered (escaped: it is free text).
    if new_status == "shipped" and (courier or tracking):
        bits = []
        if courier:
            bits.append(f"Courier: <strong>{html.escape(courier)}</strong>")
        if tracking:
            bits.append(f"Tracking number: <strong>{html.escape(tracking)}</strong>")
        body_html += "<br><br>" + "<br>".join(bits)
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


# --- Team access (warehouse / fulfilment staff) ---

def _build_staff_invite_html(link: str, name: str = "", reset: bool = False) -> str:
    who = f"Dear {html.escape(name)},<br><br>" if name else ""
    if reset:
        body = (who + "A new sign-in set-up has been requested for your Maison Henius "
                "fulfilment account. Click below to choose a password and link your "
                "authenticator app.")
    else:
        body = (who + "You have been invited to the Maison Henius fulfilment portal, where "
                "you will see the orders to prepare and dispatch. Click below to choose "
                "your password and link an authenticator app for the 2-step sign-in code.")
    return _base_html(
        headline="Set Up Your Access" if reset else "You Are Invited",
        body_content=body,
        cta_text="Set Up My Access",
        cta_url=link,
        footer_note="This link works once and expires after a short time. If it has expired, ask Maison Henius to send a new one. If you were not expecting this email, you can ignore it.",
    )


def send_staff_invite(to_email: str, link: str, name: str = "", reset: bool = False):
    """Branded invitation (or set-up again) for a fulfilment staff account."""
    return resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": ("Set Up Your Access" if reset else "Your Invitation") + " \u2014 Maison Henius Fulfilment",
        "html": _build_staff_invite_html(link, name, reset),
    })


# --- Stock requests from the warehouse (owners approve on the Stock page) ---

def send_stock_request_notice(to_emails: list, requester: str, product: str, kind_label: str,
                              change: int, current_stock: int, note: str, link: str):
    """Tell the owners a warehouse stock change is waiting for their approval."""
    e = html.escape
    body = (f"<strong>{e(requester)}</strong> recorded a stock change that needs your approval.<br><br>"
            f"Product: <strong>{e(product)}</strong><br>"
            f"Change: <strong>{e(kind_label)} ({change:+d})</strong><br>"
            f"Stock now: {current_stock} &rarr; after approval: {max(0, current_stock + change)}<br>"
            f"Note: {e(note)}<br><br>"
            "The stock on the website does not change until you approve it.")
    return resend.Emails.send({
        "from": FROM_EMAIL,
        "to": list(to_emails),
        "subject": f"Stock approval needed: {product} ({change:+d}) — Maison Henius",
        "html": _base_html(
            headline="Stock Approval Needed",
            body_content=body,
            cta_text="Review on the Stock page",
            cta_url=link,
            footer_note="Sent to the Maison Henius owners because the warehouse recorded a stock change.",
        ),
    })


def send_staff_ready(to_email: str, name: str, login_url: str):
    """Sent once, when a fulfilment account finishes set-up: the sign-in link to keep."""
    who = f"Dear {html.escape(name)},<br><br>" if name else ""
    body = (who + "Your access to the Maison Henius fulfilment portal is ready.<br><br>"
            "To sign in at any time, use the button below (we suggest you bookmark the page):<br>"
            "1. Enter your work email and the password you chose.<br>"
            "2. Enter the 6-digit code from your authenticator app.<br><br>"
            f"Sign-in address: <a href=\"{html.escape(login_url)}\" style=\"color:#e9db90;\">{html.escape(login_url)}</a>")
    return resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": "Your Access Is Ready \u2014 Maison Henius Fulfilment",
        "html": _base_html(
            headline="Your Access Is Ready",
            body_content=body,
            cta_text="Sign In",
            cta_url=login_url,
            footer_note="Forgotten your password or changed phone? Ask Maison Henius to send you a new set-up link. Never share your password or codes.",
        ),
    })


# --- Step 2: warehouse new-order email + owner issue alert ---

def _when(iso: str) -> str:
    from datetime import datetime
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return d.strftime("%d %b %Y, %H:%M UTC")
    except Exception:
        return str(iso or "")


def send_warehouse_new_order(to_email: str, data: dict, link: str):
    """New paid order for the warehouse. Owner's choice of detail: products, SKU,
    quantities, name + city + country, declared value. No phone, email or street."""
    e = html.escape
    n = sum(int(i.get("quantity") or 1) for i in data.get("items", []))
    lines = "".join(
        f"&bull; <strong>{e(i['name'])}</strong> &times; {int(i['quantity'])}<br>"
        f"<span style=\"color:rgba(250,249,246,0.5);font-size:12px;\">SKU {e(i['sku'])}"
        + (f" &middot; {e(i['variant'])}" if i.get("variant") else "") + "</span><br>"
        for i in data.get("items", []))
    body = (
        f"Order <strong>{e(data['order_id'])}</strong> &middot; paid {e(_when(data.get('paid_on')))}<br>"
        "Payment status: <strong>Paid</strong><br><br>"
        f"{lines}<br>"
        f"Deliver to: <strong>{e(data.get('customer_name') or '')}</strong> &middot; "
        f"{e(data.get('city') or '')}, {e(data.get('country') or '')}<br>"
        "<span style=\"color:rgba(250,249,246,0.5);font-size:12px;\">The full address, phone and email are in the portal.</span><br>"
        + ("Special delivery instructions: <strong>yes, see the portal</strong><br>" if data.get("has_instructions") else "")
        + f"Declared value (customs &amp; insurance): <strong>USD {float(data.get('declared_value') or 0):,.2f}</strong><br><br>"
        "Next steps: open the order, confirm receipt, prepare and pack, then enter the courier, "
        "tracking number and actual shipping cost when you dispatch. Report any problem with &ldquo;Flag an issue&rdquo;."
    )
    return resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"New order to fulfil · {data['order_id']} · {n} item{'s' if n != 1 else ''} · {data.get('country') or ''}",
        "html": _base_html(
            headline="New Order to Fulfil",
            body_content=body,
            cta_text="Open the Order",
            cta_url=link,
            footer_note="Secure link: you will be asked to sign in with your password and 6-digit code. You receive this email because Maison Henius added this address to its order notifications.",
        ),
    })


def send_owner_issue_alert(to_emails: list, order_id: str, issue_type: str, note: str, by: str, link: str):
    """Tell the owners the warehouse flagged a problem on an order."""
    e = html.escape
    body = (f"<strong>{e(by)}</strong> flagged an issue on order <strong>{e(order_id)}</strong>.<br><br>"
            f"Issue: <strong>{e(issue_type)}</strong><br>"
            f"Details: {e(note)}<br><br>"
            "Open the order to see the details and reply with a comment.")
    return resend.Emails.send({
        "from": FROM_EMAIL,
        "to": list(to_emails),
        "subject": f"Issue on order {order_id}: {issue_type} — Maison Henius",
        "html": _base_html(
            headline="Fulfilment Issue",
            body_content=body,
            cta_text="Open the Order",
            cta_url=link,
            footer_note="Sent to the Maison Henius owners because the warehouse flagged an issue.",
        ),
    })


# --- Step 3: customer order confirmation with the itemised total ---

def send_order_confirmation(to_email: str, name: str, order: dict, profile_url: str):
    """Branded 'Order Confirmed' email: products and every charge the customer paid."""
    e = html.escape
    money = lambda v: f"USD {float(v or 0):,.2f}"
    rows = "".join(
        f"{e(str(i.get('name', '')))} &times; {int(i.get('quantity') or 1)} &mdash; {money(float(i.get('price') or 0) * int(i.get('quantity') or 1))}<br>"
        for i in (order.get("items") or []))
    lines = [("Products", order.get("subtotal")), ("Shipping", order.get("shipping")),
             ("Door-to-door delivery", order.get("door_to_door_fee"))]
    if float(order.get("additional_fee") or 0) > 0:
        lines.append((order.get("additional_label") or "Additional charges", order.get("additional_fee")))
    if float(order.get("tax_amount") or 0) > 0:
        lines.append((order.get("tax_label") or "Tax", order.get("tax_amount")))
    if float(order.get("discount_amount") or 0) > 0:
        lines.append(("Discount", -float(order.get("discount_amount"))))
    breakdown = "".join(f"{e(str(label))}: {money(v)}<br>" for label, v in lines)
    a = order.get("shipping_address") or {}
    where = ", ".join(x for x in (a.get("city"), a.get("country")) if x)
    body = ((f"Dear {e(name)},<br><br>" if name else "")
            + f"Thank you. Your order <strong>{e(str(order.get('id', '')))}</strong> is confirmed and is being prepared.<br><br>"
            + rows + "<br>" + breakdown
            + f"<strong>Total paid: {money(order.get('total'))}</strong><br><br>"
            + (f"Delivering to {e(where)}. " if where else "")
            + "We will email you again when it ships, with the courier and tracking number.")
    return resend.Emails.send({
        "from": FROM_EMAIL,
        "to": [to_email],
        "subject": f"Order Confirmed — {order.get('id', '')} — Maison Henius",
        "html": _base_html(
            headline="Order Confirmed",
            body_content=body,
            cta_text="View Your Order",
            cta_url=profile_url,
            footer_note="Keep this email as your record of the order. Questions? Reply through the contact form on our website.",
        ),
    })
