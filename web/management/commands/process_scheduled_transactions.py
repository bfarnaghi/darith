# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
from datetime import date

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from web.services import pending_plan_occurrences


class Command(BaseCommand):
    help = (
        "Report planned items that need confirmation. Darith is passive and "
        "does not change balances automatically."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            dest="through_date",
            help="Check through YYYY-MM-DD (defaults to today).",
        )

    def handle(self, *args, **options):
        through_date = timezone.localdate()
        if options["through_date"]:
            try:
                through_date = date.fromisoformat(options["through_date"])
            except ValueError as error:
                raise CommandError("Date must use YYYY-MM-DD.") from error

        waiting = 0
        for user in User.objects.iterator():
            waiting += len(pending_plan_occurrences(user, through_date))
        self.stdout.write(
            self.style.SUCCESS(
                f"Found {waiting} planned item(s) waiting for confirmation "
                f"through {through_date}. No balances were changed."
            )
        )
