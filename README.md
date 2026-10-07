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

Docker alternative: `docker compose up --build` (serves on http://localhost:8000).

Tests and lint:

```bash
pytest
ruff check .
```

Configuration (environment variables): `GEO_DATA_DIR` (DB and uploads, default `./data`), `GEO_MAX_UPLOAD_MB` (default 50), `GEO_ASYNC` (set to `1` for background processing), `GEO_ASYNC_WORKERS` (default 2), `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`.

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

## Measurement methods

| `method` | How | Use when |
| --- | --- | --- |
| `projected` (default) | Reproject each feature to its UTM zone (polar: equal-area CRS), then measure in metres | Surveying-scale work; matches GIS tools working in a projected CRS |
| `geodesic` | Measure directly on the WGS84 ellipsoid with `pyproj.Geod` | You want no projection distortion at all |

On the sample polygon in `samples/qgis_check.kml` the two methods differ by about 0.12% in area and 0.06% in length. Each feature records the CRS or ellipsoid it was measured in (`measured_in_crs`).

## Background processing

Set `GEO_ASYNC=1` to return `202` immediately and process in an in-process worker pool (`GEO_ASYNC_WORKERS`, default 2). It needs no broker, which keeps setup trivial. Limitation: queued jobs are lost if the server restarts and it does not scale past one process; for that, replace `measurements/jobs.py::submit` with a Celery/RQ task that calls `jobs.run`.

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
  jobs.py              optional background worker (GEO_ASYNC=1)
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
- Optional background processing (`GEO_ASYNC=1`) with `202` + polling.
- 56 automated unit and integration tests passing.

## Learnings

- **CRS Transformation Fundamentals:** Geographic coordinates (latitude/longitude degrees) are angular measurements on an ellipsoid where longitude distance shrinks toward the poles (proportional to cos(latitude)). Converting to an appropriate projected coordinate system (UTM zone in metres) is mandatory before computing Euclidean distance or area.
- **Coordinate Axis Ordering:** By specification EPSG:4326 defines latitude before longitude (northing/easting), whereas GIS data formats (GeoJSON, Shapefiles) conventionally store longitude before latitude (x, y). Explicitly setting `always_xy=True` in `pyproj.Transformer` is essential to prevent swapped axis bugs.
- **Shapefile Format Structure:** A Shapefile is a multi-file collection (`.shp`, `.shx`, `.dbf`, `.prj`) strictly supporting a single geometry type per layer. Supporting multi-layer archives requires reading and merging all `.shp` files within the archive.
- **KML Multi-Layer Handling:** KML files structure data across multiple folders, which GDAL surfaces as distinct layers. Reading all layers iteratively ensures complete feature extraction without omitting grouped geometries.
- **Fail Fast on Missing CRS:** Files lacking CRS definition (such as shapefiles without `.prj`) should fail explicitly rather than assuming a default, preventing silent mathematical errors.
- **Separation of Concerns:** Decoupling geospatial algorithms into pure service functions (`measure.py`, `reader.py`) outside Django views makes them directly unit-testable and portable across worker processes.

## Known Limitations and Future Scope

- Celery/Redis task queue and progress reporting for very large files (the in-process worker is single-process and non-durable).
- User authentication and per-tenant upload isolation.
- PostgreSQL/PostGIS integration for spatial indexing and bounding-box queries.
