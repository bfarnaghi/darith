# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import json
import logging
from urllib.request import Request, urlopen

from django.conf import settings


logger = logging.getLogger(__name__)
TELEGRAM_API_ROOT = "https://api.telegram.org"


def _single_line(value, fallback="Not provided"):
    cleaned = " ".join(str(value or "").split())
    return cleaned[:500] or fallback


def send_telegram_admin_notification(title, details):
    """Send a private admin alert without affecting the originating request."""
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return False

    lines = ["Darith admin alert", "", _single_line(title)]
    lines.extend(
        f"{_single_line(label)}: {_single_line(value)}"
        for label, value in details
    )
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": "\n".join(lines)[:4000],
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    request = Request(
        f"{TELEGRAM_API_ROOT}/bot{token}/sendMessage",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Darith admin notifications",
        },
        method="POST",
    )

    try:
        with urlopen(
            request,
            timeout=settings.TELEGRAM_NOTIFICATION_TIMEOUT_SECONDS,
        ) as response:
            result = json.loads(response.read(2048).decode("utf-8"))
        if not result.get("ok"):
            logger.warning("Telegram rejected a Darith admin notification.")
            return False
    except Exception as error:  # A notification must never break a user action.
        logger.warning(
            "Telegram admin notification failed (%s).",
            type(error).__name__,
        )
        return False
    return True


def notify_new_user(user):
    return send_telegram_admin_notification(
        "New user created",
        (("Username", user.username), ("Email", user.email)),
    )


def notify_feedback(feedback):
    return send_telegram_admin_notification(
        "New feedback received",
        (("Username", feedback.user.username), ("Page", feedback.page)),
    )


def notify_subscription_payment(subscription):
    return send_telegram_admin_notification(
        "Subscription payment reported",
        (
            ("Username", subscription.user.username),
            ("Reference", subscription.payment_reference),
        ),
    )
