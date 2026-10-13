import threading
from dataclasses import dataclass

import numpy as np
from django.db.models import Count, Max, Sum

from fuel.models import FuelStation

from .geometry import to_xyz


@dataclass(frozen=True)
class StationIndex:
    ids: np.ndarray
    lat: np.ndarray
    lng: np.ndarray
    price: np.ndarray
    xyz: np.ndarray

    def __len__(self) -> int:
        return len(self.ids)


_lock = threading.Lock()
_cached: tuple[tuple, StationIndex] | None = None


def _fingerprint() -> tuple:
    # One cheap aggregate query; changes whenever stations are reloaded or edited.
    stats = FuelStation.objects.filter(latitude__isnull=False).aggregate(
        n=Count("id"), m=Max("id"), p=Sum("price"), lat=Sum("latitude"), lng=Sum("longitude")
    )
    return tuple(stats.values())


def station_index() -> StationIndex:
    """Geocoded stations as numpy arrays, rebuilt only when the table changes."""
    global _cached
    fingerprint = _fingerprint()
    if _cached and _cached[0] == fingerprint:
        return _cached[1]
    with _lock:
        if _cached and _cached[0] == fingerprint:
            return _cached[1]
        rows = np.array(
            FuelStation.objects.filter(latitude__isnull=False)
            .order_by("id")
            .values_list("id", "latitude", "longitude", "price"),
            dtype=float,
        ).reshape(-1, 4)
        lat, lng = rows[:, 1], rows[:, 2]
        index = StationIndex(
            ids=rows[:, 0].astype(int),
            lat=lat,
            lng=lng,
            price=rows[:, 3],
            xyz=to_xyz(lat, lng),
        )
        _cached = (fingerprint, index)
        return index
