import csv
import gzip
import re

import pytest
import responses
from django.core.management import call_command
from django.core.management.base import CommandError

import fuel.management.commands.load_fuel_stations as loader
from fuel.models import FuelStation

GAZ_HEADER = (
    "USPS|GEOID|GEOIDFQ|ANSICODE|NAME|LSAD|FUNCSTAT|ALAND|AWATER|ALAND_SQMI|AWATER_SQMI|"
    "INTPTLAT|INTPTLONG\n"
)


def gaz_row(state, name, funcstat, sqmi, lat, lng):
    return f"{state}|1|1|1|{name}|25|{funcstat}|0|0|{sqmi}|0|{lat}|{lng}\n"


def test_build_place_index_ranks_and_aliases(tmp_path):
    places = tmp_path / "places.txt"
    places.write_text(
        GAZ_HEADER
        + gaz_row("MO", "Kansas City city", "A", 315, 39.12, -94.55)
        + gaz_row("KY", "Lexington-Fayette urban county", "A", 283, 38.04, -84.46)
        + gaz_row("ID", "Boise City city", "A", 84, 43.6, -116.23)
        + gaz_row("TX", "Springfield CDP", "S", 2, 30.0, -97.0)
        + gaz_row("TX", "Springfield city", "A", 10, 31.0, -98.0)
        + gaz_row("ON", "Toronto city", "A", 1, 43.0, -79.0),
        encoding="utf-8",
    )
    output = tmp_path / "out.csv.gz"

    call_command("build_place_index", places=places, output=output)

    with gzip.open(output, "rt", encoding="utf-8") as handle:
        index = {(r["state"], r["name"]): (r["lat"], r["lng"]) for r in csv.DictReader(handle)}
    assert ("MO", "kansascity") in index
    assert ("KY", "lexington") in index
    assert ("ID", "boise") in index and ("ID", "boisecity") in index
    assert index[("TX", "springfield")] == ("31.000000", "-98.000000")  # incorporated wins
    assert not any(state == "ON" for state, _ in index)


@pytest.mark.django_db
@responses.activate
def test_loader_geocodes_unknown_cities_online_and_persists_them(tmp_path, settings, monkeypatch):
    prices = tmp_path / "prices.csv"
    prices.write_text(
        "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"
        "1,Remote Stop,I-80 EXIT 1,Nowhereville,NV,1,3.5\n",
        encoding="utf-8",
    )
    geocodes = tmp_path / "station_geocodes.csv"
    settings.FUEL = {**settings.FUEL, "STATION_GEOCODES_FILE": geocodes}
    monkeypatch.setattr(loader.time, "sleep", lambda _: None)
    responses.get(
        re.compile(r"https://nominatim\.openstreetmap\.org/search.*"),
        json=[{"lat": "40.5", "lon": "-117.5"}],
    )

    call_command("load_fuel_stations", file=prices, nominatim=True)

    station = FuelStation.objects.get()
    assert station.geo_source == FuelStation.GeoSource.NOMINATIM
    assert (station.latitude, station.longitude) == (40.5, -117.5)
    assert "NV,nowhereville,40.500000,-117.500000" in geocodes.read_text()

    # A second load is fully offline thanks to the saved file.
    responses.reset()
    call_command("load_fuel_stations", file=prices)
    assert FuelStation.objects.get().latitude == 40.5


def test_loader_reports_missing_file(tmp_path):
    with pytest.raises(CommandError):
        call_command("load_fuel_stations", file=tmp_path / "missing.csv")
