"""List Ghana's regions and districts, or refresh them from new DHIS2 exports:

    python manage.py orgunits
    python manage.py orgunits --import ghana_regions_final.json ghana_districts_final.json
"""
import json

from django.core.management.base import BaseCommand

from core import orgunits


class Command(BaseCommand):
    help = "List the org units, or import them from DHIS2 organisationUnits exports (regions, then districts)."

    def add_arguments(self, parser):
        parser.add_argument("--import", nargs=2, metavar=("REGIONS", "DISTRICTS"), dest="sources")

    def handle(self, *args, **opts):
        if opts["sources"]:
            data = orgunits.from_dhis2(*opts["sources"])
            orgunits.SOURCE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            self.stdout.write(f"Wrote {orgunits.SOURCE.name}: {len(data)} regions, {sum(len(r['districts']) for r in data)} districts.")
            return
        for r in orgunits.ORG_UNITS:
            self.stdout.write(f"{r['code']:4} {r['name']} ({len(r['districts'])})")
            for c, n in r["districts"]:
                self.stdout.write(f"     {c}  {n}")
        self.stdout.write(f"{sum(len(r['districts']) for r in orgunits.ORG_UNITS)} districts")
