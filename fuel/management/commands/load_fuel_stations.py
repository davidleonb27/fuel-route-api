import csv
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fuel.models import FuelStation
from fuel.services.geocoding import in_usa, lookup_place
from fuel.services.http import UpstreamServiceError, get_json
from fuel.services.ingest import IngestError, StationRecord, read_fuel_csv
from fuel.services.names import place_key

UPDATE_FIELDS = [
    "name",
    "address",
    "city",
    "state",
    "rack_id",
    "price",
    "price_min",
    "price_max",
    "price_observations",
    "latitude",
    "longitude",
    "geo_source",
]


class Command(BaseCommand):
    help = (
        "Cleans and loads the fuel price CSV, geocodes stations offline from US Census "
        "place centroids, and prints a data-quality report. Safe to re-run."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", type=Path, default=settings.FUEL["FUEL_PRICES_FILE"])
        parser.add_argument(
            "--nominatim",
            action="store_true",
            help="Geocode cities the Census index can't match (1 req/s) and save the results "
            "to data/station_geocodes.csv so later loads stay offline.",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Report only; don't touch the database."
        )

    def handle(self, *args, file: Path, nominatim: bool, dry_run: bool, **options):
        if not file.exists():
            raise CommandError(f"{file} not found")
        try:
            records, report = read_fuel_csv(file)
        except IngestError as exc:
            raise CommandError(str(exc)) from exc

        stations = [self._to_model(record) for record in records]
        overrides = _load_overrides()
        unmatched = [s for s in stations if not self._geocode_offline(s, overrides)]
        if nominatim and unmatched:
            self._geocode_online(unmatched, overrides)
            unmatched = [s for s in unmatched if s.latitude is None]

        for line in report.lines():
            self.stdout.write(f"  {line}")
        located = len(stations) - len(unmatched)
        self.stdout.write(f"  geocoded: {located}/{len(stations)}")
        if unmatched:
            places = sorted({f"{s.city}, {s.state}" for s in unmatched})
            self.stdout.write(f"  not located (ignored by the planner): {places}")
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: database unchanged."))
            return

        with transaction.atomic():
            FuelStation.objects.bulk_create(
                stations,
                batch_size=500,
                update_conflicts=True,
                unique_fields=["opis_id"],
                update_fields=UPDATE_FIELDS,
            )
            removed, _ = FuelStation.objects.exclude(
                opis_id__in=[s.opis_id for s in stations]
            ).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(stations)} stations ({removed} no longer in the file removed)."
            )
        )

    @staticmethod
    def _to_model(record: StationRecord) -> FuelStation:
        return FuelStation(
            opis_id=record.opis_id,
            name=record.name,
            address=record.address,
            city=record.city,
            state=record.state,
            rack_id=record.rack_id,
            price=record.price,
            price_min=record.price_min,
            price_max=record.price_max,
            price_observations=record.observations,
        )

    @staticmethod
    def _geocode_offline(station: FuelStation, overrides: dict) -> bool:
        if coords := lookup_place(station.city, station.state):
            station.latitude, station.longitude = coords
            station.geo_source = FuelStation.GeoSource.CENSUS_PLACE
            return True
        if coords := overrides.get((station.state, place_key(station.city))):
            station.latitude, station.longitude = coords
            station.geo_source = FuelStation.GeoSource.NOMINATIM
            return True
        return False

    def _geocode_online(self, stations: list[FuelStation], overrides: dict) -> None:
        by_city: dict[tuple[str, str], list[FuelStation]] = {}
        for station in stations:
            by_city.setdefault((station.state, station.city), []).append(station)

        self.stdout.write(f"Geocoding {len(by_city)} unmatched cities with Nominatim...")
        for (state, city), group in by_city.items():
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
                    overrides[(state, place_key(city))] = (lat, lng)
                    for station in group:
                        station.latitude, station.longitude = lat, lng
                        station.geo_source = FuelStation.GeoSource.NOMINATIM
            time.sleep(1.0)  # Nominatim usage policy: max 1 request per second
        _save_overrides(overrides)


def _load_overrides() -> dict[tuple[str, str], tuple[float, float]]:
    path = settings.FUEL["STATION_GEOCODES_FILE"]
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            (row["state"], row["key"]): (float(row["lat"]), float(row["lng"]))
            for row in csv.DictReader(handle)
        }


def _save_overrides(overrides) -> None:
    # Committed to the repo so later loads never need the network.
    with settings.FUEL["STATION_GEOCODES_FILE"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["state", "key", "lat", "lng"])
        for (state, key), (lat, lng) in sorted(overrides.items()):
            writer.writerow([state, key, f"{lat:.6f}", f"{lng:.6f}"])
