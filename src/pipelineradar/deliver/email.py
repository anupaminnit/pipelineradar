"""Email delivery via SMTP.

Renders the markdown brief as an HTML email and sends it via the configured
SMTP server. Requires SMTP_HOST, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM,
EMAIL_TO in Settings.

Phase 4: implement EmailDelivery.send(brief: Brief) -> None.
"""

from __future__ import annotations

# Phase 4: implement EmailDelivery
