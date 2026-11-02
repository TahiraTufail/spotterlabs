import pytest
import responses
from django.core.cache import cache
from django.test import Client

from routing.planner import optimize_fuel_stops
from stations.index import RouteStation, reset_index, stations_along
from stations.models import Station


def rs(mile, price, offset=0.0):
    return RouteStation(0, f"S{mile}", "", "", "TX", price, 0.0, 0.0, mile, offset)


def test_optimizer_buys_only_to_reach_cheaper_station_then_finishes():
    # Start station is $4.00; a $3.00 station sits at mile 200; the trip is 600 miles.
    plan = optimize_fuel_stops([rs(10, 4.00), rs(200, 3.00)], total_miles=600)

    assert [round(s.gallons, 2) for s in plan.stops] == [20.0, 40.0]
    assert plan.total_cost == pytest.approx(20 * 4.00 + 40 * 3.00)
    assert plan.total_gallons == pytest.approx(600 / 10)


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
        "https://api.openrouteservice.org/v2/directions/driving-car/geojson",
        json={
            "features": [
                {
                    "geometry": {"coordinates": [[-96.8, 32.0], [-96.2, 32.0]]},
                    "properties": {"summary": {"distance": 160934.4}},  # 100 miles
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
    assert second.json()["cached"] is True
    assert len(responses.calls) == 1
