import csv
import gzip
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from fuel.services.names import US_STATES, normalize_place_name, place_key

# Lower rank wins when two Census entries normalise to the same name in a state.
RANK_INCORPORATED_PLACE = 0
RANK_OTHER_PLACE = 1
RANK_COUNTY_SUBDIVISION = 2
RANK_ALIAS = 3


def _aliases(raw_name: str, rank: int):
    full = normalize_place_name(raw_name, strip_census_suffix=True)
    yield place_key(full), rank
    # Consolidated governments: "Lexington-Fayette urban county", "Macon-Bibb County"
    head = re.split(r"[-/]", raw_name, maxsplit=1)[0]
    if head != raw_name:
        yield place_key(head, strip_census_suffix=True), RANK_ALIAS
    # "Boise City city" is just "Boise" to everyone else
    if full.endswith(" city"):
        yield place_key(full.removesuffix(" city")), RANK_ALIAS


class Command(BaseCommand):
    help = (
        "Builds data/us_places.csv.gz (state, name, lat, lng) from the US Census Gazetteer "
        "place and county-subdivision files. Used for offline geocoding."
    )

    def add_arguments(self, parser):
        parser.add_argument("--places", required=True, type=Path)
        parser.add_argument("--cousubs", type=Path)
        parser.add_argument("--output", type=Path, default=settings.FUEL["PLACES_FILE"])

    def handle(self, *args, places: Path, cousubs: Path | None, output: Path, **options):
        best: dict[tuple[str, str], tuple[int, float, float, float]] = {}

        def consider(state, key, rank, land_area, lat, lng):
            if state not in US_STATES or not key:
                return
            current = best.get((state, key))
            # Prefer incorporated places, then the larger land area for ties.
            if current is None or (rank, -land_area) < (current[0], -current[1]):
                best[(state, key)] = (rank, land_area, lat, lng)

        for path, is_place in ((places, True), (cousubs, False)):
            if path is None:
                continue
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle, delimiter="|")
                reader.fieldnames = [name.strip() for name in reader.fieldnames]
                for row in reader:
                    if is_place:
                        incorporated = row["FUNCSTAT"] == "A"
                        rank = RANK_INCORPORATED_PLACE if incorporated else RANK_OTHER_PLACE
                    else:
                        rank = RANK_COUNTY_SUBDIVISION
                    lat, lng = float(row["INTPTLAT"]), float(row["INTPTLONG"])
                    land_area = float(row["ALAND_SQMI"] or 0)
                    state = row["USPS"].strip()
                    for alias, alias_rank in _aliases(row["NAME"], rank):
                        consider(state, alias, alias_rank, land_area, lat, lng)

        output.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(output, "wt", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["state", "name", "lat", "lng"])
            for (state, key), (_, _, lat, lng) in sorted(best.items()):
                writer.writerow([state, key, f"{lat:.6f}", f"{lng:.6f}"])

        self.stdout.write(self.style.SUCCESS(f"Wrote {len(best)} places to {output}"))
