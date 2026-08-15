# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from django.core.management.base import BaseCommand, CommandError

from web.notifications import send_telegram_admin_notification


class Command(BaseCommand):
    help = "Send a test alert to the configured Darith Telegram admin chat."

    def handle(self, *args, **options):
        sent = send_telegram_admin_notification(
            "Telegram notifications are working",
            (("Event", "Manual server test"),),
        )
        if not sent:
            raise CommandError(
                "Telegram alert was not sent. Check the bot token, chat ID, and server logs."
            )
        self.stdout.write(self.style.SUCCESS("Telegram test notification sent."))
