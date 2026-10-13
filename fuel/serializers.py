from django.conf import settings
from rest_framework import serializers


class RoutePlanRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=200, help_text='"City, ST", a full US address, or "lat,lng".'
    )
    finish = serializers.CharField(max_length=200)
    corridor_miles = serializers.FloatField(
        required=False,
        min_value=1,
        max_value=50,
        help_text="How far off the route a station may be. Default 10.",
    )
    initial_fuel_gallons = serializers.FloatField(
        required=False,
        min_value=0,
        default=0,
        help_text="Fuel already in the tank at departure. Default 0 (start empty).",
    )

    def validate_initial_fuel_gallons(self, value):
        tank = settings.FUEL["VEHICLE_RANGE_MILES"] / settings.FUEL["VEHICLE_MPG"]
        if value > tank:
            raise serializers.ValidationError(f"Cannot exceed tank size of {tank:g} gallons.")
        return value

    def validate(self, attrs):
        attrs.setdefault("corridor_miles", settings.FUEL["CORRIDOR_MILES"])
        return attrs


class LocationSerializer(serializers.Serializer):
    query = serializers.CharField()
    label = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    source = serializers.ChoiceField(choices=["coordinates", "census_place", "nominatim"])


class StationSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="OPIS truck stop id")
    name = serializers.CharField()
    address = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    price_per_gallon = serializers.FloatField()


class FuelStopSerializer(serializers.Serializer):
    sequence = serializers.IntegerField()
    station = StationSerializer()
    route_mile = serializers.FloatField()
    off_route_miles = serializers.FloatField()
    fuel_on_arrival_gallons = serializers.FloatField()
    gallons = serializers.FloatField()
    cost = serializers.FloatField()


class RoutePlanResponseSerializer(serializers.Serializer):
    start = LocationSerializer()
    finish = LocationSerializer()
    vehicle = serializers.DictField()
    route = serializers.DictField()
    fuel_stops = FuelStopSerializer(many=True)
    summary = serializers.DictField()
    geojson = serializers.DictField(help_text="GeoJSON FeatureCollection: route, endpoints, stops")
    map_url = serializers.URLField(help_text="Interactive map of this plan")
    meta = serializers.DictField()
