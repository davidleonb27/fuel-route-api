import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from fuel.models import FuelStation

pytestmark = pytest.mark.django_db


def test_health_reports_unready_without_stations():
    response = APIClient().get(reverse("health"))
    assert response.status_code == 503
    assert response.json()["status"] == "no_stations_loaded"


def test_health_ok_with_stations():
    FuelStation.objects.create(
        opis_id=1,
        name="A",
        address="",
        city="Austin",
        state="TX",
        price=3,
        price_min=3,
        price_max=3,
        latitude=30.3,
        longitude=-97.7,
    )
    response = APIClient().get(reverse("health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "stations": 1}


def test_openapi_schema_renders():
    response = APIClient().get(reverse("schema"))
    assert response.status_code == 200
    assert b"/api/v1/route-plan/" in response.content
