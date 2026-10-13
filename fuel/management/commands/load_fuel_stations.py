import csv
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fuel.models import FuelStation
from fuel.services.geocoding import in_usa, lookup_place
from fuel.services.http import UpstreamServiceError, get_json
from fuel.services.names import normalize_state

COLUMNS = {
    "opis_id": "OPIS Truckstop ID",
    "name": "Truckstop Name",
    "address": "Address",
    "city": "City",
    "state": "State",
    "rack_id": "Rack ID",
    "price": "Retail Price",
}


class Command(BaseCommand):
    help = (
        "Loads the fuel price CSV into the database and geocodes each station offline "
        "from US Census place centroids. Use --nominatim to resolve the few leftovers online."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", type=Path, default=settings.FUEL["FUEL_PRICES_FILE"])
        parser.add_argument(
            "--nominatim",
            action="store_true",
            help="Geocode stations the Census index could not match (1 request/second).",
        )

    def handle(self, *args, file: Path, nominatim: bool, **options):
        if not file.exists():
            raise CommandError(f"{file} not found")

        stations = self._read(file)
        unmatched = []
        for station in stations.values():
            coords = lookup_place(station.city, station.state)
            if coords:
                station.latitude, station.longitude = coords
                station.geo_source = FuelStation.GeoSource.CENSUS_PLACE
            else:
                unmatched.append(station)

        if nominatim and unmatched:
            self._geocode_online(unmatched)

        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(stations.values(), batch_size=1000)

        located = sum(1 for s in stations.values() if s.latitude is not None)
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(stations)} unique stations, {located} geocoded "
                f"({len(stations) - located} without coordinates are skipped by the planner)."
            )
        )

    def _read(self, file: Path) -> dict[int, FuelStation]:
        stations: dict[int, FuelStation] = {}
        with file.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = set(COLUMNS.values()) - {name.strip() for name in reader.fieldnames or []}
            if missing:
                raise CommandError(f"CSV is missing columns: {sorted(missing)}")
            for line, raw in enumerate(reader, start=2):
                row = {key: (raw.get(column) or "").strip() for key, column in COLUMNS.items()}
                try:
                    opis_id = int(row["opis_id"])
                    price = Decimal(row["price"])
                except (ValueError, InvalidOperation):
                    self.stderr.write(f"Skipping line {line}: bad id or price")
                    continue
                state = normalize_state(row["state"])
                if not state or price <= 0:
                    continue
                # The same truck stop appears several times; keep its lowest posted price.
                existing = stations.get(opis_id)
                if existing and existing.price <= price:
                    continue
                stations[opis_id] = FuelStation(
                    opis_id=opis_id,
                    name=row["name"],
                    address=row["address"],
                    city=row["city"],
                    state=state,
                    rack_id=int(row["rack_id"]) if row["rack_id"].isdigit() else None,
                    price=price,
                )
        return stations

    def _geocode_online(self, stations: list[FuelStation]) -> None:
        by_city: dict[tuple[str, str], list[FuelStation]] = {}
        for station in stations:
            by_city.setdefault((station.city.lower(), station.state), []).append(station)

        self.stdout.write(f"Geocoding {len(by_city)} unmatched cities with Nominatim...")
        for (city, state), group in by_city.items():
            try:
                results = get_json(
                    f"{settings.FUEL['NOMINATIM_BASE_URL']}/search",
                    params={
                        "city": city,
                        "state": state,
                        "country": "us",
                        "format": "jsonv2",
                        "limit": 1,
                    },
                )
            except UpstreamServiceError as exc:
                self.stderr.write(str(exc))
                results = []
            if results:
                lat, lng = float(results[0]["lat"]), float(results[0]["lon"])
                if in_usa(lat, lng):
                    for station in group:
                        station.latitude, station.longitude = lat, lng
                        station.geo_source = FuelStation.GeoSource.NOMINATIM
            time.sleep(1.0)  # Nominatim usage policy: max 1 request per second
