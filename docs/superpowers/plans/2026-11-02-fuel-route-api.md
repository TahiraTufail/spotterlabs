# Fuel Route API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Django API that takes a US start and finish, returns the driving route, the cost-optimal fuel stops (500 mile range), and the total fuel spend at 10 MPG, plus a small web page that shows the route on a map.

**Architecture:** Station prices from the supplied CSV are cleaned and given approximate coordinates once, offline, then held in memory. Each request makes one OpenRouteService (ORS) directions call (two more only if an input is not in the offline city index), keeps stations within a corridor of the route, and runs a greedy fuel-purchase algorithm over them. Results are cached by normalized input.

**Tech Stack:** Django (latest stable, confirm on PyPI at setup), Django REST Framework, requests, NumPy, SciPy (`cKDTree`), Redis with django-redis (cache), pytest-django, responses (HTTP mocking), Leaflet 1.9.4 with OpenStreetMap tiles.

**Spec:** The assessment email (summarized under Global Constraints). Input data: `fuel-prices-for-be-assessment.csv`.

## Global Constraints

- Framework: latest stable Django.
- Input: a start and a finish, both within the USA.
- Output: a map of the route, the fuel-up locations along it, and total money spent on fuel.
- Vehicle: maximum range 500 miles, 10 miles per gallon (so a 50 gallon tank).
- Prices come only from the supplied CSV (columns: `OPIS Truckstop ID, Truckstop Name, Address, City, State, Rack ID, Retail Price`).
- Routing and geocoding come from a free external API. One call is ideal, two or three acceptable, per request.
- The API must be fast: no per-request CSV parsing, no per-request database scan of all stations.
- Cache: Redis (`REDIS_URL`, default `redis://localhost:6379/1`). Tests use `LocMemCache` so they run without Redis.
- Deliverables: GitHub repository, plus a Postman collection for the Loom demo (the Loom itself is recorded by the user).
- Frontend: simple and clean, one accent color on a neutral palette, no gradients, no shadows, no emojis anywhere (UI, README, API messages).

## Review Focus

Failure modes the brief implies but does not state, most likely first:

1. A stretch of more than 500 miles with no station in the corridor (west Texas, Nevada, Montana): respond 422 naming the mile range, never 500.
2. Start or finish outside the USA, or a bare ambiguous name like "Springfield": 422 with a message asking for "City, ST".
3. ORS timeout, 401, 429 or 5xx: 502 with a short message, no stack trace, and nothing cached.
4. The CSV repeats a station ID with different names or prices: keep one row per ID, lowest price.
5. A very short trip (under 50 miles) or start equal to finish: one origin fill, correct cost, no divide-by-zero.

## Assumptions (documented in README)

- **Starting fuel:** the brief does not say whether the tank starts empty or full. It asks for the "total money spent on fuel" for the route at 10 MPG, so the plan charges for every gallon the trip burns. That is modeled as an origin fill at mile 0, priced at the cheapest station within 50 route miles of the start. If none exists, the first station on the route sets the price and the response flags it with `origin_fill_estimated`. A free full tank would make any trip under 500 miles cost zero, which contradicts the brief's cost requirement. State this reading in the README.
- **Station coordinates:** the CSV has no coordinates, so stations are placed at their city center. This is approximate, which is why the corridor is wide (15 miles) and why detour cost is ignored.
- **End of trip:** the last purchase covers only the fuel needed to reach the destination.
- **Prices:** `Retail Price` is dollars per gallon and applies to the vehicle's fuel.

## File Structure

```
manage.py
requirements.txt
.env.example                    ORS_API_KEY, CACHE settings
fuelroute/                      project package (settings.py, urls.py)
stations/
  models.py                     Station
  geo.py                        distance, unit vectors, densify (pure)
  cities.py                     offline "City, ST" lookup (pure + cached loader)
  index.py                      in-memory station KD-tree + corridor query
  management/commands/load_stations.py
  data/                         us_cities.csv (built from GeoNames), not the raw price CSV
routing/
  ors.py                        ORS client: geocode(), directions()
  planner.py                    optimize_fuel_stops() (pure)
  service.py                    plan_route(start, finish) orchestration + cache
  views.py, serializers.py, urls.py
  errors.py                     PlanError subclasses and their HTTP codes
web/
  templates/web/index.html
  static/web/app.css, app.js
tests/                          mirrors the packages above
README.md, postman/fuel-route.postman_collection.json
```

---

### Task 1: Project scaffold

**Files:**
- Create: `manage.py`, `fuelroute/settings.py`, `fuelroute/urls.py`, `requirements.txt`, `.env.example`, `.gitignore`, `pytest.ini`, `tests/test_health.py`
- Create apps: `stations`, `routing`, `web`

**Interfaces:**
- Produces: settings `ORS_API_KEY: str`, `ORS_TIMEOUT_SECONDS = 10`, `VEHICLE_RANGE_MILES = 500`, `VEHICLE_MPG = 10`, `CORRIDOR_MILES = 15`, `ORIGIN_FILL_WINDOW_MILES = 50`. Read from environment where a secret, constants otherwise.

- [ ] **Step 1: Write the failing test** in `tests/test_health.py`: `test_health_returns_ok` does `client.get("/api/v1/health/")` and asserts `status_code == 200` and `json() == {"status": "ok"}`.
- [ ] **Step 2: Run** `pytest tests/test_health.py -v`. Expected: FAIL (404 or import error).
- [ ] **Step 3: Create the project** with `django-admin startproject fuelroute .`, the three apps, DRF in `INSTALLED_APPS`, SQLite database, default cache backed by Redis through `django_redis.cache.RedisCache` with `LOCATION = env REDIS_URL`; `pytest.ini` points at a test settings module that overrides `CACHES` with `LocMemCache`. Add `REDIS_URL` to `.env.example`. Add the `health` view in `routing/views.py` and route it in `routing/urls.py` under `api/v1/`.
- [ ] **Step 4: Run** the test. Expected: PASS.
- [ ] **Step 5: Commit** `git init` plus the scaffold: `chore: scaffold django project`.

---

### Task 2: Geometry helpers

**Files:**
- Create: `stations/geo.py`
- Test: `tests/stations/test_geo.py`

**Interfaces:**
- Produces:
  - `haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float`
  - `to_unit_xyz(lat: ndarray, lng: ndarray) -> ndarray` shape `(n, 3)`, points on the unit sphere
  - `miles_to_chord(miles: float) -> float` converts a surface distance to the chord length used by the KD-tree
  - `densify(coords: list[tuple[float, float]], step_miles: float) -> tuple[ndarray, ndarray]` returns `(points_lat_lng shape (n,2), cumulative_miles shape (n,))`, inserting points so no gap exceeds `step_miles`. Input order is `(lat, lng)`.

- [ ] **Step 1: Write failing tests:**
  - `test_haversine_dallas_to_chicago`: result is within 2 percent of 802 miles.
  - `test_miles_to_chord_roundtrip`: for 100 miles, the chord between two points 100 miles apart on the equator equals `miles_to_chord(100)` within 1e-6.
  - `test_densify_caps_gap`: a two-point 50 mile line with `step_miles=1` yields cumulative miles whose max diff is at most 1.01 and whose last value is within 0.1 of 50.
  - `test_densify_single_point_returns_zero_length`: one input point yields cumulative `[0.0]`.
- [ ] **Step 2: Run** the tests. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** with Earth radius 3958.8 miles. `densify` interpolates linearly in lat/lng per segment (adequate at 1 mile spacing).
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add geometry helpers`.

---

### Task 3: Station import with approximate coordinates

**Files:**
- Create: `stations/models.py`, `stations/management/commands/load_stations.py`, `stations/cities.py`, `stations/data/us_cities.csv` (generated)
- Create: `stations/management/commands/build_city_index.py`
- Test: `tests/stations/test_load_stations.py`, `tests/stations/test_cities.py`, fixture `tests/fixtures/stations_sample.csv`

**Interfaces:**
- Produces:
  - Model `Station(opis_id: int unique, name: str, address: str, city: str, state: str, price: Decimal(6,4), lat: float, lng: float)`
  - `normalize_place(text: str) -> str`: lowercase, strip, collapse spaces, expand `st.`/`mt`/`ft` to `saint`/`mount`/`fort`
  - `lookup_city(city: str, state: str) -> tuple[float, float] | None`
  - `parse_place_query(text: str) -> tuple[str, str] | None`: splits "Dallas, TX" or "Dallas TX" into `("dallas", "TX")`, returns `None` if no state part
  - Command `load_stations <csv_path> [--clear]` prints loaded, merged duplicate, dropped non-US, and unmatched counts.
  - Command `build_city_index <geonames_US.txt>` writes `us_cities.csv` with columns `name,state,lat,lng,population`, including alternate names as extra rows. Source is GeoNames `US.zip` (CC BY 4.0, credit it in README).

- [ ] **Step 1: Write failing tests:**
  - `test_merges_duplicate_ids_keeps_lowest_price`: fixture has ID 20 twice (3.899 and 3.799); after load, one `Station` with price `3.799`.
  - `test_drops_canadian_provinces`: a row with state `ON` is not stored; command output contains `dropped_non_us=1`.
  - `test_unmatched_city_is_skipped_and_counted`: a row with city `Nowhereville` is not stored; output contains `unmatched=1`.
  - `test_lookup_city_handles_abbreviations`: `lookup_city("Mt. Jackson", "VA")` is not `None`.
  - `test_lookup_city_picks_largest_population_on_name_clash`: two rows named Springfield in one state resolve to the larger one.
  - `test_parse_place_query_requires_state`: `"Springfield"` returns `None`; `"Dallas, TX"` and `"dallas tx"` both return `("dallas", "TX")`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement** the model and migration, `cities.py` (loader cached with `functools.lru_cache`, dict keyed by `(normalized_name, state)`), and both commands. `load_stations` reads with `csv.DictReader` and `encoding="utf-8-sig"`, groups by `OPIS Truckstop ID`, keeps the minimum price, and uses `bulk_create` inside one transaction.
- [ ] **Step 4: Download GeoNames `US.zip`, run** `build_city_index`, then `load_stations` on the real CSV. Record the unmatched percentage in the README. If it is above 5 percent, add the failing city names to a short alias table in `cities.py` and re-run. Expected: a count close to 6,700 stations loaded.
- [ ] **Step 5: Run** the tests. Expected: PASS.
- [ ] **Step 6: Commit** `feat: import stations with city coordinates`.

---

### Task 4: ORS client

**Files:**
- Create: `routing/ors.py`, `routing/errors.py`
- Test: `tests/routing/test_ors.py`

**Interfaces:**
- Produces:
  - `errors.PlanError(Exception)` with `status: int` and `message: str`; subclasses `InvalidLocation (400)`, `OutsideUsa (422)`, `NoFuelInRange (422)`, `UpstreamError (502)`
  - `ors.geocode(text: str) -> tuple[float, float]` returns `(lat, lng)`; uses the ORS Pelias search with `boundary.country=US` and `size=1`; raises `InvalidLocation` on no result
  - `ors.directions(start: tuple[float, float], finish: tuple[float, float]) -> Route` where `Route = dataclass(coords: list[tuple[float, float]], distance_miles: float)`; coords are `(lat, lng)`
  - A module-level `requests.Session` with `Authorization` header and `timeout=settings.ORS_TIMEOUT_SECONDS`.

- [ ] **Step 1: Write failing tests** using the `responses` library:
  - `test_directions_parses_geojson`: mocked response with two coordinates and `summary.distance` of 160934 meters returns `distance_miles` within 0.01 of 100 and coords swapped to `(lat, lng)`.
  - `test_directions_sends_instructions_false`: the captured request JSON has `"instructions": false`.
  - `test_directions_maps_429_to_upstream_error`: a 429 response raises `UpstreamError` with status 502.
  - `test_directions_maps_timeout_to_upstream_error`: a `requests.Timeout` raises `UpstreamError`.
  - `test_geocode_no_features_raises_invalid_location`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.** Directions endpoint: `POST /v2/directions/driving-car/geojson`, body `{"coordinates": [[lng, lat], [lng, lat]], "instructions": false}`. ORS takes `[lng, lat]`, so swap carefully at the boundary and nowhere else. Do not log the API key.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Live check (manual, one request):** with a real key, call `directions` for New York to Los Angeles and note the response time and whether the distance limit rejects it. If it rejects, add a midpoint waypoint split (still within three calls) and update the tests.
- [ ] **Step 6: Commit** `feat: add openrouteservice client`.

---

### Task 5: Stations along the route

**Files:**
- Create: `stations/index.py`
- Test: `tests/stations/test_index.py`

**Interfaces:**
- Consumes: `densify`, `to_unit_xyz`, `miles_to_chord` from Task 2; `Station` from Task 3.
- Produces:
  - `dataclass RouteStation(opis_id: int, name: str, address: str, city: str, state: str, price: float, lat: float, lng: float, mile: float, offset_miles: float)`
  - `stations_along(route_coords: list[tuple[float, float]], corridor_miles: float) -> list[RouteStation]` sorted by `mile`
  - The station KD-tree is built once on first use, held in a module-level cache, and cleared by `reset_index()` for tests.

- [ ] **Step 1: Write failing tests** using a handful of `Station` rows created in the test database around a straight east-west test route:
  - `test_includes_station_inside_corridor`: a station 5 miles off the line is returned with `offset_miles` near 5.
  - `test_excludes_station_outside_corridor`: one 40 miles off is not returned.
  - `test_mile_marker_is_distance_along_route`: stations at roughly 10 and 60 miles from the start get `mile` within 2 of those values.
  - `test_results_sorted_by_mile`.
  - `test_two_stations_at_same_city_keep_both_with_same_mile` (city-level coordinates make this common).
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.** Build a `cKDTree` over densified route points (unit xyz, 1 mile spacing) and query it with each station's coordinates using `query(k=1, distance_upper_bound=miles_to_chord(corridor_miles))`, which returns nearest route vertex and index for all stations in one vectorized call. `mile` is the cumulative distance at that vertex. Load all stations once into NumPy arrays and drop those with infinite distance.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: find stations along a route`.

---

### Task 6: Fuel stop optimizer

**Files:**
- Create: `routing/planner.py`
- Test: `tests/routing/test_planner.py`

**Interfaces:**
- Consumes: `RouteStation` from Task 5; `NoFuelInRange` from Task 4.
- Produces:
  - `dataclass FuelStop(station: RouteStation, mile: float, gallons: float, price: float, cost: float)`
  - `dataclass FuelPlan(stops: list[FuelStop], total_cost: float, total_gallons: float, origin_fill_estimated: bool)`
  - `optimize_fuel_stops(stations: list[RouteStation], total_miles: float, range_miles: float = 500, mpg: float = 10, origin_window_miles: float = 50) -> FuelPlan`

**Algorithm (pins the behavior):** The tank starts empty. The origin fill is a stop at mile 0 priced at the cheapest station with `mile <= origin_window_miles` (that station's price, not its mile marker). If none qualifies, use the price of the first station on the route and set `origin_fill_estimated=True`. From the current stop, look at stations within `range_miles` ahead. If one is cheaper than the current price, buy exactly enough to reach it and go there. Otherwise, if the destination is within range, buy enough to reach it and finish. Otherwise fill the tank (`range_miles / mpg` gallons) and go to the cheapest station in range. If nothing is in range and the destination is not, raise `NoFuelInRange` stating the mile range. Merge consecutive zero-gallon stops away.

- [ ] **Step 1: Write failing tests** (prices in dollars per gallon, miles on the route):
  - `test_short_trip_single_origin_fill`: 100 miles, a station at mile 10 priced 3.00. Result has one stop, `total_gallons == 10.0`, `total_cost == 30.0`.
  - `test_cheaper_station_ahead_buys_only_to_reach_it`: origin station 4.00, station at mile 200 priced 3.00, finish at mile 600. The first stop buys exactly 20 gallons; the second stop buys 40 gallons (to the finish).
  - `test_no_cheaper_station_fills_tank_then_picks_cheapest_in_range`: origin 3.00, stations at miles 300 (3.50) and 450 (3.20), finish at mile 900. First stop buys 50 gallons, next stop is mile 450.
  - `test_total_gallons_equals_total_miles_over_mpg`: for any plan, `total_gallons` is within 0.001 of `total_miles / mpg`.
  - `test_gap_over_range_raises_no_fuel_in_range`: origin station then nothing for 600 miles raises with a message containing both mile values.
  - `test_start_equals_finish_zero_miles`: `total_miles == 0` returns zero stops and cost 0.
  - `test_no_stations_in_origin_window_flags_estimate`: first station at mile 80 sets `origin_fill_estimated=True`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement** `optimize_fuel_stops` per the algorithm above. Work in miles of range rather than gallons until output, to avoid float drift, and round cost to cents only in the response layer.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add fuel stop optimizer`.

---

### Task 7: Orchestration, caching and the API endpoint

**Files:**
- Create: `routing/service.py`, `routing/serializers.py`
- Modify: `routing/views.py`, `routing/urls.py`
- Test: `tests/routing/test_service.py`, `tests/routing/test_api.py`

**Interfaces:**
- Consumes: `parse_place_query`, `lookup_city` (Task 3); `ors.geocode`, `ors.directions` (Task 4); `stations_along` (Task 5); `optimize_fuel_stops` (Task 6).
- Produces:
  - `plan_route(start: str, finish: str) -> dict` returning the response body below
  - `POST /api/v1/route-plan/` with body `{"start": str, "finish": str}`; both accept "City, ST" or "lat,lng"
  - Response `200`:

```json
{
  "start": {"query": "Dallas, TX", "lat": 32.78, "lng": -96.8},
  "finish": {"query": "Chicago, IL", "lat": 41.88, "lng": -87.63},
  "distance_miles": 925.4,
  "total_gallons": 92.54,
  "total_cost": 301.52,
  "origin_fill_estimated": false,
  "fuel_stops": [
    {"order": 1, "opis_id": 123, "name": "", "address": "", "city": "", "state": "",
     "lat": 0.0, "lng": 0.0, "mile": 0.0, "price_per_gallon": 3.05, "gallons": 50.0, "cost": 152.5}
  ],
  "route": {"type": "LineString", "coordinates": [[-96.8, 32.78]]},
  "map_url": "/?start=Dallas%2C+TX&finish=Chicago%2C+IL",
  "timing_ms": {"routing": 0, "stations": 0, "optimize": 0, "total": 0}
}
```

  - Error body for every failure: `{"error": {"code": "no_fuel_in_range", "message": "..."}}` with the HTTP status from `PlanError.status`.

- [ ] **Step 1: Write failing tests** (ORS mocked with `responses`, stations created in the test database):
  - `test_post_returns_plan`: status 200, keys above present, `total_cost` equals the sum of `fuel_stops[].cost` within 0.01.
  - `test_same_request_twice_makes_one_ors_call`: after two identical POSTs, the mock reports `len(responses.calls) == 1`.
  - `test_normalized_inputs_share_cache`: "Dallas, TX" and " dallas,tx " produce one ORS call.
  - `test_city_in_offline_index_skips_geocode_call`: no request to the ORS geocode URL is made.
  - `test_unknown_place_falls_back_to_geocode`: an unmatched input triggers exactly one geocode call.
  - `test_missing_state_returns_400_with_hint`: body `{"start": "Springfield", ...}` gives 400 and a message mentioning "City, ST".
  - `test_outside_usa_returns_422`: a mocked geocode result outside the US bounding box gives 422 `outside_usa`.
  - `test_ors_failure_returns_502_and_is_not_cached`: after a 500 then a 200 on retry, the second POST succeeds.
  - `test_no_fuel_in_range_returns_422`.
  - `test_missing_field_returns_400`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement.** Cache key `route:{normalized_start}|{normalized_finish}` storing the full response (24 hour TTL; cache only on success). Geocode only the inputs that miss the offline index; run two geocodes concurrently with `ThreadPoolExecutor` when both miss. Validate resolved coordinates against a continental US plus Alaska and Hawaii bounding box. Time each stage with `time.perf_counter` for `timing_ms`. Serializer validates the two string fields (non-empty, max 200 characters). The DRF exception handler converts `PlanError` to the error body.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add route-plan endpoint`.

---

### Task 8: Frontend page

**Files:**
- Create: `web/templates/web/index.html`, `web/static/web/app.css`, `web/static/web/app.js`
- Modify: `web/views.py`, `fuelroute/urls.py`
- Test: `tests/web/test_index.py`

**Interfaces:**
- Consumes: `POST /api/v1/route-plan/` (Task 7).
- Produces: `GET /` renders the page. Query params `start` and `finish` prefill the form and submit automatically (this is what `map_url` links to).

**Design rules (so it does not look generated):**
- One page, one column of controls above a map, summary and stops table below on narrow screens; two columns (controls and results at 380px, map filling the rest) from 900px up.
- Palette: white page, one near-black text color, one mid-gray for borders and secondary text, one accent (a single dark blue) used only for the primary button, links and the route line. Error text uses the same dark text with a left border in the accent, not red. No gradients, no shadows, no emoji, no icons beyond a plain map marker.
- Type: the system font stack, two sizes plus one small label size, tabular numerals for prices and miles.
- Shape: 1px gray borders, 4px radius, generous whitespace on an 8px spacing scale. No cards inside cards.
- Controls: two labeled text inputs ("Start", "Finish") with placeholder "City, ST", one button "Plan route". The button shows "Planning..." and is disabled while the request runs. Inputs have visible labels, focus outlines, and keyboard submit.
- Results: a three-row summary list (Distance, Fuel, Total cost) followed by a plain table of stops (#, Station, Location, Mile, Price, Gallons, Cost). Clicking a row pans the map to that stop. A small line states `timing_ms.total` and whether the origin fill was estimated.
- Map: Leaflet 1.9.4 from cdnjs with a pinned version, OpenStreetMap tiles with attribution, the route as a 3px accent polyline, the start and finish as small filled circles, fuel stops as numbered circles matching the table. Fit bounds to the route. Popups show name, price and gallons only.
- Accessibility: the results region uses `aria-live="polite"`, the map has a text alternative (the table), and contrast meets WCAG AA.

- [ ] **Step 1: Write failing tests** in `tests/web/test_index.py`:
  - `test_index_renders_form`: `client.get("/")` is 200 and contains `name="start"`, `name="finish"` and the button text `Plan route`.
  - `test_index_has_no_emoji_or_gradient`: the rendered HTML and `app.css` contain no `gradient(` and no characters in the emoji ranges.
  - `test_index_prefills_from_query`: `/?start=A%2C+TX&finish=B%2C+IL` returns inputs with those values.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Build the page** with the template, CSS variables for the four colors, and `app.js` using `fetch` to the API, rendering the summary and table with `textContent` (never `innerHTML` on API data), and drawing the route from the returned GeoJSON.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Manual check** in the browser at 375px and 1280px widths: Dallas, TX to Chicago, IL, then Los Angeles, CA to New York, NY. Confirm stop numbers match the table, the map fits the route, and an error (an invalid place) shows a plain message.
- [ ] **Step 6: Commit** `feat: add route planner page`.

---

### Task 9: Performance, docs and delivery

**Files:**
- Create: `README.md`, `postman/fuel-route.postman_collection.json`, `tests/routing/test_perf.py`
- Modify: `routing/service.py` only if the measurements demand it

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the test** `test_processing_time_excluding_ors_under_200ms`: with ORS mocked to return a 900 mile route of about 2,000 points and the full real station set loaded, `plan_route(...)["timing_ms"]["stations"] + ["optimize"]` is under 200 on the dev machine (relax the number if the first KD-tree build counts; warm it with one prior call).
- [ ] **Step 2: Run** it. Expected: FAIL only if the code is slower than the budget; if it passes immediately, keep it as a regression guard.
- [ ] **Step 3: Measure for real** with a live key: first-request and cached-request times for three routes (short, 900 miles, coast to coast). Put them in a README table, noting which part is ORS.
- [ ] **Step 4: Write the README:** setup (`pip install`, start Redis with `docker run -p 6379:6379 redis:7`, `.env`, `migrate`, `load_stations`, `runserver`), the endpoint with a curl example, the algorithm in five sentences, the assumptions above, the speed measures taken (single directions call, offline geocoding, caching, in-memory KD-tree), known limits (city-level coordinates, no detour cost), and the GeoNames credit.
- [ ] **Step 5: Postman collection** with three requests: a short trip, a long multi-stop trip, and an error case (`"Springfield"`). Add a `pm.test` on each that checks status and, for success, that `total_cost` is a number.
- [ ] **Step 6: Run the whole suite** with `pytest -q`. Expected: all pass.
- [ ] **Step 7: Push** to a new GitHub repository, and confirm a fresh clone works by following the README alone.
- [ ] **Step 8: Loom outline (5 minutes):** 0:00 to 0:30 what it does; 0:30 to 2:30 Postman: short trip, long trip, an error; 2:30 to 3:30 the web page; 3:30 to 5:00 code tour of `ors.py`, `index.py`, `planner.py`, and the cache.
- [ ] **Step 9: Commit** `docs: add readme, postman collection and perf test`.

---

## Self-Review

- **Spec coverage:** route map (Tasks 7, 8); optimal fuel stops by price (Task 6); 500 mile range with multiple stops (Task 6); total cost at 10 MPG (Tasks 6, 7); CSV prices (Task 3); free routing API with at most three calls (Tasks 4, 7); latest Django (Task 1); speed (Tasks 5, 7, 9); Postman and Loom (Task 9); GitHub (Task 9).
- **Review Focus coverage:** item 1 in Task 6 (`test_gap_over_range_raises_no_fuel_in_range`) and Task 7; item 2 in Task 7; item 3 in Task 7; item 4 in Task 3; item 5 in Task 6.
- **Type consistency:** coordinates are `(lat, lng)` everywhere except the ORS request and the GeoJSON output, which use `[lng, lat]`; the swap happens only in `ors.py` and the response serializer.

## Decisions made

- Starting fuel: every gallon the trip burns is paid for (see Assumptions).
- Cache: Redis.
