import csv
import gzip
import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings
from django.core.cache import cache

from .http import get_json
from .names import normalize_place_name, normalize_state, place_key

# Contiguous US + Alaska; Hawaii is unreachable by road so it is rejected.
_US_BOUNDS = ((24.0, 50.0, -125.0, -66.5), (51.0, 71.5, -170.0, -129.0))
_COORDS = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


class GeocodingError(Exception):
    pass


@dataclass(frozen=True)
class Location:
    query: str
    label: str
    lat: float
    lng: float
    source: str

    def as_dict(self) -> dict:
        return {
            "query": self.query,
            "label": self.label,
            "lat": round(self.lat, 6),
            "lng": round(self.lng, 6),
            "source": self.source,
        }


def in_usa(lat: float, lng: float) -> bool:
    return any(s <= lat <= n and w <= lng <= e for s, n, w, e in _US_BOUNDS)


@lru_cache(maxsize=1)
def place_index() -> dict[tuple[str, str], tuple[float, float]]:
    index = {}
    with gzip.open(settings.FUEL["PLACES_FILE"], "rt", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            index[(row["state"], row["name"])] = (float(row["lat"]), float(row["lng"]))
    return index


def lookup_place(city: str, state: str) -> tuple[float, float] | None:
    code = normalize_state(state)
    if not code:
        return None
    return place_index().get((code, place_key(city)))


def _split_city_state(query: str) -> tuple[str, str] | None:
    parts = [part.strip() for part in query.split(",") if part.strip()]
    if parts and parts[-1].lower() in {"usa", "us", "united states", "united states of america"}:
        parts = parts[:-1]
    if len(parts) == 2:
        return parts[0], parts[1]
    # "Austin TX" / "Salt Lake City Utah"
    tokens = query.replace(",", " ").split()
    for size in (3, 2, 1):
        if len(tokens) > size and normalize_state(" ".join(tokens[-size:])):
            return " ".join(tokens[:-size]), " ".join(tokens[-size:])
    return None


def geocode(query: str) -> tuple[Location, int]:
    """Returns the location and the number of external API calls it took (0 or 1)."""
    query = query.strip()
    if not query:
        raise GeocodingError("Location must not be empty")

    if match := _COORDS.match(query):
        lat, lng = float(match.group(1)), float(match.group(2))
        if not in_usa(lat, lng):
            raise GeocodingError(f"'{query}' is not inside the continental USA or Alaska")
        return Location(query, f"{lat:.5f}, {lng:.5f}", lat, lng, "coordinates"), 0

    if split := _split_city_state(query):
        city, state = split
        coords = lookup_place(city, state)
        if coords and not in_usa(*coords):
            raise GeocodingError(f"'{query}' is not reachable by road from the mainland USA")
        if coords:
            code = normalize_state(state)
            label = f"{city.strip().title()}, {code}"
            return Location(query, label, *coords, "census_place"), 0

    cache_key = "geocode:v1:" + hashlib.sha256(normalize_place_name(query).encode()).hexdigest()
    if cached := cache.get(cache_key):
        return Location(query, *cached, "nominatim"), 0

    results = get_json(
        f"{settings.FUEL['NOMINATIM_BASE_URL']}/search",
        params={"q": query, "format": "jsonv2", "countrycodes": "us", "limit": 1},
    )
    if not results:
        raise GeocodingError(f"Could not find '{query}' in the USA")
    hit = results[0]
    lat, lng = float(hit["lat"]), float(hit["lon"])
    if not in_usa(lat, lng):
        raise GeocodingError(f"'{query}' is not reachable by road in the USA")
    label = hit.get("display_name", query)
    cache.set(cache_key, (label, lat, lng), timeout=60 * 60 * 24 * 30)
    return Location(query, label, lat, lng, "nominatim"), 1
