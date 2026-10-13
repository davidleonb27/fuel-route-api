import numpy as np
import pytest

from fuel.services.geometry import haversine_miles, resample_route, simplify


def _max_deviation(original, simplified):
    original, simplified = np.asarray(original), np.asarray(simplified)
    worst = 0.0
    for a, b in zip(simplified[:-1], simplified[1:], strict=True):
        lo, hi = sorted((a[0], b[0]))
        inside = original[(original[:, 0] >= lo - 1e-12) & (original[:, 0] <= hi + 1e-12)]
        d = b - a
        norm = np.hypot(*d) or 1.0
        dev = np.abs(d[0] * (inside[:, 1] - a[1]) - d[1] * (inside[:, 0] - a[0])) / norm
        worst = max(worst, float(dev.max(initial=0.0)))
    return worst


@pytest.mark.parametrize("seed", range(10))
def test_simplify_keeps_endpoints_and_stays_within_tolerance(seed):
    rng = np.random.default_rng(seed)
    x = np.linspace(-100, -90, 3000)
    y = 40 + np.cumsum(rng.normal(0, 0.002, x.size))
    line = np.column_stack((x, y))
    tolerance = 0.005

    result = simplify(line, tolerance)

    assert result[0] == pytest.approx(line[0].round(5).tolist())
    assert result[-1] == pytest.approx(line[-1].round(5).tolist())
    assert len(result) < len(line) / 3
    assert _max_deviation(line, result) <= tolerance + 1e-5


def test_simplify_collapses_a_straight_line():
    line = [[-100 + i * 0.01, 40.0] for i in range(500)]
    assert len(simplify(line, 0.001)) == 2


def test_resample_route_is_evenly_spaced_and_scaled_to_router_distance():
    coords = [(-100.0, 40.0), (-99.0, 40.0)]
    lat, lng, miles = resample_route(coords, step_miles=0.5, total_miles=60.0)
    assert miles[0] == 0 and miles[-1] == pytest.approx(60.0)
    assert np.allclose(np.diff(miles)[:-1], 0.5)
    assert haversine_miles(40.0, -100.0, 40.0, -99.0) == pytest.approx(52.9, abs=0.2)
