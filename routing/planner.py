"""Greedy fuel purchase planning along a route.

The tank starts empty and is measured in miles of range. At each stop:
  - if a station within range is cheaper, buy just enough to reach the first such station;
  - otherwise, if the destination is within range, buy just enough to finish;
  - otherwise fill the tank and drive to the cheapest station within range.
The first stop (the "origin fill") is the cheapest station within the origin window, or the first
station on the route when there is none. Fuel burned between the start and that station is paid
for at that station's price. Stations before the origin station are ignored.

Stations are compared by effective price: the real price grossed up by the fuel a round trip off the
route would burn (2 * offset / range). Money is always computed from the real price, so a plan's
cost and gallons are exactly what is bought.
"""
from dataclasses import dataclass, field

from stations.index import RouteStation

from .errors import NoFuelInRange


@dataclass
class FuelStop:
    station: RouteStation
    mile: float
    gallons: float
    price: float
    cost: float


@dataclass
class FuelPlan:
    stops: list = field(default_factory=list)
    total_cost: float = 0.0
    total_gallons: float = 0.0
    origin_fill_estimated: bool = False


def _greedy_plan(stations, total_miles, range_miles, mpg, origin_window_miles) -> FuelPlan:
    if total_miles <= 0:
        return FuelPlan()

    def eff(s):
        """Price used to compare stations: grossed up by the fuel burned on the round-trip detour."""
        return s.price * (1 + 2 * s.offset_miles / range_miles)

    stations = [s for s in stations if s.mile <= total_miles]
    if not stations:
        raise NoFuelInRange(f"No fuel stations found along the route (miles 0 to {total_miles:.0f}).")

    in_window = [s for s in stations if s.mile <= origin_window_miles]
    estimated = not in_window
    origin = min(in_window, key=lambda s: (eff(s), s.mile)) if in_window else stations[0]
    ahead = [s for s in stations if s.mile > origin.mile]

    # Each stop: [station, position, miles of fuel bought]. The origin fill also pays for the
    # miles driven from the start to the origin station.
    stops = [[origin, origin.mile, origin.mile]]
    position, price, fuel = origin.mile, eff(origin), 0.0
    while True:
        in_range = [s for s in ahead if position < s.mile <= position + range_miles]
        cheaper = next((s for s in in_range if eff(s) < price), None)
        remaining = total_miles - position
        if cheaper:
            nxt, buy = cheaper, max(0.0, cheaper.mile - position - fuel)
        elif remaining <= range_miles:
            stops[-1][2] += max(0.0, remaining - fuel)
            break
        elif in_range:
            nxt, buy = min(in_range, key=lambda s: (eff(s), s.mile)), range_miles - fuel
        else:
            raise NoFuelInRange(
                f"No fuel stations between mile {position:.0f} and mile {position + range_miles:.0f} "
                f"(the vehicle range is {range_miles:.0f} miles)."
            )
        stops[-1][2] += buy
        fuel = fuel + buy - (nxt.mile - position)
        position, price = nxt.mile, eff(nxt)
        stops.append([nxt, position, 0.0])
        ahead = [s for s in ahead if s is not nxt]

    plan = FuelPlan(origin_fill_estimated=estimated)
    for station, _, buy_miles in stops:
        if buy_miles <= 1e-9:
            continue
        gallons = buy_miles / mpg
        plan.stops.append(
            FuelStop(station=station, mile=station.mile, gallons=gallons, price=station.price, cost=gallons * station.price)
        )
    plan.total_gallons = sum(s.gallons for s in plan.stops)
    plan.total_cost = sum(s.cost for s in plan.stops)
    return plan


def optimize_fuel_stops(
    stations, total_miles, range_miles=500, mpg=10, origin_window_miles=50, stop_penalty=0.0
) -> FuelPlan:
    """Greedy plan, then drop stops that save less than stop_penalty dollars.

    Left alone, the greedy plan makes tiny top-ups at a slightly cheaper station to save cents.
    Each pass removes the stop whose removal increases the fuel bill by the least, as long as the
    increase is below stop_penalty, and re-plans over the remaining stops. The first stop is kept.
    """
    plan = _greedy_plan(stations, total_miles, range_miles, mpg, origin_window_miles)
    while stop_penalty > 0 and len(plan.stops) > 1:
        best = None
        for stop in plan.stops[1:]:
            kept = [s.station for s in plan.stops if s is not stop]
            try:
                candidate = _greedy_plan(kept, total_miles, range_miles, mpg, origin_window_miles)
            except NoFuelInRange:
                continue
            increase = candidate.total_cost - plan.total_cost
            if increase < stop_penalty and (best is None or increase < best[0]):
                best = (increase, candidate)
        if best is None:
            break
        plan = best[1]
    return plan
