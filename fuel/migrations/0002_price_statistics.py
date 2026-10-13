from decimal import Decimal

from django.db import migrations, models
from django.db.models import F


def copy_price(apps, schema_editor):
    FuelStation = apps.get_model("fuel", "FuelStation")
    FuelStation.objects.update(price_min=F("price"), price_max=F("price"))


class Migration(migrations.Migration):
    dependencies = [("fuel", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="fuelstation",
            name="price",
            field=models.DecimalField(
                decimal_places=4,
                help_text="Median of all prices listed for this stop",
                max_digits=7,
            ),
        ),
        migrations.AddField(
            model_name="fuelstation",
            name="price_min",
            field=models.DecimalField(decimal_places=4, default=Decimal("0"), max_digits=7),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="fuelstation",
            name="price_max",
            field=models.DecimalField(decimal_places=4, default=Decimal("0"), max_digits=7),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="fuelstation",
            name="price_observations",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.RunPython(copy_price, migrations.RunPython.noop),
    ]
