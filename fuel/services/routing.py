from dataclasses import dataclass
from typing import Protocol

import requests
from django.conf import settings
from django.core.cache import cache

from .http import session

METERS_PER_MILE = 1609.344

# OSRM codes meaning "your input has no route", as opposed to the service failing.
_NO_ROUTE_CODES = {"NoRoute", "NoSegment", "InvalidValue", "InvalidInput"}


class RoutingError(Exception):
    pass


class NoRouteError(RoutingError):
    pass


@dataclass(frozen=True)
class Route:
    distance_miles: float
    duration_seconds: float
    coordinates: list[tuple[float, float]]  # (lng, lat), GeoJSON order


class RoutingProvider(Protocol):
    def route(self, start: tuple[float, float], finish: tuple[float, float]) -> Route: ...


def decode_polyline(encoded: str, precision: int = 6) -> list[tuple[float, float]]:
    """Google encoded polyline -> [(lng, lat)]. OSRM's polyline6 is ~5x smaller than GeoJSON."""
    factor = 10**precision
    coordinates, index, lat, lng = [], 0, 0, 0
    length = len(encoded)
    while index < length:
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lng += deltas[1]
        coordinates.append((lng / factor, lat / factor))
    return coordinates


class OSRMProvider:
    """Free OSRM routing; one HTTP call returns distance, duration and the full geometry."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.FUEL["OSRM_BASE_URL"]).rstrip("/")

    def route(self, start, finish) -> Route:
        (lat1, lng1), (lat2, lng2) = start, finish
        url = f"{self.base_url}/route/v1/driving/{lng1:.6f},{lat1:.6f};{lng2:.6f},{lat2:.6f}"
        params = {"overview": "full", "geometries": "polyline6", "steps": "false"}
        try:
            response = session().get(
                url, params=params, timeout=settings.FUEL["HTTP_TIMEOUT_SECONDS"]
            )
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RoutingError("Routing service is unavailable, please retry") from exc

        code = payload.get("code")
        if code in _NO_ROUTE_CODES:
            raise NoRouteError("There is no drivable route between those locations")
        if code != "Ok" or not payload.get("routes"):
            raise RoutingError("Routing service is unavailable, please retry")

        best = payload["routes"][0]
        return Route(
            distance_miles=best["distance"] / METERS_PER_MILE,
            duration_seconds=best["duration"],
            coordinates=decode_polyline(best["geometry"]),
        )


def route_cache_key(start: tuple[float, float], finish: tuple[float, float]) -> str:
    return "route:v2:{:.5f},{:.5f};{:.5f},{:.5f}".format(*start, *finish)


def get_route(
    start: tuple[float, float], finish: tuple[float, float], provider: RoutingProvider | None = None
) -> tuple[Route, int]:
    """Cached routing; returns the route and how many external calls were made (0 or 1)."""
    key = route_cache_key(start, finish)
    if cached := cache.get(key):
        return cached, 0
    route = (provider or OSRMProvider()).route(start, finish)
    cache.set(key, route, timeout=settings.FUEL["PLAN_CACHE_SECONDS"])
    return route, 1
