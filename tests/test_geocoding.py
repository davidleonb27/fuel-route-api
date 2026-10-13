import pytest

from fuel.services.geocoding import GeocodingError, geocode, lookup_place
from fuel.services.names import normalize_place_name, normalize_state, place_key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("St. Louis", "st louis"),
        ("Saint Louis", "st louis"),
        ("Kansas City", "kansas city"),
        ("Winston-Salem", "winston salem"),
        ("Coeur d'Alene", "coeur d alene"),
        ("Fort Worth", "ft worth"),
    ],
)
def test_normalize_place_name(raw, expected):
    assert normalize_place_name(raw) == expected


def test_census_suffix_only_stripped_when_asked():
    assert normalize_place_name("Kansas City city", strip_census_suffix=True) == "kansas city"
    assert normalize_place_name("Abanda CDP", strip_census_suffix=True) == "abanda"


@pytest.mark.parametrize(("raw", "code"), [("tx", "TX"), ("Texas", "TX"), ("N.Y.", None)])
def test_normalize_state(raw, code):
    assert normalize_state(raw) == code


@pytest.mark.parametrize(
    ("city", "state"),
    [("New York", "NY"), ("Nashville", "TN"), ("Louisville", "KY"), ("Ft. Worth", "Texas")],
)
def test_lookup_place_finds_major_cities(city, state):
    assert lookup_place(city, state) is not None


@pytest.mark.parametrize("query", ["Austin TX", "Salt Lake City, Utah", "Miami, FL, USA"])
def test_geocode_city_state_offline(query):
    location, calls = geocode(query)
    assert calls == 0
    assert location.source == "census_place"


def test_geocode_rejects_points_outside_usa():
    with pytest.raises(GeocodingError):
        geocode("48.85,2.35")


def test_place_key_ignores_spacing_variants():
    assert place_key("Mc Calla") == place_key("McCalla")
    assert place_key("De Forest") == place_key("DeForest")


@pytest.mark.parametrize(
    ("city", "state"),
    [
        ("Boise", "ID"),
        ("Lexington", "KY"),
        ("Macon", "GA"),
        ("Canon City", "CO"),
        ("Mc Calla", "AL"),
    ],
)
def test_lookup_place_handles_census_naming_quirks(city, state):
    assert lookup_place(city, state) is not None
