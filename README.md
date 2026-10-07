# Geospatial File Measurement API

[![CI](https://github.com/sanjanamg0/geospatial-measurement-api/actions/workflows/ci.yml/badge.svg)](https://github.com/sanjanamg0/geospatial-measurement-api/actions/workflows/ci.yml)

Django + Django REST Framework service that accepts a zipped **Shapefile** or a **KML** file, extracts every feature, and returns **area** (polygons) and **length** (lines) in metres.

## Setup

Requires Python 3.12+. No system GDAL is needed: `pyogrio`, `shapely` and `pyproj` ship wheels that bundle GDAL, GEOS and PROJ.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows (source .venv/bin/activate on Linux/macOS)
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py runserver
```

Docker alternatives:

- `docker compose up --build`: the API only (SQLite), on http://localhost:8000.
- `docker compose -f docker-compose.full.yml up --build`: the production-style stack (PostgreSQL + PostGIS, Redis, API, Celery worker, authentication on). See [Production stack](#production-stack).

Tests and lint:

```bash
pytest
ruff check .
```

`requirements-dev.txt` also installs the optional packages (`requirements-optional.txt`: Celery and the PostgreSQL driver). The base `requirements.txt` is enough to run the API with SQLite.

Configuration (environment variables):

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEO_DATA_DIR` | `./data` | SQLite DB and uploaded files |
| `GEO_MAX_UPLOAD_MB` | 50 | Upload size limit |
| `GEO_DATABASE_URL` | (SQLite) | `postgres://user:pass@host:5432/db` to use PostgreSQL (PostGIS is used when available) |
| `GEO_ASYNC` | off | `1`/`thread`: in-process worker; `celery`: Celery worker through a broker |
| `GEO_ASYNC_WORKERS` | 2 | Thread pool size for `GEO_ASYNC=1` |
| `GEO_CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery broker |
| `GEO_REQUIRE_AUTH` | off | `1`: token authentication required, users see only their own files |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | dev defaults | Django settings |

**Interactive API docs (Swagger UI):** http://localhost:8000/api/docs/ (OpenAPI schema at `/api/schema/`).

## API

### `POST /api/files/`
Multipart upload. Fields:

- `file` (required): a `.kml`, or a `.zip` containing one or more Shapefiles.
- `method` (optional): `projected` (default) or `geodesic`, see [Measurement methods](#measurement-methods).

By default the file is processed synchronously (`201`; the response already carries the final status). With `GEO_ASYNC=1` it returns `202` with `status: "PENDING"` and a background worker processes it; poll `GET /api/files/{id}/` until `status` is `COMPLETED` or `FAILED`.

```bash
curl -F file=@samples/survey_sample.kml http://localhost:8000/api/files/
```
```json
{
  "id": "1249d2d535144b85b9259476d7138841",
  "filename": "survey_sample.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "method": "projected",
  "error": null,
  "created_at": "2026-10-07T10:27:12.147231Z"
}
```

| Case | Result |
| --- | --- |
| Wrong extension / missing file / too large | `400` with validation message |
| Corrupt zip, unreadable data, no CRS | `201` with `status: "FAILED"` and an `error` message |

### `GET /api/files/{id}/`
Same shape as the upload response. `404` for unknown ids.

### `DELETE /api/files/{id}/`
Deletes the record, its features and the stored upload. `204` on success, `404` if unknown.

### `GET /api/files/{id}/measurements/?limit=100&offset=0`
`409` unless the file is `COMPLETED`. Paginated: `limit` defaults to 100 (max 1000); the response includes `count` (total), `next` and `previous` links.

```json
{
  "file_id": "1249d2d535144b85b9259476d7138841",
  "status": "COMPLETED",
  "count": 3,
  "next": null,
  "previous": null,
  "summary": {
    "by_geometry_type": {"Polygon": 1, "LineString": 1, "Point": 1},
    "totals": {"area": {"m²": 11050.42}, "length": {"m": 1105.7}}
  },
  "features": [
    {
      "index": 0,
      "geometry_type": "Polygon",
      "crs": "EPSG:4326",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[77.5946, 12.9716], [77.5956, 12.9716], "..."]]
      },
      "properties": {"Name": "Agricultural Field 1"},
      "measurement": {
        "type": "area",
        "value": 11050.42,
        "unit": "m²",
        "measured_in_crs": "EPSG:32643",
        "note": null
      }
    }
  ]
}
```

`measurement.type` is `area`, `length`, or `null` (points and unsupported types, with an explanatory `note`). Geometry is returned as GeoJSON in the file's original CRS. `summary` covers the whole file (not just the current page): counts per geometry type and totals of area/length per unit.

### `GET /api/files/{id}/export/?as=geojson|csv`
Downloads every feature with its measurement. GeoJSON (default) keeps the source CRS in a top-level `crs` member; CSV has one row per feature with the geometry as WKT. `409` unless the file is `COMPLETED`; `400` for an unknown `as`.

```bash
curl -OJ "http://localhost:8000/api/files/<id>/export/?as=csv"
```

### `GET /api/files/`
Lists files (paginated with `limit`/`offset`). With authentication enabled, only your own.

### Filtering by area: `?bbox=minx,miny,maxx,maxy`
Both `/measurements/` and `/export/` accept `bbox` (in the file's own CRS) and return only the features intersecting it; `count` and `summary` then describe the filtered set. `400` for malformed or inverted boxes. On SQLite and plain PostgreSQL this compares each feature's stored bounding box (indexed). On PostgreSQL with PostGIS it uses `ST_Intersects` against a GiST-indexed geometry column, so it tests the real shape: a box that only overlaps the empty corner of an L-shaped polygon matches without PostGIS and does not match with it.

## Authentication

Off by default so you can try the API with plain `curl`. Set `GEO_REQUIRE_AUTH=1` to require a token on every file endpoint; each user then only sees, lists, exports and deletes their own files (anyone else's id returns `404`).

```bash
curl -X POST localhost:8000/api/auth/register/ -d username=demo -d password='correct-horse-battery'
# {"username": "demo", "token": "..."}
curl -X POST localhost:8000/api/auth/token/ -d username=demo -d password='correct-horse-battery'   # log in again
curl -H "Authorization: Token <token>" -F file=@samples/survey_sample.kml localhost:8000/api/files/
```

Passwords go through Django's validators (minimum 8 characters, not a common password). Tokens do not expire; there is no rate limiting yet (see future scope).

## Measurement methods

| `method` | How | Use when |
| --- | --- | --- |
| `projected` (default) | Reproject each feature to its UTM zone (polar: equal-area CRS), then measure in metres | Surveying-scale work; matches GIS tools working in a projected CRS |
| `geodesic` | Measure directly on the WGS84 ellipsoid with `pyproj.Geod` | You want no projection distortion at all |

On the sample polygon in `samples/qgis_check.kml` the two methods differ by about 0.12% in area and 0.06% in length. Each feature records the CRS or ellipsoid it was measured in (`measured_in_crs`).

## Background processing

Uploads can be processed in the background: the API returns `202` with `status: "PENDING"` and the client polls `GET /api/files/{id}/`. Two backends share the same processing function (`measurements/jobs.py::run`):

| `GEO_ASYNC` | Backend | Trade-off |
| --- | --- | --- |
| `1` / `thread` | In-process thread pool (`GEO_ASYNC_WORKERS`) | No extra services; jobs are lost if the server restarts; single process only |
| `celery` | Celery worker via a broker (Redis by default) | Durable, scales with more workers; needs Redis and a worker process |

```bash
pip install -r requirements-optional.txt
export GEO_ASYNC=celery GEO_CELERY_BROKER_URL=redis://localhost:6379/0
celery -A geoproject worker -l info          # terminal 1
python manage.py runserver                   # terminal 2
bash scripts/smoke_async.sh http://localhost:8000   # upload, poll, check results
```

The API and the worker must see the same upload directory (`GEO_DATA_DIR`) and the same database; use PostgreSQL when they run on different machines or containers.

## PostgreSQL and PostGIS

Set `GEO_DATABASE_URL=postgres://user:pass@host:5432/db` to use PostgreSQL instead of SQLite. Migration `0004` then tries to enable the PostGIS extension and adds a `geom` geometry column with a GiST index; if PostGIS is not available it logs a warning and the API still works with bounding-box filtering. GeoDjango is deliberately not used, so installing the project still needs no system GDAL (the PostGIS column is filled and queried with a few lines of SQL in `measurements/spatial.py`). Geometries are stored 2D in the file's own SRID (KML altitudes are dropped).

## Production stack

```bash
docker compose -f docker-compose.full.yml up --build
```

Starts PostGIS, Redis, the API (gunicorn) and a Celery worker with authentication on. Swagger UI is at http://localhost:8000/api/docs/. Change `DJANGO_SECRET_KEY` and the database password in the compose file before any real deployment.

## Maintenance

```bash
python manage.py cleanup_uploads --days 30            # delete files older than 30 days
python manage.py cleanup_uploads --days 30 --dry-run  # only report
```

## Architecture

```
geoproject/            Django project (settings, urls)
measurements/
  models.py            UploadedFile, Feature
  serializers.py       upload validation, response shapes
  views.py             FileViewSet (create, retrieve, delete, measurements, export)
  jobs.py / tasks.py   optional background processing (thread pool or Celery task)
  auth_views.py        register / token endpoints; permissions.py: optional auth switch
  spatial.py           bbox filtering, PostGIS geometry column (raw SQL, no GeoDjango)
  management/commands/ cleanup_uploads retention command
  services/
    reader.py          zip/KML -> GeoDataFrame (framework independent)
    measure.py         CRS selection + area/length (framework independent)
    processor.py       orchestration + persistence
tests/
samples/               sample KML and Shapefile files for testing
```

**File-processing flow:** upload validated -> saved under `data/uploads/<id>` -> (inline, or via the background worker) status `PROCESSING` -> `reader` parses it -> every feature is measured -> features bulk-inserted -> status `COMPLETED` (or `FAILED` with a message).

**Measurement flow:** per feature, `measure_geometry` picks the measurement kind from the geometry type (Polygon/MultiPolygon -> area, LineString/MultiLineString -> length, Point and anything else -> no measurement plus a note), reprojects if needed, and measures.

**CRS handling**
- Geographic CRS (such as EPSG:4326): each feature is reprojected to the UTM zone of its own centroid (EPSG:326xx north / 327xx south), then measured in metres. Degrees are never used for area or distance calculations.
- Outside UTM's valid latitude band (north of 84 N or south of 80 S), a Lambert azimuthal equal-area CRS centred on the pole is used instead.
- Features crossing the antimeridian are shifted onto a continuous 0..360 longitude range before determining the centroid.
- Invalid geometries (such as bow-tie self-intersecting polygons) are repaired with `shapely.make_valid`, and the feature's `note` records the repair.
- Projected CRS: measured in place; the unit is read from the CRS definition.
- KML without CRS info defaults to WGS84 by specification. A shapefile with no `.prj` is rejected as `FAILED`, because guessing a CRS would produce inaccurate numbers.

## Design Decisions

- **Django + DRF over FastAPI:** batteries included (ORM, migrations, validation, test client). The geospatial logic is isolated in `services/` without Django imports, making it clean, modular, and reusable.
- **No GeoDjango / PostGIS requirement:** GeoDjango requires system-level GDAL and PostGIS server configuration. Since this service processes uploaded files on the fly and stores results, GeoPandas and Shapely handle all operations in Python wheels without external dependencies.
- **Per-feature UTM projection:** selecting UTM by feature centroid minimises projection distortion (< 0.2%) even for datasets that span multiple UTM zones.
- **Synchronous processing with status tracking:** typical survey files process in milliseconds. The model stores explicit status transitions (`PENDING` -> `PROCESSING` -> `COMPLETED`/`FAILED`), making it straightforward to offload to background queues (Celery/RQ) if needed.
- **Stored measurement results:** features and calculated values are persisted to JSON and relational fields during processing, making `/measurements/` a fast and repeatable database read.
- **Security guards:** zip-slip directory traversal protection, uncompressed archive size limits (zip-bomb guard), upload payload caps, and automatic temporary extraction cleanup.

## Validation

Results are cross-checked in the test suite against an independent ellipsoidal calculation (`pyproj.Geod`) on 0.02 x 0.02 degree test polygons across multiple latitudes. Observed difference of UTM-based planar measurements versus geodesic benchmarks:

| Site (lon, lat) | Deviation |
| --- | --- |
| 77.0, 12.9 | +0.04% |
| -122.4, 37.8 | -0.07% |
| 151.2, -33.9 | -0.01% |
| 10.0, 60.0 | -0.07% |
| 0.1, 0.1 (near zone edge) | +0.18% |

All test cases assert agreement within 0.5%.

### Independent check against QGIS

`samples/qgis_check.kml` (an irregular polygon and a polyline near Bangalore) was measured in QGIS (project ellipsoid WGS 84; field calculator `$area`, `$length`, and `area()`/`length()` of the geometry transformed to EPSG:32643) and compared with this API:

| Quantity | API | QGIS | Difference |
| --- | --- | --- | --- |
| Area, geodesic (`method=geodesic`) | 273068.8226675242 m² | 273068.8226675242 m² | 0 |
| Area, UTM 43N (`method=projected`) | 273385.02470 m² | 273385 m² (field rounded to whole m²) | +0.02 m² (0.00001%) |
| Length, geodesic | 1285.9520287970836 m | 1285.9520287970836 m | 0 |
| Length, UTM 43N | 1286.698838265507 m | 1286.698838265507 m | 0 |

The two methods differ from each other by about 0.12% (area) and 0.06% (length) on this sample, which is the expected UTM scale distortion 2.6 degrees from the zone's central meridian.

## Hardening Implemented

- Geodesic cross-check tests across 5 global locations.
- Automatic geometry repair (`shapely.make_valid`) for self-intersecting shapes.
- Antimeridian coordinate unwrapping and polar LAEA projection fallback.
- Cached coordinate transformers (`lru_cache`) for efficient reprojections.
- Paginated measurements endpoint with limit and offset controls.
- Zip-bomb thresholds (max 1000 archive members, 500 MB max uncompressed size).
- Automatic cleanup of extracted temporary folders after processing.
- Structured logging with feature count and execution duration.
- GitHub Actions CI workflow running tests and linter on Python 3.12.
- Swagger UI / OpenAPI schema, geodesic measurement mode, GeoJSON and CSV export, whole-file summary, delete endpoint and retention command.
- Optional background processing with `202` + polling: in-process threads or a Celery worker.
- Optional token authentication with per-user file isolation.
- Optional PostgreSQL/PostGIS with `?bbox=` spatial filtering (GiST index, `ST_Intersects`).
- 79 automated tests on PostGIS (76 on SQLite plus 4 PostGIS-only tests that are skipped there). CI runs the suite on SQLite and on PostGIS, plus an end-to-end job with a real Celery worker and Redis.

## Learnings

- **CRS Transformation Fundamentals:** Geographic coordinates (latitude/longitude degrees) are angular measurements on an ellipsoid where longitude distance shrinks toward the poles (proportional to cos(latitude)). Converting to an appropriate projected coordinate system (UTM zone in metres) is mandatory before computing Euclidean distance or area.
- **Coordinate Axis Ordering:** By specification EPSG:4326 defines latitude before longitude (northing/easting), whereas GIS data formats (GeoJSON, Shapefiles) conventionally store longitude before latitude (x, y). Explicitly setting `always_xy=True` in `pyproj.Transformer` is essential to prevent swapped axis bugs.
- **Shapefile Format Structure:** A Shapefile is a multi-file collection (`.shp`, `.shx`, `.dbf`, `.prj`) strictly supporting a single geometry type per layer. Supporting multi-layer archives requires reading and merging all `.shp` files within the archive.
- **KML Multi-Layer Handling:** KML files structure data across multiple folders, which GDAL surfaces as distinct layers. Reading all layers iteratively ensures complete feature extraction without omitting grouped geometries.
- **Fail Fast on Missing CRS:** Files lacking CRS definition (such as shapefiles without `.prj`) should fail explicitly rather than assuming a default, preventing silent mathematical errors.
- **Separation of Concerns:** Decoupling geospatial algorithms into pure service functions (`measure.py`, `reader.py`) outside Django views makes them directly unit-testable and portable across worker processes.

## Known Limitations and Future Scope

- Progress reporting for very large files, and streaming/chunked reading.
- Token expiry and rotation, rate limiting on the auth endpoints, per-user quotas; OAuth/SSO if this becomes multi-tenant.
- Reprojecting `bbox` queries from WGS84 so clients need not know each file's CRS.
- Spatial analysis on the stored geometries (area within a polygon, nearest feature) now that PostGIS holds them.
