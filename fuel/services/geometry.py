import numpy as np

EARTH_RADIUS_MILES = 3958.7613


def to_xyz(lat, lng) -> np.ndarray:
    """Points on a sphere of Earth's radius, so Euclidean KD-trees work with miles."""
    lat_r, lng_r = np.radians(lat), np.radians(lng)
    cos_lat = np.cos(lat_r)
    return EARTH_RADIUS_MILES * np.column_stack(
        (cos_lat * np.cos(lng_r), cos_lat * np.sin(lng_r), np.sin(lat_r))
    )


def chord_for_arc(miles: float) -> float:
    return 2 * EARTH_RADIUS_MILES * np.sin(miles / (2 * EARTH_RADIUS_MILES))


def arc_for_chord(chord):
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.clip(chord / (2 * EARTH_RADIUS_MILES), 0, 1))


def haversine_miles(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def resample_route(coordinates, step_miles: float, total_miles: float | None = None):
    """Evenly spaced (lat, lng, mile) samples along a GeoJSON (lng, lat) polyline.

    OSRM leaves long straight interstate stretches with few vertices, so stations
    beside them would be missed without resampling.
    """
    points = np.asarray(coordinates, dtype=float)
    lng, lat = points[:, 0], points[:, 1]
    segment = haversine_miles(lat[:-1], lng[:-1], lat[1:], lng[1:])
    cumulative = np.concatenate(([0.0], np.cumsum(segment)))
    if total_miles and cumulative[-1] > 0:
        cumulative *= total_miles / cumulative[-1]
    length = cumulative[-1]
    marks = np.arange(0.0, length + step_miles, step_miles)
    marks[-1] = min(marks[-1], length)
    return np.interp(marks, cumulative, lat), np.interp(marks, cumulative, lng), marks


def simplify(coordinates, tolerance_degrees: float) -> list[list[float]]:
    """Ramer-Douglas-Peucker, vectorised one recursion level at a time."""
    points = np.asarray(coordinates, dtype=float)
    n = len(points)
    if n < 3:
        return points.round(5).tolist()

    keep = np.zeros(n, dtype=bool)
    keep[[0, -1]] = True
    candidates = np.arange(1, n - 1)  # interior points of segments not yet settled
    while candidates.size:
        bounds = np.flatnonzero(keep)
        segment = np.searchsorted(bounds, candidates, side="right") - 1
        first, last = bounds[segment], bounds[segment + 1]
        start = points[first]
        direction = points[last] - start
        offset = points[candidates] - start
        norm = np.hypot(direction[:, 0], direction[:, 1])
        cross = np.abs(direction[:, 0] * offset[:, 1] - direction[:, 1] * offset[:, 0])
        distance = np.where(
            norm > 0, cross / np.where(norm > 0, norm, 1), np.hypot(offset[:, 0], offset[:, 1])
        )

        # Per-segment maximum: candidates are sorted, so segments are contiguous runs.
        run_starts = np.flatnonzero(np.r_[True, segment[1:] != segment[:-1]])
        run_max = np.maximum.reduceat(distance, run_starts)
        run_of = np.repeat(np.arange(run_starts.size), np.diff(np.r_[run_starts, segment.size]))
        splitting = run_max > tolerance_degrees
        is_max = (distance == run_max[run_of]) & splitting[run_of]
        _, first_hit = np.unique(run_of[is_max], return_index=True)
        keep[candidates[np.flatnonzero(is_max)[first_hit]]] = True

        still_open = splitting[run_of] & ~keep[candidates]
        candidates = candidates[still_open]
    return points[keep].round(5).tolist()
