"""Send today's AFP 60-day follow-up reminders by SMS. Run it once a day:

    python manage.py send_reminders              send
    python manage.py send_reminders --dry-run    show what would be sent, send nothing
    python manage.py send_reminders --region "Upper East"

cPanel (Cron Jobs), every day at 08:00:
    0 8 * * * cd ~/surveillance && ~/virtualenv/surveillance/3.12/bin/python manage.py send_reminders
Windows (Task Scheduler), every day at 08:00:
    schtasks /Create /SC DAILY /ST 08:00 /TN "AFP SMS reminders" /TR "cmd /c cd /d \"<project folder>\" && python manage.py send_reminders"
"""
from django.core.management.base import BaseCommand, CommandError

from core import orgunits
from core.locks import write_lock
from reminders import letsfish, service


class Command(BaseCommand):
    help = "Send today's AFP 60-day follow-up reminders (due soon and overdue) by SMS to district officers."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show the messages; send nothing.")
        parser.add_argument("--region", default="", help="Only this region.")

    def handle(self, *args, dry_run=False, region="", **kw):
        if region:
            unit = orgunits.region_of(region)
            if not unit:
                raise CommandError(f"There is no region called {region}.")
            region = unit["name"]
        if not dry_run and not letsfish.configured():
            raise CommandError("SMS is not set up: the support account enters the Fish Africa details on the SMS reminders page (or set LETSFISH_APP_ID, LETSFISH_APP_SECRET and LETSFISH_SENDER_ID in .env).")
        with write_lock():  # never twice at once (the page's Send now, or a second scheduled run)
            results = service.run(region=region or None, dry_run=dry_run)
        if not results:
            self.stdout.write("No reminders to send today.")
            return
        sent = failed = 0
        for r in results:
            state = "WOULD SEND" if dry_run else "SENT" if r["ok"] else "FAILED"
            self.stdout.write(f"--- {state} to {r['name']} ({r['place']}) {r['to']}, {len(r['cases'])} case(s)")
            self.stdout.write(r["text"])
            if r["error"]:
                self.stderr.write("    " + r["error"])
            sent += bool(r["ok"])
            failed += r["ok"] is False
        self.stdout.write(f"{len(results)} message(s)" + ("" if dry_run else f": {sent} sent, {failed} failed."))
        if failed:
            raise CommandError(f"{failed} message(s) failed; they will be tried again on the next run.")
