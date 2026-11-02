import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache

from stations.cities import lookup_city, parse_place_query
from stations.index import stations_along

from . import ors
from .errors import OutsideUsa
from .planner import optimize_fuel_stops

_COORD_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
_MAX_ROUTE_POINTS = 2000


def _in_usa(lat, lng):
    return 17.5 <= lat <= 71.5 and -180.0 <= lng <= -64.5


def _resolve(text):
    """"lat,lng" -> as is; "City, ST" -> offline index; anything else -> one ORS geocode call."""
    match = _COORD_RE.match(text)
    if match:
        lat, lng = float(match.group(1)), float(match.group(2))
    else:
        parsed = parse_place_query(text)
        lat, lng = (lookup_city(*parsed) if parsed else None) or ors.geocode(text)
    if not _in_usa(lat, lng):
        raise OutsideUsa(f'"{text}" is outside the USA.')
    return lat, lng


def _thin(coords, limit):
    if len(coords) <= limit:
        return coords
    step = -(-len(coords) // limit)
    return coords[::step] + ([coords[-1]] if (len(coords) - 1) % step else [])


def _ms(since):
    return round((time.perf_counter() - since) * 1000, 1)


def plan_route(start: str, finish: str) -> dict:
    started = time.perf_counter()
    start, finish = " ".join(start.split()), " ".join(finish.split())
    key = "route:" + hashlib.sha1(f"{start.lower()}|{finish.lower()}".encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return {**cached, "cached": True, "timing_ms": {"total": _ms(started)}}

    with ThreadPoolExecutor(max_workers=2) as pool:
        start_future, finish_future = pool.submit(_resolve, start), pool.submit(_resolve, finish)
        start_pt, finish_pt = start_future.result(), finish_future.result()

    t = time.perf_counter()
    route = ors.directions(start_pt, finish_pt)
    routing_ms = _ms(t)

    t = time.perf_counter()
    along = stations_along(route.coords, settings.CORRIDOR_MILES, total_miles=route.distance_miles)
    stations_ms = _ms(t)

    t = time.perf_counter()
    plan = optimize_fuel_stops(
        along,
        route.distance_miles,
        range_miles=settings.VEHICLE_RANGE_MILES,
        mpg=settings.VEHICLE_MPG,
        origin_window_miles=settings.ORIGIN_FILL_WINDOW_MILES,
    )
    optimize_ms = _ms(t)

    result = {
        "start": {"query": start, "lat": start_pt[0], "lng": start_pt[1]},
        "finish": {"query": finish, "lat": finish_pt[0], "lng": finish_pt[1]},
        "distance_miles": round(route.distance_miles, 1),
        "total_gallons": round(plan.total_gallons, 2),
        "total_cost": round(plan.total_cost, 2),
        "origin_fill_estimated": plan.origin_fill_estimated,
        "fuel_stops": [
            {
                "order": i,
                "opis_id": s.station.opis_id,
                "name": s.station.name,
                "address": s.station.address,
                "city": s.station.city,
                "state": s.station.state,
                "lat": s.station.lat,
                "lng": s.station.lng,
                "mile": round(s.mile, 1),
                "price_per_gallon": round(s.price, 3),
                "gallons": round(s.gallons, 2),
                "cost": round(s.cost, 2),
            }
            for i, s in enumerate(plan.stops, start=1)
        ],
        "route": {
            "type": "LineString",
            "coordinates": [[round(lng, 5), round(lat, 5)] for lat, lng in _thin(route.coords, _MAX_ROUTE_POINTS)],
        },
        "map_url": "/?" + urlencode({"start": start, "finish": finish}),
    }
    cache.set(key, result, settings.ROUTE_CACHE_SECONDS)
    return {
        **result,
        "cached": False,
        "timing_ms": {"routing": routing_ms, "stations": stations_ms, "optimize": optimize_ms, "total": _ms(started)},
    }
