import itertools
import random

import pytest

from fuel.services.optimizer import (
    Candidate,
    InfeasibleRouteError,
    plan_purchases,
    plan_purchases_with_stop_cost,
)


def cost(purchases):
    return sum(p.miles_of_fuel * p.candidate.price for p in purchases)


def brute_force_cost(candidates, route_miles, range_miles, step):
    """Exact DP over discretised fuel levels, used as an oracle for the greedy."""
    stations = sorted(candidates, key=lambda c: c.mile)
    levels = int(range_miles // step)
    inf = float("inf")
    # best[k] = min cost to be at the current station holding k*step miles of fuel
    best = [inf] * (levels + 1)
    best[0] = 0.0
    position = stations[0].mile
    for idx, station in enumerate(stations):
        if idx:
            drive = round((station.mile - position) / step)
            moved = [inf] * (levels + 1)
            for k, value in enumerate(best):
                if value < inf and k >= drive:
                    moved[k - drive] = min(moved[k - drive], value)
            best = moved
            position = station.mile
        for k in range(1, levels + 1):
            best[k] = min(best[k], best[k - 1] + step * station.price)
    remaining = round((route_miles - position) / step)
    return min((v for k, v in enumerate(best) if k >= remaining), default=inf)


def test_single_tank_trip_buys_exact_distance_at_origin():
    plan = plan_purchases([Candidate(0, 3.0, "A")], route_miles=120, range_miles=500)
    assert [(p.candidate.ref, p.miles_of_fuel) for p in plan] == [("A", 120)]


def test_buys_only_enough_to_reach_cheaper_station():
    stations = [Candidate(0, 4.0, "A"), Candidate(100, 3.0, "B")]
    plan = plan_purchases(stations, route_miles=400, range_miles=500)
    assert [(p.candidate.ref, p.miles_of_fuel) for p in plan] == [("A", 100), ("B", 300)]


def test_fills_up_when_cheapest_and_more_than_one_tank_needed():
    stations = [Candidate(0, 3.0, "A"), Candidate(450, 5.0, "B")]
    plan = plan_purchases(stations, route_miles=700, range_miles=500)
    assert [(p.candidate.ref, p.miles_of_fuel) for p in plan] == [("A", 500), ("B", 200)]
    assert plan[1].fuel_on_arrival_miles == pytest.approx(50)


def test_raises_when_gap_exceeds_range():
    with pytest.raises(InfeasibleRouteError):
        plan_purchases([Candidate(0, 3.0, "A"), Candidate(600, 3.0, "B")], 900, 500)


def test_raises_when_no_station_at_start():
    with pytest.raises(InfeasibleRouteError):
        plan_purchases([Candidate(30, 3.0, "A")], 300, 500)


def test_start_fuel_lets_vehicle_skip_expensive_first_station():
    stations = [Candidate(10, 9.0, "pricey"), Candidate(200, 3.0, "cheap")]
    plan = plan_purchases(stations, route_miles=600, range_miles=500, start_fuel_miles=250)
    assert [p.candidate.ref for p in plan] == ["cheap"]


def test_zero_length_route_needs_no_fuel():
    assert plan_purchases([Candidate(0, 3.0, "A")], 0, 500) == []


@pytest.mark.parametrize("seed", range(60))
def test_greedy_matches_exact_dp(seed):
    rng = random.Random(seed)
    step = 10
    range_miles = 200
    route_miles = rng.choice(range(250, 900, step))
    miles = sorted(
        {0, *rng.sample(range(step, route_miles, step), k=min(25, route_miles // step - 1))}
    )
    candidates = [Candidate(m, round(rng.uniform(2.5, 5.5), 3), m) for m in miles]
    if any(b - a > range_miles for a, b in itertools.pairwise(miles + [route_miles])):
        with pytest.raises(InfeasibleRouteError):
            plan_purchases(candidates, route_miles, range_miles)
        return

    plan = plan_purchases(candidates, route_miles, range_miles)
    assert sum(p.miles_of_fuel for p in plan) == pytest.approx(route_miles)
    assert cost(plan) == pytest.approx(brute_force_cost(candidates, route_miles, range_miles, step))


def random_route(seed, range_miles=200):
    rng = random.Random(seed)
    route_miles = rng.choice(range(250, 1500, 10))
    miles = sorted({0, *rng.sample(range(5, route_miles), k=min(60, route_miles // 10))})
    candidates = [Candidate(m, round(rng.uniform(2.5, 5.5), 3), m) for m in miles]
    feasible = all(b - a <= range_miles for a, b in itertools.pairwise(miles + [route_miles]))
    return candidates, route_miles, feasible


@pytest.mark.parametrize("seed", range(40))
def test_stop_cost_dp_with_zero_cost_matches_greedy(seed):
    candidates, route_miles, feasible = random_route(seed)
    if not feasible:
        with pytest.raises(InfeasibleRouteError):
            plan_purchases_with_stop_cost(candidates, route_miles, 200, mpg=10, stop_cost=0)
        return
    greedy = plan_purchases(candidates, route_miles, 200)
    dp = plan_purchases_with_stop_cost(candidates, route_miles, 200, mpg=10, stop_cost=0)
    assert cost(dp) == pytest.approx(cost(greedy))
    assert sum(p.miles_of_fuel for p in dp) == pytest.approx(route_miles)


@pytest.mark.parametrize("seed", range(40))
def test_stop_cost_trades_a_little_fuel_for_fewer_stops(seed):
    candidates, route_miles, feasible = random_route(seed)
    if not feasible:
        return
    stop_cost = 15.0
    greedy = plan_purchases(candidates, route_miles, 200)
    dp = plan_purchases_with_stop_cost(candidates, route_miles, 200, mpg=10, stop_cost=stop_cost)

    def objective(plan):
        return cost(plan) / 10 + stop_cost * len(plan)

    assert len(dp) <= len(greedy)
    assert objective(dp) <= objective(greedy) + 1e-6
    assert all(p.miles_of_fuel <= 200 for p in dp)
    assert sum(p.miles_of_fuel for p in dp) == pytest.approx(route_miles)


def test_stop_cost_reports_fuel_on_arrival():
    stations = [Candidate(0, 3.0, "A"), Candidate(450, 5.0, "B")]
    plan = plan_purchases_with_stop_cost(stations, 700, 500, mpg=10, stop_cost=5)
    assert [(p.candidate.ref, p.miles_of_fuel, p.fuel_on_arrival_miles) for p in plan] == [
        ("A", 500, 0),
        ("B", 200, 50),
    ]
