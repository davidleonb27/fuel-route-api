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


def simplify(coordinates, tolerance_degrees: float):
    """Iterative Ramer-Douglas-Peucker to shrink the polyline sent to clients."""
    points = np.asarray(coordinates, dtype=float)
    if len(points) < 3:
        return points.tolist()
    keep = np.zeros(len(points), dtype=bool)
    keep[[0, -1]] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        start, end = points[first], points[last]
        inner = points[first + 1 : last]
        direction = end - start
        norm = np.hypot(*direction)
        if norm == 0:
            distances = np.hypot(*(inner - start).T)
        else:
            offset = inner - start
            distances = np.abs(direction[0] * offset[:, 1] - direction[1] * offset[:, 0]) / norm
        index = int(np.argmax(distances))
        if distances[index] > tolerance_degrees:
            split = first + 1 + index
            keep[split] = True
            stack.extend(((first, split), (split, last)))
    return points[keep].round(5).tolist()
