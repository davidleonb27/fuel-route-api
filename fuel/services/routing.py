from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.core.cache import cache

from .http import UpstreamServiceError, get_json

METERS_PER_MILE = 1609.344


class RoutingError(Exception):
    pass


@dataclass(frozen=True)
class Route:
    distance_miles: float
    duration_seconds: float
    coordinates: list[tuple[float, float]]  # (lng, lat), GeoJSON order


class RoutingProvider(Protocol):
    def route(self, start: tuple[float, float], finish: tuple[float, float]) -> Route: ...


class OSRMProvider:
    """Free OSRM routing; one HTTP call returns distance, duration and the full geometry."""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.FUEL["OSRM_BASE_URL"]).rstrip("/")

    def route(self, start, finish) -> Route:
        (lat1, lng1), (lat2, lng2) = start, finish
        url = f"{self.base_url}/route/v1/driving/{lng1:.6f},{lat1:.6f};{lng2:.6f},{lat2:.6f}"
        try:
            payload = get_json(
                url, params={"overview": "full", "geometries": "geojson", "steps": "false"}
            )
        except UpstreamServiceError as exc:
            raise RoutingError("Routing service is unavailable, please retry") from exc

        if payload.get("code") != "Ok" or not payload.get("routes"):
            raise RoutingError(payload.get("message") or "No drivable route between those points")
        best = payload["routes"][0]
        return Route(
            distance_miles=best["distance"] / METERS_PER_MILE,
            duration_seconds=best["duration"],
            coordinates=[tuple(point) for point in best["geometry"]["coordinates"]],
        )


def get_route(
    start: tuple[float, float], finish: tuple[float, float], provider: RoutingProvider | None = None
) -> tuple[Route, int]:
    """Cached routing; returns the route and how many external calls were made (0 or 1)."""
    key = "route:v1:{:.5f},{:.5f};{:.5f},{:.5f}".format(*start, *finish)
    if cached := cache.get(key):
        return cached, 0
    route = (provider or OSRMProvider()).route(start, finish)
    cache.set(key, route, timeout=settings.FUEL["PLAN_CACHE_SECONDS"])
    return route, 1
