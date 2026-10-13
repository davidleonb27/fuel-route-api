from decimal import Decimal

import pytest
from django.core.management import call_command

from fuel.models import FuelStation
from fuel.services.ingest import IngestError, parse_price, read_fuel_csv, repair_text

HEADER = "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price\n"


def by_id(records):
    return {record.opis_id: record for record in records}


def test_duplicate_ids_use_median_price_and_most_common_name():
    csv_text = HEADER + (
        "20,PILOT TRAVEL CENTER #1243,I-8 EXIT 119,Gila Bend,AZ,930,3.899\n"
        "20,PILOT #1243,I-8 EXIT 119,Gila Bend,AZ,930,3.799\n"
        "20,PILOT #1243,I-8 EXIT 119,Gila Bend,AZ,930,4.299\n"
    )
    records, report = read_fuel_csv(csv_text)

    station = by_id(records)[20]
    assert station.price == Decimal("3.8990")
    assert (station.price_min, station.price_max) == (Decimal("3.7990"), Decimal("4.2990"))
    assert station.observations == 3
    assert station.name == "PILOT #1243"
    assert report.duplicate_ids == 1
    assert report.duplicate_ids_with_price_conflict == 1


def test_messy_values_are_cleaned():
    csv_text = HEADER + (
        "1,Stuckeyâ€™s Travel Center,  US-1  ,SOUTH BEND    ,in,1,$3.459\n"
        '2,Somewhere,Main St,Gila Bend,AZ,,"3,10"\n'
        "3,Long decimals,Main St,Gila Bend,AZ,7,3.00733333\n"
    )
    records, report = read_fuel_csv(csv_text)
    stations = by_id(records)

    assert stations[1].name == "Stuckey’s Travel Center"
    assert stations[1].address == "US-1"
    assert stations[1].city == "South Bend"
    assert stations[1].state == "IN"
    assert stations[1].price == Decimal("3.4590")
    assert stations[2].price == Decimal("3.1000")
    assert stations[2].rack_id is None
    assert stations[3].price == Decimal("3.0073")
    assert report.text_repaired == 1


def test_bad_rows_are_skipped_and_counted():
    csv_text = HEADER + (
        "abc,No id,Main,Austin,TX,1,3.0\n"
        "5,Bad price,Main,Austin,TX,1,n/a\n"
        "6,Too cheap,Main,Austin,TX,1,0.01\n"
        "7,Toronto stop,Main,Toronto,ON,1,4.1\n"
        "8,Nowhere,Main,Atlantis,ZZ,1,3.0\n"
        "9,No city,Main,,TX,1,3.0\n"
        ",,,,,,\n"
        "10,Good,Main,Austin,TX,1,3.0\n"
    )
    records, report = read_fuel_csv(csv_text)

    assert [r.opis_id for r in records] == [10]
    assert report.rows_read == 7
    assert report.skipped == {
        "invalid station id": 1,
        "unparseable price": 1,
        "implausible price": 1,
        "unknown state": 1,
        "missing city": 1,
    }
    assert report.non_us_rows == {"ON": 1}


def test_header_variants_and_semicolon_delimiter():
    csv_text = "price;STATE;city;Station Name;opis id\n3.5;tx;Austin;Stop;42\n"
    records, _ = read_fuel_csv(csv_text)
    assert by_id(records)[42].state == "TX"


def test_cp1252_encoded_bytes_are_decoded():
    data = (HEADER + "1,Café Stop,Main,Austin,TX,1,3.0\n").encode("cp1252")
    records, _ = read_fuel_csv(data)
    assert records[0].name == "Café Stop"


@pytest.mark.parametrize("text", ["", "a,b,c\n1,2,3\n"])
def test_unusable_files_raise(text):
    with pytest.raises(IngestError):
        read_fuel_csv(text)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("3.459", "3.459"), ("$3.459", "3.459"), (" 3,459 ", "3.459"), ("abc", None), ("NaN", None)],
)
def test_parse_price(raw, expected):
    result = parse_price(raw)
    assert result == (Decimal(expected) if expected else None)


def test_repair_text_leaves_clean_text_alone():
    assert repair_text("  Love's   Travel Stop ") == ("Love's Travel Stop", False)


@pytest.mark.django_db
def test_load_command_upserts_and_removes_stale_stations(tmp_path):
    first = tmp_path / "first.csv"
    first.write_text(
        HEADER + "1,A,Main,Austin,TX,1,3.0\n2,B,Main,Dallas,TX,1,3.2\n", encoding="utf-8"
    )
    call_command("load_fuel_stations", file=first)
    assert FuelStation.objects.count() == 2

    second = tmp_path / "second.csv"
    second.write_text(HEADER + "1,A,Main,Austin,TX,1,2.9\n", encoding="utf-8")
    call_command("load_fuel_stations", file=second)

    station = FuelStation.objects.get()
    assert station.opis_id == 1
    assert station.price == Decimal("2.9000")
    assert station.geo_source == FuelStation.GeoSource.CENSUS_PLACE


@pytest.mark.django_db
def test_load_command_dry_run_writes_nothing(tmp_path):
    path = tmp_path / "prices.csv"
    path.write_text(HEADER + "1,A,Main,Austin,TX,1,3.0\n", encoding="utf-8")
    call_command("load_fuel_stations", file=path, dry_run=True)
    assert not FuelStation.objects.exists()
