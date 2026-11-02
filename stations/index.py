"""In-memory station index. Built once per process; a request only runs vectorized lookups."""
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from .geo import chord_to_miles, densify, miles_to_chord, to_unit_xyz
from .models import Station

DENSIFY_STEP_MILES = 1.0


@dataclass
class RouteStation:
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    price: float
    lat: float
    lng: float
    mile: float
    offset_miles: float


_cache = {}


def reset_index():
    _cache.clear()


def _load():
    if not _cache:
        rows = list(Station.objects.values_list("opis_id", "name", "address", "city", "state", "price", "lat", "lng"))
        _cache["rows"] = rows
        _cache["xyz"] = to_unit_xyz([r[6] for r in rows], [r[7] for r in rows]) if rows else np.empty((0, 3))
    return _cache["rows"], _cache["xyz"]


def stations_along(route_coords, corridor_miles, total_miles=None):
    """Stations within corridor_miles of the route, each with its mile marker, sorted by mile.

    route_coords: sequence of (lat, lng). total_miles: the provider's route distance; mile markers
    are rescaled to it because a simplified geometry is slightly shorter than the road.
    """
    rows, station_xyz = _load()
    if not rows or len(route_coords) == 0:
        return []
    points, cumulative = densify(route_coords, DENSIFY_STEP_MILES)
    if total_miles and cumulative[-1] > 0:
        cumulative = cumulative * (total_miles / cumulative[-1])
    tree = cKDTree(to_unit_xyz(points[:, 0], points[:, 1]))
    dist, idx = tree.query(station_xyz, k=1, distance_upper_bound=float(miles_to_chord(corridor_miles)))
    found = np.flatnonzero(np.isfinite(dist))
    result = []
    for i in found:
        opis_id, name, address, city, state, price, lat, lng = rows[i]
        result.append(
            RouteStation(
                opis_id=opis_id, name=name, address=address, city=city, state=state,
                price=float(price), lat=lat, lng=lng,
                mile=float(cumulative[idx[i]]), offset_miles=float(chord_to_miles(dist[i])),
            )
        )
    result.sort(key=lambda s: s.mile)
    return result
