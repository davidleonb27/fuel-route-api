# Fuel Route Optimizer API

Django REST API that takes a start and finish location in the USA and returns:

- the driving route, as GeoJSON plus an interactive map page,
- where to fuel up along it for a vehicle with a **500 mile range**, chosen for the lowest cost,
- the **total fuel cost** at **10 MPG**, using the provided truck-stop price list.

Built with Django 6.1, Django REST Framework, NumPy/SciPy and the free
[OSRM](https://project-osrm.org/) routing service. **Each plan makes one routing call, and
none when the route has been seen before.**

| Route | Distance | Stops | Fuel cost | Cold response | Cached |
| --- | --- | --- | --- | --- | --- |
| New York, NY to Los Angeles, CA | 2,810 mi | 7 | $861.49 | ~0.8 s | ~10 ms |
| Seattle, WA to Miami, FL | 3,303 mi | 8 | $1,042.91 | ~1.3 s | ~10 ms |
| Chicago, IL to Houston, TX | 1,083 mi | 3 | $325.31 | ~0.7 s | ~10 ms |
| Austin, TX to Dallas, TX | 196 mi | 1 | $56.49 | ~0.4 s | ~10 ms |

Cold response time is almost entirely the single OSRM request. Local compute is roughly
50 to 150 ms.

## Quick start

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py load_fuel_stations
python manage.py runserver
```

```bash
curl "http://127.0.0.1:8000/api/v1/route-plan/?start=New+York,+NY&finish=Los+Angeles,+CA"
```

- Interactive docs (Swagger): <http://127.0.0.1:8000/api/docs/>
- Map of any plan: the `map_url` field in the response, for example
  <http://127.0.0.1:8000/api/v1/route-plan/map/?start=New+York,+NY&finish=Los+Angeles,+CA>
- Postman: import `postman/fuel-route-api.postman_collection.json`. It holds 11 requests with
  assertions (one routing call, stops never over the 50 gal tank, costs add up, error cases).

With Docker:

```bash
docker build -t fuel-route-api .
docker run -p 8000:8000 -e DJANGO_SECRET_KEY=change-me fuel-route-api
```

## API

`GET /api/v1/route-plan/?start=...&finish=...` or `POST /api/v1/route-plan/` with a JSON body.

| Field | Required | Description |
| --- | --- | --- |
| `start`, `finish` | yes | `"City, ST"`, `"City, State"`, a street address, or `"lat,lng"` |
| `stop_cost` | no | Dollar cost per fuel stop, 0 to 500, default 15. See below |
| `corridor_miles` | no | How far off the route a station may be, 1 to 50, default 10 |
| `initial_fuel_gallons` | no | Fuel in the tank when leaving, 0 to 50, default 0 |

Response (trimmed):

```json
{
  "start":  {"label": "New York, NY", "lat": 40.662712, "lng": -73.938677, "source": "census_place"},
  "finish": {"label": "Los Angeles, CA", "lat": 34.019394, "lng": -118.410825, "source": "census_place"},
  "vehicle": {"range_miles": 500, "mpg": 10, "tank_gallons": 50, "initial_fuel_gallons": 0, "stop_cost": 15},
  "route":  {"distance_miles": 2810.4, "duration_hours": 50.31, "stations_considered": 459},
  "fuel_stops": [
    {
      "sequence": 1,
      "station": {"id": 52322, "name": "BOLLA MARKET", "address": "I-95, EXIT 13", "city": "Elizabeth", "state": "NJ",
                  "lat": 40.666367, "lng": -74.193503, "price_per_gallon": 3.099,
                  "listed_price_range": [3.099, 3.099], "price_listings": 1},
      "route_mile": 15.0, "off_route_miles": 5.7,
      "fuel_on_arrival_gallons": 0.0, "gallons": 39.6, "cost": 122.72
    }
  ],
  "summary": {"number_of_stops": 7, "trip_fuel_gallons": 281.04, "gallons_purchased": 281.0,
              "total_fuel_cost": 861.49, "average_price_per_gallon": 3.066},
  "geojson": {"type": "FeatureCollection", "features": ["route line, start, finish, one point per stop"]},
  "map_url": "http://127.0.0.1:8000/api/v1/route-plan/map/?start=New+York%2C+NY&finish=Los+Angeles%2C+CA",
  "meta": {"cached": false, "geocoding_api_calls": 0, "routing_api_calls": 1, "compute_ms": 815.0}
}
```

| Status | When |
| --- | --- |
| 400 | Invalid parameters, or a location that isn't in the US or can't be reached by road (Hawaii) |
| 422 | No route between the points, or no feasible plan (a stretch over 500 miles with no station) |
| 502 | The routing service is down |

`GET /api/health/` returns 200 once stations are loaded and 503 before that.

## How it works

```
start, finish ──► geocode (offline) ──► 1 OSRM call ──► stations near the route ──► optimiser ──► response
                         │                    │                                                    │
                  Census place index     cached by coords                                   cached by request
```

1. **Geocoding without API calls.** `"City, ST"` input is looked up in a local index of
   ~48,000 US places built from the US Census Gazetteer (`data/us_places.csv.gz`).
   Coordinates skip geocoding entirely. Only free-text street addresses fall back to Nominatim,
   and those results are cached.
2. **One routing call.** OSRM returns distance, duration and the full geometry in a single
   request. The geometry comes back as an encoded polyline, which is about 5 times smaller than
   GeoJSON and saves up to a second per call.
3. **Stations near the route.** The route is resampled every 0.5 miles and put in a KD-tree on
   3-D unit-sphere coordinates, so distances are in real miles. Every station within the corridor
   gets its mile marker along the route. This takes about 40 ms for a coast-to-coast trip with
   6,600 stations.
4. **Optimiser.** `fuel/services/optimizer.py` has two exact algorithms:
   - `plan_purchases`: the classic minimum-cost refuelling greedy. At each stop, if a cheaper
     station is within range, buy just enough to reach it; otherwise fill up and go to the
     cheapest station in range. This gives the lowest possible fuel spend.
   - `plan_purchases_with_stop_cost`: a dynamic program over fuel level (0.1 gal steps) that
     minimises **fuel spend + `stop_cost` per stop**. With pure cost minimisation the plan will
     happily stop for 1.15 gal to save a cent a gallon (19 stops coast to coast). At the default
     of $15 per stop, New York to Los Angeles takes **7 stops for $861.49, versus 19 stops for
     $853.01**: 1% more fuel spend for 12 fewer stops. Send `stop_cost=0` for the absolute
     cheapest plan.

   Tests check the greedy against a brute-force dynamic program on random routes, check that the
   stop-cost DP with `stop_cost=0` matches the greedy exactly, and check that a positive stop
   cost never gives a worse objective or more stops.
5. **Total cost** is the sum of what's bought at each stop (gallons times that stop's price).
   The vehicle starts empty by default and fuels at a station within 25 route miles of the start.
   Pass `initial_fuel_gallons` to start with fuel.
6. **Caching.** Routes and finished plans are cached, so a repeated request (and the map page,
   which reuses the plan) answers in about 10 ms with zero external calls. The default file cache
   is shared by all gunicorn workers. Set `REDIS_URL` to share it across machines.
7. **Startup.** `config/wsgi.py` warms up the SciPy import and both indexes. With
   `gunicorn --preload` this happens once in the master process, so no request pays the
   ~2 second cold start.

## The price data and what had to be cleaned

`python manage.py load_fuel_stations` runs every row through `fuel/services/ingest.py` and prints
a report. On the provided file:

```
rows read: 8151, accepted: 7531
duplicate station ids: 568 (487 with conflicting prices, max spread $0.900); price = median of observations
names reconciled across duplicates: 227
text fields repaired (mojibake): 1
non-US rows excluded: {'AB': 180, 'ON': 217, 'BC': 121, 'NB': 4, 'SK': 36, 'MB': 42, 'QC': 6, 'YT': 8, 'NS': 6}
price outliers kept (> Q3 + 3*IQR): 12: #72368 CHEVRON #352416 $6.3990, #70300 PILOT #1194 $6.0390, ...
geocoded: 6626/6626
```

| Problem in the file | Handling |
| --- | --- |
| The same truck stop listed up to 6 times with different prices | One station; price is the **median**, and min, max and count are kept and returned |
| Same id under different names ("PILOT #1194" vs "PILOT DEALER #1194") | Most frequent name |
| 621 rows in Canadian provinces | Excluded and counted; the API is US-only |
| Cities padded with spaces, ALL CAPS, "Mc Calla" vs "McCalla", "Saint" vs "St." | Normalised before matching |
| `Stuckeyâ€™s` (UTF-8 read as cp1252) | Repaired |
| Prices with 8 decimals | Quantised to 4 |
| Very high prices | Kept but reported; the optimiser avoids them on its own |
| No coordinates at all | City centroid from the Census index (99.9%); the rest were geocoded once with Nominatim and saved to `data/station_geocodes.csv`, so loading never needs the network |

The loader also copes with input this file doesn't have: header names in any case or order,
`;`, tab or `|` delimiters, cp1252 encoding, `$3.45` or `3,45` prices, blank lines, rows with
missing or invalid fields (skipped and counted), and implausible prices. It upserts in one
transaction and removes stations that are no longer in the file, so re-running it is safe.
`--dry-run` prints the report without writing anything.

## Design notes and trade-offs

- **Station locations are city-level.** The CSV gives an address like "I-44, EXIT 283", a city
  and a state. Geocoding 6,600 such addresses through a free API at 1 request per second takes
  hours and is unreliable for exit descriptions, so stations use their city's centroid. That's
  why the corridor defaults to 10 miles; `off_route_miles` is reported for each stop.
- **The detour to a station** isn't added to fuel use, which keeps fuel bought equal to the
  route distance divided by 10 MPG.
- **The routing provider is swappable.** `RoutingProvider` is a small protocol, so OSRM can be
  replaced (self-hosted OSRM, GraphHopper, Google) without touching the planner.
  `OSRM_BASE_URL` points at any OSRM server; the public demo server has no SLA.
- **Throttling.** Anonymous requests are limited to 120 per minute (`API_ANON_THROTTLE`) to
  protect the free upstream services.

## Configuration

All optional, via environment variables:

| Variable | Default |
| --- | --- |
| `DJANGO_DEBUG` | `true` (`false` in the Docker image) |
| `DJANGO_SECRET_KEY` | dev key; required when debug is off |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,0.0.0.0` |
| `OSRM_BASE_URL` | `https://router.project-osrm.org` |
| `NOMINATIM_BASE_URL` | `https://nominatim.openstreetmap.org` |
| `FUEL_STOP_COST_USD` | `15` |
| `FUEL_CORRIDOR_MILES` | `10` |
| `FUEL_ORIGIN_RADIUS_MILES` | `25` |
| `VEHICLE_RANGE_MILES` / `VEHICLE_MPG` | `500` / `10` |
| `PLAN_CACHE_SECONDS` | `86400` |
| `REDIS_URL` | unset (file cache in `.cache/`) |
| `API_ANON_THROTTLE` | `120/min` |

## Quality

```bash
pytest --cov=fuel      # 220 tests, 95% coverage, runs offline (OSRM and Nominatim are mocked)
ruff check . && ruff format --check .
python manage.py spectacular --validate --fail-on-warn
```

The same checks run in `.github/workflows/ci.yml`.

## Rebuilding the place index

```bash
python manage.py build_place_index \
  --places 2025_Gaz_place_national.txt \
  --cousubs 2025_Gaz_cousubs_national.txt
```

Source files: <https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html>

## Project layout

```
config/                       settings, URLs, WSGI with warm-up
fuel/models.py                FuelStation
fuel/views.py                 route plan, map page, health
fuel/services/optimizer.py    greedy and stop-cost DP (pure Python and NumPy, no Django)
fuel/services/planner.py      geocode -> route -> stations on route -> optimise -> response
fuel/services/routing.py      OSRM client behind a RoutingProvider protocol
fuel/services/geocoding.py    offline Census lookup, Nominatim fallback
fuel/services/geometry.py     resampling, KD-tree helpers, vectorised line simplification
fuel/services/ingest.py       CSV cleaning and data-quality report
fuel/management/commands/     load_fuel_stations, build_place_index
postman/                      Postman collection
tests/                        optimiser, ingestion, geometry, geocoding, commands, API
```
