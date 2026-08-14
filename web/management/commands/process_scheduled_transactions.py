# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from datetime import date

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from web.services import post_due_recurring


class Command(BaseCommand):
    help = "Post all recurring income and expense entries due through a date."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            dest="through_date",
            help="Process through YYYY-MM-DD (defaults to today).",
        )

    def handle(self, *args, **options):
        through_date = timezone.localdate()
        if options["through_date"]:
            try:
                through_date = date.fromisoformat(options["through_date"])
            except ValueError as error:
                raise CommandError("Date must use YYYY-MM-DD.") from error

        posted = 0
        for user in User.objects.iterator():
            posted += post_due_recurring(user, through_date)
        self.stdout.write(
            self.style.SUCCESS(
                f"Posted {posted} scheduled transaction(s) through {through_date}."
            )
        )
