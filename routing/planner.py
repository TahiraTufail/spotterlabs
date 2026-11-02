"""Greedy fuel purchase planning along a route.

The tank starts empty and is measured in miles of range. At each stop:
  - if a station within range is cheaper, buy just enough to reach the first such station;
  - otherwise, if the destination is within range, buy just enough to finish;
  - otherwise fill the tank and drive to the cheapest station within range.
The first stop (the "origin fill") is the cheapest station within the origin window, or the first
station on the route when there is none. Fuel burned between the start and that station is paid
for at that station's price. Stations before the origin station are ignored.
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


def optimize_fuel_stops(stations, total_miles, range_miles=500, mpg=10, origin_window_miles=50) -> FuelPlan:
    if total_miles <= 0:
        return FuelPlan()
    stations = [s for s in stations if s.mile <= total_miles]
    if not stations:
        raise NoFuelInRange(f"No fuel stations found along the route (miles 0 to {total_miles:.0f}).")

    in_window = [s for s in stations if s.mile <= origin_window_miles]
    estimated = not in_window
    origin = min(in_window, key=lambda s: (s.price, s.mile)) if in_window else stations[0]
    ahead = [s for s in stations if s.mile > origin.mile]

    # Each stop: [station, position, miles of fuel bought]. The origin fill also pays for the
    # miles driven from the start to the origin station.
    stops = [[origin, origin.mile, origin.mile]]
    position, price, fuel = origin.mile, origin.price, 0.0
    while True:
        in_range = [s for s in ahead if position < s.mile <= position + range_miles]
        cheaper = next((s for s in in_range if s.price < price), None)
        remaining = total_miles - position
        if cheaper:
            nxt, buy = cheaper, max(0.0, cheaper.mile - position - fuel)
        elif remaining <= range_miles:
            stops[-1][2] += max(0.0, remaining - fuel)
            break
        elif in_range:
            nxt, buy = min(in_range, key=lambda s: (s.price, s.mile)), range_miles - fuel
        else:
            raise NoFuelInRange(
                f"No fuel stations between mile {position:.0f} and mile {position + range_miles:.0f} "
                f"(the vehicle range is {range_miles:.0f} miles)."
            )
        stops[-1][2] += buy
        fuel = fuel + buy - (nxt.mile - position)
        position, price = nxt.mile, nxt.price
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
