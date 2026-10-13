from collections.abc import Sequence
from dataclasses import dataclass

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
