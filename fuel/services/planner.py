import hashlib
import time
from dataclasses import dataclass

import numpy as np
from django.conf import settings
from django.core.cache import cache
from scipy.spatial import cKDTree

from fuel.models import FuelStation

from .geocoding import Location, geocode
from .geometry import arc_for_chord, chord_for_arc, resample_route, simplify, to_xyz
from .optimizer import Candidate, plan_purchases
from .routing import Route, RoutingProvider, get_route
from .stations import station_index

MILES_PER_DEGREE_LAT = 69.0


@dataclass(frozen=True)
class PlanOptions:
    corridor_miles: float
    initial_fuel_gallons: float = 0.0


@dataclass(frozen=True)
class StationOnRoute:
    row: int
    mile: float
    off_route_miles: float


def stations_along_route(route: Route, corridor_miles: float) -> list[StationOnRoute]:
    index = station_index()
    if not len(index) or len(route.coordinates) < 2:
        return []

    lat, lng, miles = resample_route(
        route.coordinates, settings.FUEL["ROUTE_SAMPLE_MILES"], route.distance_miles
    )

    # Cheap bounding-box prefilter before the exact nearest-point query.
    pad_lat = corridor_miles / MILES_PER_DEGREE_LAT
    pad_lng = pad_lat / max(np.cos(np.radians(np.abs(lat).max())), 0.1)
    mask = (
        (index.lat >= lat.min() - pad_lat)
        & (index.lat <= lat.max() + pad_lat)
        & (index.lng >= lng.min() - pad_lng)
        & (index.lng <= lng.max() + pad_lng)
    )
    rows = np.flatnonzero(mask)
    if not rows.size:
        return []

    tree = cKDTree(to_xyz(lat, lng))
    chord, nearest = tree.query(index.xyz[rows], distance_upper_bound=chord_for_arc(corridor_miles))
    hit = np.isfinite(chord)
    return [
        StationOnRoute(int(row), float(miles[sample]), float(arc_for_chord(distance)))
        for row, sample, distance in zip(rows[hit], nearest[hit], chord[hit], strict=True)
    ]


def _cache_key(start: Location, finish: Location, options: PlanOptions) -> str:
    raw = (
        f"{start.lat:.5f},{start.lng:.5f}|{finish.lat:.5f},{finish.lng:.5f}|"
        f"{options.corridor_miles:.2f}|{options.initial_fuel_gallons:.2f}|"
        f"{settings.FUEL['VEHICLE_RANGE_MILES']}|{settings.FUEL['VEHICLE_MPG']}"
    )
    return "plan:v1:" + hashlib.sha256(raw.encode()).hexdigest()


def build_plan(
    start_query: str,
    finish_query: str,
    options: PlanOptions,
    provider: RoutingProvider | None = None,
) -> dict:
    started = time.perf_counter()
    start, start_calls = geocode(start_query)
    finish, finish_calls = geocode(finish_query)

    key = _cache_key(start, finish, options)
    if cached := cache.get(key):
        cached["meta"] = {
            **cached["meta"],
            "cached": True,
            "geocoding_api_calls": start_calls + finish_calls,
            "routing_api_calls": 0,
            "compute_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        return cached

    route, routing_calls = get_route((start.lat, start.lng), (finish.lat, finish.lng), provider)
    plan = _optimise(start, finish, route, options)
    plan["meta"] = {
        "cached": False,
        "geocoding_api_calls": start_calls + finish_calls,
        "routing_api_calls": routing_calls,
        "compute_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    cache.set(key, plan, timeout=settings.FUEL["PLAN_CACHE_SECONDS"])
    return plan


def _optimise(start: Location, finish: Location, route: Route, options: PlanOptions) -> dict:
    cfg = settings.FUEL
    mpg = cfg["VEHICLE_MPG"]
    range_miles = cfg["VEHICLE_RANGE_MILES"]
    index = station_index()
    on_route = stations_along_route(route, options.corridor_miles)

    start_fuel_miles = min(options.initial_fuel_gallons * mpg, range_miles)
    origin_radius = cfg["ORIGIN_RADIUS_MILES"]
    candidates = []
    for station in on_route:
        mile = station.mile
        # Starting empty, the truck fuels near the origin; the few miles to that pump
        # are billed at its price instead of making the route infeasible.
        if start_fuel_miles == 0 and mile <= origin_radius:
            mile = 0.0
        candidates.append(Candidate(mile, float(index.price[station.row]), station))

    purchases = plan_purchases(candidates, route.distance_miles, range_miles, start_fuel_miles)

    station_ids = [int(index.ids[p.candidate.ref.row]) for p in purchases]
    stations = FuelStation.objects.in_bulk(station_ids)
    stops, total_cost, total_gallons = [], 0.0, 0.0
    for sequence, (purchase, station_id) in enumerate(zip(purchases, station_ids, strict=True), 1):
        station = stations[station_id]
        gallons = purchase.miles_of_fuel / mpg
        price = float(station.price)
        cost = gallons * price
        total_cost += cost
        total_gallons += gallons
        stops.append(
            {
                "sequence": sequence,
                "station": {
                    "id": station.opis_id,
                    "name": station.name,
                    "address": station.address,
                    "city": station.city,
                    "state": station.state,
                    "lat": round(station.latitude, 6),
                    "lng": round(station.longitude, 6),
                    "price_per_gallon": round(price, 3),
                },
                "route_mile": round(purchase.candidate.ref.mile, 1),
                "off_route_miles": round(purchase.candidate.ref.off_route_miles, 1),
                "fuel_on_arrival_gallons": round(purchase.fuel_on_arrival_miles / mpg, 2),
                "gallons": round(gallons, 2),
                "cost": round(cost, 2),
            }
        )

    trip_gallons = route.distance_miles / mpg
    geometry = simplify(route.coordinates, tolerance_degrees=0.0005)
    return {
        "start": start.as_dict(),
        "finish": finish.as_dict(),
        "vehicle": {
            "range_miles": range_miles,
            "mpg": mpg,
            "tank_gallons": range_miles / mpg,
            "initial_fuel_gallons": round(start_fuel_miles / mpg, 2),
        },
        "route": {
            "distance_miles": round(route.distance_miles, 1),
            "duration_hours": round(route.duration_seconds / 3600, 2),
            "stations_considered": len(on_route),
        },
        "fuel_stops": stops,
        "summary": {
            "number_of_stops": len(stops),
            "trip_fuel_gallons": round(trip_gallons, 2),
            "gallons_purchased": round(total_gallons, 2),
            "total_fuel_cost": round(total_cost, 2),
            "average_price_per_gallon": round(total_cost / total_gallons, 3)
            if total_gallons
            else None,
        },
        "geojson": _geojson(start, finish, geometry, stops),
    }


def _geojson(start: Location, finish: Location, geometry, stops) -> dict:
    def point(lng, lat, **properties):
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": properties,
        }

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": geometry},
            "properties": {"kind": "route"},
        },
        point(start.lng, start.lat, kind="start", label=start.label),
        point(finish.lng, finish.lat, kind="finish", label=finish.label),
    ]
    for stop in stops:
        station = stop["station"]
        features.append(
            point(
                station["lng"],
                station["lat"],
                kind="fuel_stop",
                sequence=stop["sequence"],
                name=station["name"],
                price_per_gallon=station["price_per_gallon"],
                gallons=stop["gallons"],
                cost=stop["cost"],
            )
        )
    return {"type": "FeatureCollection", "features": features}
