# Fuel Route API

Django API that takes a start and a finish inside the USA and returns the driving route, the
cheapest places to fuel along it (500 mile range), and the total fuel cost at 10 MPG. A small web
page draws the route and the stops on a map.

## How it works

1. **Prices.** `data/fuel-prices.csv` is loaded once into the database (`load_stations`). Duplicate
   station IDs are merged (lowest price kept) and Canadian rows are dropped. The CSV has no
   coordinates, so each station is placed at the center of its city using a GeoNames-derived index
   (`stations/data/us_cities.csv`).
2. **Route.** One call to OpenRouteService returns the route geometry and distance. A start or
   finish given as `"City, ST"` is resolved from the offline index, so the typical request makes
   exactly **one** external call. Anything else (a bare city such as `"Austin"`, a misspelling, or a
   street address) costs one extra ORS geocode call per place, restricted to the USA. `"lat,lng"`
   input also works. A bare name that exists in several states resolves to the geocoder's top
   result, so `"City, ST"` is the unambiguous form.
3. **Stations near the route.** The route is densified to 1 mile spacing and a KD-tree finds the
   stations within 15 miles of it, each with its mile marker. Stations are held in memory.
4. **Fuel plan.** Greedy purchase planning: if a cheaper station is within range, buy just enough to
   reach it; otherwise, if the destination is in range, buy just enough to finish; otherwise fill up
   and drive to the cheapest station in range. If a 500 mile stretch has no station, the API
   answers 422 with the mile range.
5. **Caching.** The full result is cached in Redis by normalized start and finish, so a repeat
   request makes no external call. If Redis is unreachable the API still works, uncached.

## Assumptions

- **Starting fuel.** The brief does not say whether the tank starts empty or full. It asks for the
  total money spent on fuel for the route, so every gallon the trip burns is paid for. The first
  stop is the cheapest station within 50 route miles of the start, and the fuel burned before
  reaching it is priced at that station. If there is none, the first station on the route is used and
  `origin_fill_estimated` is `true`. The last purchase covers only what is needed to arrive.
- **Station locations are approximate** (city level), which is why the corridor is 15 miles wide.
  Detours to reach a station are not costed.
- **Prices** are the CSV `Retail Price` in dollars per gallon.
- Coordinate input is only checked against a rough USA bounding box. City names and geocoded text
  are restricted to the USA.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # then set ORS_API_KEY (free key: openrouteservice.org)
python manage.py migrate
python manage.py load_stations
python manage.py runserver
```

**Redis.** The cache needs a Redis server at `REDIS_URL` (default `redis://localhost:6379/1`). Any of:

- Docker: `docker run -p 6379:6379 redis:7`
- WSL or Linux/macOS: `sudo apt install redis-server && redis-server`
- A hosted instance (for example a free Redis Cloud database): set `REDIS_URL` to its URL
- No install at all: `python scripts/dev_redis.py` starts an in-memory server that speaks the Redis
  protocol (development only, data is lost on exit)

Without any Redis the API still works but every request calls the routing API.

`stations/data/us_cities.csv` is committed. To rebuild it, download `US.zip` from
<https://download.geonames.org/export/dump/> (GeoNames, CC BY 4.0), unzip it, and run
`python manage.py build_city_index path/to/US.txt`.

Open <http://127.0.0.1:8000/> for the map page.

## API

`POST /api/v1/route-plan/`

```bash
curl -X POST http://127.0.0.1:8000/api/v1/route-plan/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Dallas, TX", "finish": "Chicago, IL"}'
```

Response (abridged):

```json
{
  "distance_miles": 946.7,
  "total_gallons": 94.67,
  "total_cost": 266.82,
  "origin_fill_estimated": false,
  "fuel_stops": [
    {"order": 1, "name": "...", "city": "...", "state": "..", "lat": 0, "lng": 0,
     "mile": 204.1, "price_per_gallon": 2.879, "gallons": 50.0, "cost": 143.95}
  ],
  "route": {"type": "LineString", "coordinates": [[-96.8, 32.78]]},
  "map_url": "/?start=Dallas%2C+TX&finish=Chicago%2C+IL",
  "cached": false,
  "timing_ms": {"routing": 0, "stations": 0, "optimize": 0, "total": 0}
}
```

Errors use `{"error": {"code": "...", "message": "..."}}`:

| Status | Code | When |
|---|---|---|
| 400 | `invalid_request` / `invalid_location` | Missing field, or a place that cannot be found in the USA |
| 422 | `outside_usa` | A location outside the USA |
| 422 | `no_fuel_in_range` | A stretch longer than 500 miles with no station |
| 422 | `no_route` | No road connects the two places (for example Montana to Hawaii) |
| 502 / 503 | `routing_provider_error` | The routing API failed, timed out, or has no key |

`GET /api/v1/health/` returns `{"status": "ok"}`. A Postman collection is in `postman/`.

## Speed

The routing call dominates. Measured with a live key, one request each:

| Trip | Miles | Routing API | Stations + planning | Repeat (cached) |
|---|---|---|---|---|
| Denver to Boise | 831 | 2.2 s | 0.15 s first request, about 15 ms after | 2 ms |
| New York to Los Angeles | 2,794 | 1.8 s | 40 ms | 1 ms |
| Seattle to Miami | 3,328 | 3.3 s | 0.13 s | 1 ms |

Times vary with the routing provider's load. `timing_ms` in each response splits the time by stage.

## Tests

```bash
pytest
```

Three tests cover the fuel optimizer, the route corridor search, and the endpoint (routing API
mocked) including the cache.

## Credits

City coordinates derive from GeoNames (<https://www.geonames.org>), CC BY 4.0. Map tiles are
from OpenStreetMap contributors.
