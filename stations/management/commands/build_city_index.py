import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stations.cities import CITY_INDEX_PATH, US_STATES, normalize_place

MIN_POPULATION_FOR_ALTERNATES = 500


class Command(BaseCommand):
    help = "Build stations/data/us_cities.csv from the GeoNames US.txt dump (CC BY 4.0)."

    def add_arguments(self, parser):
        parser.add_argument("geonames_txt", help="Path to US.txt from download.geonames.org/export/dump/US.zip")

    def handle(self, *args, **options):
        source = Path(options["geonames_txt"])
        if not source.exists():
            raise CommandError(f"{source} not found")

        best = {}  # (normalized name, state) -> (population, lat, lng)

        def offer(name, state, population, lat, lng):
            key = (normalize_place(name), state)
            if key[0] and (key not in best or population > best[key][0]):
                best[key] = (population, lat, lng)

        with open(source, encoding="utf-8") as fh:
            for line in fh:
                f = line.rstrip("\n").split("\t")
                if len(f) < 15 or f[6] != "P" or f[10] not in US_STATES:
                    continue
                population, lat, lng, state = int(f[14] or 0), float(f[4]), float(f[5]), f[10]
                offer(f[2], state, population, lat, lng)
                if population >= MIN_POPULATION_FOR_ALTERNATES:
                    for alt in f[3].split(","):
                        if alt.isascii() and 0 < len(alt) <= 40:
                            offer(alt, state, population, lat, lng)

        CITY_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CITY_INDEX_PATH, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["name", "state", "lat", "lng"])
            for (name, state), (_, lat, lng) in sorted(best.items()):
                writer.writerow([name, state, f"{lat:.4f}", f"{lng:.4f}"])
        self.stdout.write(f"wrote {len(best)} entries to {CITY_INDEX_PATH}")
