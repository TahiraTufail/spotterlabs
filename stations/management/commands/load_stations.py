import csv
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from stations.cities import US_STATES, lookup_city
from stations.index import reset_index
from stations.models import Station


class Command(BaseCommand):
    help = "Load fuel stations from the price CSV: merge duplicate IDs (lowest price), drop non-US rows, geocode by city."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", nargs="?", default=str(settings.BASE_DIR / "data" / "fuel-prices.csv"))

    def handle(self, *args, **options):
        merged = {}
        rows = dropped_non_us = 0
        with open(options["csv_path"], newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                rows += 1
                state = row["State"].strip().upper()
                if state not in US_STATES:
                    dropped_non_us += 1
                    continue
                station_id, price = int(row["OPIS Truckstop ID"]), Decimal(row["Retail Price"])
                current = merged.get(station_id)
                if current is None:
                    merged[station_id] = {
                        "opis_id": station_id,
                        "name": row["Truckstop Name"].strip(),
                        "address": row["Address"].strip(),
                        "city": row["City"].strip(),
                        "state": state,
                        "price": price,
                    }
                elif price < current["price"]:
                    current["price"] = price

        stations, unmatched = [], 0
        for data in merged.values():
            coords = lookup_city(data["city"], data["state"])
            if coords is None:
                unmatched += 1
                continue
            stations.append(Station(lat=coords[0], lng=coords[1], **data))

        with transaction.atomic():
            Station.objects.all().delete()
            Station.objects.bulk_create(stations, batch_size=1000)
        reset_index()
        self.stdout.write(
            f"rows={rows} dropped_non_us={dropped_non_us} unique_ids={len(merged)} "
            f"loaded={len(stations)} unmatched={unmatched}"
        )
