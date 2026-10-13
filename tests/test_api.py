import re
from decimal import Decimal

import numpy as np
import pytest
import responses
from django.urls import reverse
from rest_framework.test import APIClient

from fuel.models import FuelStation
from fuel.services.routing import METERS_PER_MILE

pytestmark = pytest.mark.django_db

OSRM_URL = re.compile(r"https://router\.project-osrm\.org/route/v1/driving/.*")
NOMINATIM_URL = re.compile(r"https://nominatim\.openstreetmap\.org/search.*")

# A straight east-west road along latitude 40; one degree of longitude ~ 52.9 miles.
ROUTE_LAT = 40.0
ROUTE_LNG = np.linspace(-100.0, -84.0, 400)


def osrm_payload():
    coordinates = [[float(lng), ROUTE_LAT] for lng in ROUTE_LNG]
    miles = 52.9 * (ROUTE_LNG[-1] - ROUTE_LNG[0])
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": miles * METERS_PER_MILE,
                "duration": miles / 60 * 3600,
                "geometry": {"type": "LineString", "coordinates": coordinates},
            }
        ],
    }


def make_station(opis_id, lng, price, lat=ROUTE_LAT, **extra):
    return FuelStation.objects.create(
        opis_id=opis_id,
        name=f"Stop {opis_id}",
        address="I-70, EXIT 1",
        city="Town",
        state="KS",
        price=Decimal(str(price)),
        latitude=lat,
        longitude=lng,
        geo_source=FuelStation.GeoSource.CENSUS_PLACE,
        **extra,
    )


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def corridor_stations():
    make_station(1, -99.95, 3.90)  # near the start
    make_station(2, -97.0, 3.10)  # cheap, ~160 mi in
    make_station(3, -94.0, 4.20)  # expensive, ~315 mi
    make_station(4, -91.5, 3.00)  # cheapest, ~450 mi
    make_station(5, -88.0, 3.60)  # ~640 mi
    make_station(6, -95.0, 1.00, lat=43.0)  # very cheap but 200 mi off the route
    return FuelStation.objects.all()


@responses.activate
def test_plans_cheapest_stops_with_a_single_routing_call(client, corridor_stations):
    responses.get(OSRM_URL, json=osrm_payload())

    response = client.get(reverse("route-plan"), {"start": "40.0,-100.0", "finish": "40.0,-84.0"})

    assert response.status_code == 200, response.content
    body = response.json()
    assert len(responses.calls) == 1
    assert body["meta"] == {**body["meta"], "routing_api_calls": 1, "geocoding_api_calls": 0}

    stop_ids = [stop["station"]["id"] for stop in body["fuel_stops"]]
    assert stop_ids == [1, 2, 4]  # skips the $4.20 stop and the off-route $1.00 one
    assert 6 not in stop_ids

    total_miles = body["route"]["distance_miles"]
    assert body["summary"]["gallons_purchased"] == pytest.approx(total_miles / 10, abs=0.05)
    assert body["summary"]["total_fuel_cost"] == pytest.approx(
        sum(stop["cost"] for stop in body["fuel_stops"]), abs=0.05
    )
    for stop in body["fuel_stops"]:
        assert stop["gallons"] <= 50

    kinds = [feature["properties"]["kind"] for feature in body["geojson"]["features"]]
    assert kinds[:3] == ["route", "start", "finish"]
    assert kinds.count("fuel_stop") == 3
    assert body["map_url"].startswith("http://testserver/api/v1/route-plan/map/?")


@responses.activate
def test_post_with_city_names_uses_offline_geocoding_and_caches(client, corridor_stations):
    responses.get(OSRM_URL, json=osrm_payload())
    payload = {"start": "Denver, CO", "finish": "Saint Louis, Missouri"}

    first = client.post(reverse("route-plan"), payload, format="json")
    second = client.post(reverse("route-plan"), payload, format="json")

    assert first.status_code == 200, first.content
    assert first.json()["start"]["source"] == "census_place"
    assert first.json()["finish"]["label"] == "Saint Louis, MO"
    assert second.json()["meta"]["cached"] is True
    assert len(responses.calls) == 1  # no geocoding calls, one routing call in total


@responses.activate
def test_free_text_address_falls_back_to_nominatim(client, corridor_stations):
    responses.get(NOMINATIM_URL, json=[{"lat": "40.0", "lon": "-100.0", "display_name": "X"}])
    responses.get(OSRM_URL, json=osrm_payload())

    response = client.get(
        reverse("route-plan"), {"start": "1 Main Street somewhere", "finish": "40,-84"}
    )

    assert response.status_code == 200, response.content
    assert response.json()["meta"]["geocoding_api_calls"] == 1


@responses.activate
def test_gap_longer_than_range_is_reported_as_422(client):
    make_station(1, -99.95, 3.5)
    make_station(2, -86.0, 3.5)  # ~740 mi later
    responses.get(OSRM_URL, json=osrm_payload())

    response = client.get(reverse("route-plan"), {"start": "40,-100", "finish": "40,-84"})

    assert response.status_code == 422
    assert "Gap of more than 500 miles" in response.json()["detail"]


@responses.activate
def test_initial_fuel_avoids_needing_a_station_at_the_origin(client):
    make_station(2, -97.0, 3.10)
    make_station(4, -91.5, 3.00)
    make_station(5, -88.0, 3.60)
    responses.get(OSRM_URL, json=osrm_payload())

    response = client.get(
        reverse("route-plan"),
        {"start": "40,-100", "finish": "40,-84", "initial_fuel_gallons": 20},
    )

    assert response.status_code == 200, response.content
    assert response.json()["fuel_stops"][0]["station"]["id"] == 2


@responses.activate
def test_routing_outage_returns_502(client, corridor_stations):
    responses.get(OSRM_URL, status=503)
    response = client.get(reverse("route-plan"), {"start": "40,-100", "finish": "40,-84"})
    assert response.status_code == 502


@pytest.mark.parametrize(
    "params",
    [
        {"start": "40,-100"},
        {"start": "51.5,-0.12", "finish": "40,-84"},  # London
        {"start": "40,-100", "finish": "40,-84", "corridor_miles": 500},
        {"start": "40,-100", "finish": "40,-84", "initial_fuel_gallons": 80},
    ],
)
def test_invalid_input_returns_400(client, params):
    assert client.get(reverse("route-plan"), params).status_code == 400


@responses.activate
def test_map_page_renders_without_extra_routing_calls(client, corridor_stations):
    responses.get(OSRM_URL, json=osrm_payload())
    params = {"start": "40,-100", "finish": "40,-84"}

    client.get(reverse("route-plan"), params)
    page = client.get(reverse("route-map"), params)

    assert page.status_code == 200
    assert b"leaflet" in page.content
    assert b"Stop 4" in page.content
    assert len(responses.calls) == 1
