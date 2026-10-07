# Geospatial File Measurement API

Django + Django REST Framework service that accepts a zipped **Shapefile** or a **KML** file,
extracts every feature, and returns **area** (polygons) and **length** (lines) in metres.

## Setup

Requires Python 3.12+. No system GDAL is needed: `pyogrio`, `shapely` and `pyproj` ship wheels
that bundle GDAL, GEOS and PROJ.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on Linux/macOS)
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

Configuration (environment variables): `GEO_DATA_DIR` (DB and uploads, default `./data`),
`GEO_MAX_UPLOAD_MB` (default 50), `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`.

## API

### `POST /api/files/`
Multipart upload, field name `file`. Accepts `.kml` or `.zip` containing one or more `.shp` sets.
The file is processed synchronously; the response already carries the final status.

```bash
curl -F file=@survey.kml http://localhost:8000/api/files/
```
```json
{"id": "1249d2d5...", "filename": "survey.kml", "feature_count": 1,
 "crs": "EPSG:4326", "status": "COMPLETED", "error": null, "created_at": "..."}
```

| Case | Result |
| --- | --- |
| Wrong extension / missing file / too large | `400` with validation message |
| Corrupt zip, unreadable data, no CRS | `201` with `status: "FAILED"` and an `error` message |

### `GET /api/files/{id}/`
Same shape as the upload response. `404` for unknown ids.

### `GET /api/files/{id}/measurements/?limit=100&offset=0`
`409` unless the file is `COMPLETED`. Paginated: `limit` defaults to 100 (max 1000); the response
includes `count` (total), `next` and `previous` links.

```json
{"file_id": "1249d2d5...", "status": "COMPLETED", "count": 1, "features": [{
  "index": 0, "geometry_type": "Polygon", "crs": "EPSG:4326",
  "geometry": {"type": "Polygon", "coordinates": [[[77.0, 0.0], "..."]]},
  "properties": {"Name": "sq"},
  "measurement": {"type": "area", "value": 1231440.2, "unit": "m²",
                  "measured_in_crs": "EPSG:32643", "note": null}}]}
```

`measurement.type` is `area`, `length`, or `null` (points and unsupported types, with a `note`).
Geometry is returned as GeoJSON in the file's **original** CRS.

## Architecture

```
geoproject/            Django project (settings, urls)
measurements/
  models.py            UploadedFile, Feature
  serializers.py       upload validation, response shapes
  views.py             FileViewSet (create, retrieve, measurements action)
  services/
    reader.py          zip/KML -> GeoDataFrame (framework independent)
    measure.py         CRS selection + area/length (framework independent)
    processor.py       orchestration + persistence
tests/
```

**File-processing flow:** upload validated -> saved under `data/uploads/<id>` -> status
`PROCESSING` -> `reader` parses it -> every feature is measured -> features bulk-inserted ->
status `COMPLETED` (or `FAILED` with a message).

**Measurement flow:** per feature, `measure_geometry` picks the measurement kind from the
geometry type (Polygon/MultiPolygon -> area, LineString/MultiLineString -> length, Point and
anything else -> no measurement plus a note), reprojects if needed, and measures.

**CRS handling**
- Geographic CRS (e.g. EPSG:4326): each feature is reprojected to the **UTM zone of its own
  centroid** (EPSG:326xx north / 327xx south), then measured in metres. Degrees are never used
  for area or distance.
- Outside UTM's valid band (north of 84 N or south of 80 S) a Lambert azimuthal equal-area CRS
  centred on the pole is used instead.
- Features crossing the antimeridian are shifted onto a continuous 0..360 longitude range first.
- Invalid geometries (e.g. bow-tie polygons) are repaired with `shapely.make_valid`, and the
  feature's `note` says so.
- Projected CRS: measured in place; the unit is read from the CRS definition.
- KML without CRS info is WGS84 by specification. A shapefile with no `.prj` is rejected as
  `FAILED`, because guessing a CRS would give silently wrong numbers.

## Design decisions

- **Django + DRF over FastAPI:** batteries included (ORM, migrations, validation, test client).
  The geospatial code lives in `services/` and does not import Django, so it is easy to test and reuse.
- **No GeoDjango/PostGIS:** it would require system GDAL and a spatial DB for a task that is
  pure computation. GeoPandas/Shapely already cover it. The trade-off is no spatial queries.
- **UTM per feature vs. one CRS per file:** per feature keeps distortion low for files spanning
  several zones. Alternative considered: a Lambert azimuthal equal-area projection centred on
  each feature, which gives exact areas worldwide but is less familiar. UTM error is typically
  well below 1% within a zone.
- **Synchronous processing:** the spec asks for upload-and-process in one call, and typical
  survey files process in well under a second. `status` is stored so moving to a background
  worker (Celery/RQ) later only changes the view, not the API.
- **Features stored in the DB (JSON columns), not recomputed:** measurements endpoint is a
  cheap read. Alternative: recompute on request, which saves storage but repeats work.
- **Safety:** zip-slip check on extraction, upload size cap, per-feature fallbacks so one bad
  geometry never fails the file.

## Validation

Results are cross-checked in the test suite against an independent ellipsoidal calculation
(`pyproj.Geod`) on 0.02 x 0.02 degree squares at five sites. Observed difference of the UTM-based
area from the geodesic area:

| Site (lon, lat) | Difference |
| --- | --- |
| 77.0, 12.9 | +0.04% |
| -122.4, 37.8 | -0.07% |
| 151.2, -33.9 | -0.01% |
| 10.0, 60.0 | -0.07% |
| 0.1, 0.1 (near a zone edge) | +0.18% |

Tests assert agreement within 0.5%. A manual comparison in QGIS has not been done yet.

## Hardening implemented

Geodesic cross-check tests, `make_valid` repair, polar and antimeridian handling, cached
transformers, paginated measurements, zip-bomb limits (1000 members / 500 MB expanded),
cleanup of extracted files, per-upload log line (status, features, duration), GitHub Actions CI
(`.github/workflows/ci.yml`: ruff + pytest). Test count: 40.

## Known limitations / future scope

- Background processing (Celery/RQ) with progress for very large files; the `status` field and
  polling endpoints already exist for it.
- A GeoJSON/CSV export.
- Authentication and per-user file ownership; cleanup of old uploads.
- Optional geodesic measurement mode (`pyproj.Geod`) selectable per request.
- OpenAPI schema / Swagger UI (drf-spectacular).
- PostgreSQL/PostGIS for spatial queries.
