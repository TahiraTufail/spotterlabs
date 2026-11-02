"""OpenRouteService client. ORS takes and returns [lng, lat]; the swap to (lat, lng) happens only here."""
from dataclasses import dataclass

import requests
from django.conf import settings

from .errors import InvalidLocation, NoRoute, PlanError, UpstreamError

_session = requests.Session()


@dataclass
class Route:
    coords: list  # [(lat, lng), ...]
    distance_miles: float


def _request(method, path, **kwargs):
    if not settings.ORS_API_KEY:
        err = UpstreamError("ORS_API_KEY is not configured on the server.")
        err.status = 503
        raise err
    try:
        response = _session.request(
            method,
            settings.ORS_BASE_URL + path,
            headers={"Authorization": settings.ORS_API_KEY},
            timeout=settings.ORS_TIMEOUT_SECONDS,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise UpstreamError(f"Routing provider unreachable or too slow ({type(exc).__name__}).") from exc
    if response.status_code == 200:
        return response.json()
    if response.status_code in (401, 403):
        raise UpstreamError("Routing provider rejected the API key.")
    if response.status_code == 429:
        raise UpstreamError("Routing provider rate limit reached. Try again later.")
    if response.status_code == 404:
        raise NoRoute("No driving route exists between these two places.")
    if response.status_code == 400 and "2004" in response.text:
        raise PlanError("Route is longer than the routing provider allows.")
    raise UpstreamError(f"Routing provider returned HTTP {response.status_code}.")


def geocode(text: str):
    """Return (lat, lng) for a free-text US place."""
    data = _request(
        "GET",
        "/geocode/search",
        # Place-level layers only, so "new york" resolves to the city rather than the state.
        params={
            "text": text,
            "boundary.country": "US",
            "layers": "address,venue,street,neighbourhood,locality,localadmin,borough",
            "size": 1,
        },
    )
    features = data.get("features") or []
    if not features:
        raise InvalidLocation(f'Could not find "{text}" in the USA. Try "City, ST".')
    lng, lat = features[0]["geometry"]["coordinates"]
    return lat, lng


def directions(start, finish) -> Route:
    """start and finish are (lat, lng). One POST returns the whole route."""
    data = _request(
        "POST",
        "/v2/directions/driving-car/geojson",
        json={
            "coordinates": [[start[1], start[0]], [finish[1], finish[0]]],
            "instructions": False,
            "geometry_simplify": True,
            "radiuses": [-1, -1],
        },
    )
    feature = data["features"][0]
    coords = [(lat, lng) for lng, lat in feature["geometry"]["coordinates"]]
    meters = feature["properties"]["summary"]["distance"]
    return Route(coords=coords, distance_miles=meters / 1609.344)
