"""Optional delivery of the daily report.

Writing a report to disk is only useful if you actually look at it. These
helpers push it to where you already are. Both are opt-in and configured by
environment variable, so nothing is sent unless you ask for it.
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
from email.message import EmailMessage


def send_email(subject: str, text_body: str, html_body: str | None = None) -> str:
    """Email the report using SMTP settings from the environment.

    Requires QUANTDESK_SMTP_HOST, QUANTDESK_SMTP_USER, QUANTDESK_SMTP_PASSWORD
    and QUANTDESK_EMAIL_TO. Port defaults to 587 with STARTTLS.
    """
    host = os.environ.get("QUANTDESK_SMTP_HOST", "").strip()
    user = os.environ.get("QUANTDESK_SMTP_USER", "").strip()
    password = os.environ.get("QUANTDESK_SMTP_PASSWORD", "").strip()
    recipient = os.environ.get("QUANTDESK_EMAIL_TO", "").strip()
    port = int(os.environ.get("QUANTDESK_SMTP_PORT", "587"))

    missing = [
        name for name, value in [
            ("QUANTDESK_SMTP_HOST", host), ("QUANTDESK_SMTP_USER", user),
            ("QUANTDESK_SMTP_PASSWORD", password), ("QUANTDESK_EMAIL_TO", recipient),
        ] if not value
    ]
    if missing:
        return f"email skipped - not configured ({', '.join(missing)})"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = user
    message["To"] = recipient
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=context)
        server.login(user, password)
        server.send_message(message)
    return f"emailed to {recipient}"


def send_webhook(summary: dict) -> str:
    """POST a JSON summary to QUANTDESK_WEBHOOK_URL (Slack, Discord, anything)."""
    url = os.environ.get("QUANTDESK_WEBHOOK_URL", "").strip()
    if not url:
        return "webhook skipped - QUANTDESK_WEBHOOK_URL not set"

    import urllib.request

    payload = json.dumps(summary).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return f"webhook responded {response.status}"
