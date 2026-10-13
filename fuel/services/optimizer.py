from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

_EPS = 1e-9


@dataclass(frozen=True)
class Candidate[T]:
    mile: float
    price: float
    ref: T


@dataclass(frozen=True)
class Purchase[T]:
    candidate: Candidate[T]
    miles_of_fuel: float
    fuel_on_arrival_miles: float


class InfeasibleRouteError(Exception):
    pass


def plan_purchases[T](
    candidates: Sequence[Candidate[T]],
    route_miles: float,
    range_miles: float,
    start_fuel_miles: float = 0.0,
) -> list[Purchase[T]]:
    # Fuel is measured in miles. Classic optimal greedy: if a cheaper station is in
    # range, buy just enough to reach it; otherwise fill up and go to the cheapest one in range.
    if route_miles <= 0:
        return []
    if not 0 <= start_fuel_miles <= range_miles:
        raise ValueError("start_fuel_miles must be between 0 and range_miles")

    stations = sorted(
        (c for c in candidates if 0 <= c.mile < route_miles), key=lambda c: (c.mile, c.price)
    )
    if start_fuel_miles + _EPS >= route_miles:
        return []
    if not stations or stations[0].mile > start_fuel_miles + _EPS:
        raise InfeasibleRouteError("No fuel station reachable from the start of the route")

    purchases: list[Purchase[T]] = []
    fuel = start_fuel_miles - stations[0].mile
    i = 0
    n = len(stations)

    while True:
        here = stations[i]
        reach = here.mile + range_miles

        cheaper = None
        best_ahead = None
        j = i + 1
        while j < n and stations[j].mile <= reach + _EPS:
            if stations[j].price < here.price - _EPS:
                cheaper = j
                break
            if best_ahead is None or stations[j].price < stations[best_ahead].price - _EPS:
                best_ahead = j
            j += 1

        if cheaper is not None:
            target_mile, next_i = stations[cheaper].mile, cheaper
        elif route_miles <= reach + _EPS:
            target_mile, next_i = route_miles, None
        elif best_ahead is not None:
            target_mile, next_i = here.mile + range_miles, best_ahead
        else:
            raise InfeasibleRouteError(
                f"Gap of more than {range_miles:.0f} miles without a fuel station after mile "
                f"{here.mile:.1f}"
            )

        needed = target_mile - here.mile
        buy = max(0.0, needed - fuel)
        if buy > _EPS:
            purchases.append(Purchase(here, buy, max(fuel, 0.0)))
            fuel += buy

        if next_i is None:
            return purchases

        fuel -= stations[next_i].mile - here.mile
        i = next_i


def plan_purchases_with_stop_cost[T](
    candidates: Sequence[Candidate[T]],
    route_miles: float,
    range_miles: float,
    mpg: float,
    stop_cost: float,
    start_fuel_miles: float = 0.0,
    resolution_miles: float = 1.0,
) -> list[Purchase[T]]:
    # Exact DP over fuel level (in resolution_miles units) minimising fuel spend plus
    # stop_cost per stop; the greedy alone happily makes 1-gallon top-ups.
    if route_miles <= 0:
        return []
    if not 0 <= start_fuel_miles <= range_miles:
        raise ValueError("start_fuel_miles must be between 0 and range_miles")
    if start_fuel_miles + _EPS >= route_miles:
        return []

    stations = sorted(
        (c for c in candidates if 0 <= c.mile < route_miles), key=lambda c: (c.mile, c.price)
    )
    levels = int(range_miles // resolution_miles)
    start_level = int(start_fuel_miles // resolution_miles)
    finish = round(route_miles / resolution_miles)
    positions = [round(c.mile / resolution_miles) for c in stations]
    if not stations or positions[0] > start_level:
        raise InfeasibleRouteError("No fuel station reachable from the start of the route")

    inf = np.inf
    k = np.arange(levels + 1)
    cost = np.full(levels + 1, inf)
    cost[start_level - positions[0]] = 0.0
    choices: list[np.ndarray] = []  # level before buying, indexed by level after buying
    after = cost

    for i, station in enumerate(stations):
        if i:
            drive = positions[i] - positions[i - 1]
            cost = np.full(levels + 1, inf)
            if drive <= levels:
                cost[: levels + 1 - drive] = after[drive:]
        unit_price = station.price * resolution_miles / mpg
        # after[k] = min(cost[k], stop_cost + min_{j<k}(cost[j] + (k - j) * unit_price))
        g = cost - k * unit_price
        running_min = np.minimum.accumulate(g)
        argmin = np.maximum.accumulate(np.where(g <= running_min, k, 0))
        bought = np.full(levels + 1, inf)
        bought[1:] = running_min[:-1] + k[1:] * unit_price + stop_cost
        after = np.minimum(cost, bought)
        source = k.copy()
        use_buy = bought < cost
        source[1:][use_buy[1:]] = argmin[:-1][use_buy[1:]]
        choices.append(source)
        if not np.isfinite(after).any():
            raise InfeasibleRouteError(
                f"Gap of more than {range_miles:.0f} miles without a fuel station after mile "
                f"{stations[i - 1].mile if i else 0:.1f}"
            )

    remaining = finish - positions[-1]
    if remaining > levels or not np.isfinite(after[remaining:]).any():
        raise InfeasibleRouteError(
            f"Gap of more than {range_miles:.0f} miles without a fuel station after mile "
            f"{stations[-1].mile:.1f}"
        )
    level = remaining + int(np.argmin(after[remaining:]))

    purchases: list[Purchase[T]] = []
    for i in range(len(stations) - 1, -1, -1):
        before = int(choices[i][level])
        if before != level:
            purchases.append(
                Purchase(
                    stations[i],
                    (level - before) * resolution_miles,
                    before * resolution_miles,
                )
            )
        if i:
            level = before + positions[i] - positions[i - 1]
    purchases.reverse()
    return purchases
