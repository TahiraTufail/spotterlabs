import pytest
import responses
from django.core.cache import cache
from django.test import Client

from routing.planner import optimize_fuel_stops
from stations.index import RouteStation, reset_index, stations_along
from stations.models import Station


def encode_polyline(coords):
    """Encode [(lat, lng), ...] as a precision-5 polyline, the format ORS returns."""
    out, prev = [], (0, 0)
    for lat, lng in coords:
        point = (round(lat * 1e5), round(lng * 1e5))
        for value in (point[0] - prev[0], point[1] - prev[1]):
            value = ~(value << 1) if value < 0 else value << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        prev = point
    return "".join(out)


def rs(mile, price, offset=0.0):
    return RouteStation(0, f"S{mile}", "", "", "TX", price, 0.0, 0.0, mile, offset)


def test_optimizer_buys_only_to_reach_cheaper_station_then_finishes():
    # Start station is $4.00; a $3.00 station sits at mile 200; the trip is 600 miles.
    plan = optimize_fuel_stops([rs(10, 4.00), rs(200, 3.00)], total_miles=600)

    assert [round(s.gallons, 2) for s in plan.stops] == [20.0, 40.0]
    assert plan.total_cost == pytest.approx(20 * 4.00 + 40 * 3.00)
    assert plan.total_gallons == pytest.approx(600 / 10)


def test_optimizer_drops_stops_that_save_less_than_the_penalty():
    # After filling at mile 10, the greedy plan tops up 2 gallons at mile 30 to save cents.
    stations = [rs(10, 2.80), rs(30, 2.85), rs(400, 3.00)]

    greedy = optimize_fuel_stops(stations, total_miles=900)
    consolidated = optimize_fuel_stops(stations, total_miles=900, stop_penalty=5.0)

    assert [s.station.mile for s in greedy.stops] == [10, 30, 400]
    assert [s.station.mile for s in consolidated.stops] == [10, 400]
    assert consolidated.total_cost - greedy.total_cost < 5.0
    assert consolidated.total_gallons == pytest.approx(900 / 10)


def test_optimizer_prefers_on_route_station_over_slightly_cheaper_detour():
    # 14 miles off the route is $3.00; on the route is $3.02. The detour burns more than the 2 cents saved.
    plan = optimize_fuel_stops([rs(10, 3.00, offset=14), rs(20, 3.02, offset=0)], total_miles=100)

    assert [s.station.mile for s in plan.stops] == [20]
    assert plan.total_cost == pytest.approx(10 * 3.02)  # money uses the real price


def test_city_lookup_matches_names_spelled_with_a_space():
    from stations.cities import lookup_city

    assert lookup_city("Mc Lean", "IL") is not None  # GeoNames spells it McLean
    assert lookup_city("De Forest", "WI") is not None


@pytest.mark.django_db
def test_stations_along_keeps_corridor_and_sets_mile_marker():
    reset_index()
    # East-west route along latitude 32 for about 100 miles (1 degree of longitude ~ 58.6 miles).
    route = [(32.0, -97.0), (32.0, -95.3)]
    Station.objects.create(opis_id=1, name="near", address="", city="A", state="TX", price="3.0", lat=32.05, lng=-96.4)
    Station.objects.create(opis_id=2, name="far", address="", city="B", state="TX", price="3.0", lat=33.0, lng=-96.4)

    found = stations_along(route, corridor_miles=15)

    assert [s.name for s in found] == ["near"]
    assert found[0].mile == pytest.approx(35, abs=2)  # 0.6 degrees of longitude from the start
    assert found[0].offset_miles == pytest.approx(3.5, abs=1)


@pytest.mark.django_db
@responses.activate
def test_endpoint_returns_plan_and_second_call_uses_cache():
    reset_index()
    cache.clear()
    Station.objects.create(opis_id=1, name="Start Stop", address="", city="A", state="TX", price="3.0", lat=32.0, lng=-96.8)
    responses.add(
        responses.POST,
        "https://api.openrouteservice.org/v2/directions/driving-car",
        json={
            "routes": [
                {
                    "geometry": encode_polyline([(32.0, -96.8), (32.0, -96.2)]),
                    "summary": {"distance": 160934.4},  # 100 miles
                }
            ]
        },
    )
    payload = {"start": "32.0,-96.8", "finish": "32.0,-96.2"}

    first = Client().post("/api/v1/route-plan/", payload, content_type="application/json")
    second = Client().post("/api/v1/route-plan/", payload, content_type="application/json")

    body = first.json()
    assert first.status_code == 200
    assert body["distance_miles"] == pytest.approx(100, abs=0.1)
    assert body["total_cost"] == pytest.approx(30.0)  # 100 miles / 10 mpg * $3.00
    assert sum(s["cost"] for s in body["fuel_stops"]) == pytest.approx(body["total_cost"], abs=0.01)
    assert body["map_url"].startswith("http://testserver/?start=")  # absolute, so it is clickable in Postman
    assert second.json()["cached"] is True
    assert len(responses.calls) == 1
