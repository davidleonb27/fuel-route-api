from django.db import models


class FuelStation(models.Model):
    class GeoSource(models.TextChoices):
        CENSUS_PLACE = "census_place", "US Census place centroid"
        NOMINATIM = "nominatim", "Nominatim (OpenStreetMap)"

    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.PositiveIntegerField(null=True, blank=True)
    price = models.DecimalField(
        max_digits=7, decimal_places=4, help_text="Median of all prices listed for this stop"
    )
    price_min = models.DecimalField(max_digits=7, decimal_places=4)
    price_max = models.DecimalField(max_digits=7, decimal_places=4)
    price_observations = models.PositiveSmallIntegerField(default=1)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    geo_source = models.CharField(max_length=32, choices=GeoSource.choices, blank=True)

    class Meta:
        ordering = ["state", "city", "name"]
        indexes = [models.Index(fields=["latitude", "longitude"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state}) ${self.price}"
