# Project Plan

Goal: submission-ready Geospatial File Measurement API (Django + DRF), public GitHub repo.

## Milestones

- [x] 1. Scaffold: Django project, `measurements` app, requirements, pyproject, Docker
- [x] 2. Services: reader (zip/KML), CRS selection + measurement, processor
- [x] 3. API: upload, file info, measurements; validation and error mapping
- [x] 4. Tests: measurement unit tests, API tests (KML, shapefile, corrupt, no CRS, 404)
- [x] 5. README: setup, API, architecture, decisions, future scope
- [x] 6. Hardening
  - [x] Geodesic (pyproj.Geod) cross-check tests; results recorded in README
  - [ ] Manual QGIS comparison of one known polygon (needs QGIS, not done)
  - [x] `shapely.make_valid` with a note on the feature
  - [x] Polar (LAEA) and antimeridian handling
  - [x] Transformer cache, pagination, zip-bomb guard, extracted-file cleanup, upload logging
  - [x] Missing tests: zip-slip, oversize, multi-layer KML, MultiPolygon, 3D coordinates (40 tests total)
  - [x] GitHub Actions workflow (ruff + pytest), not yet run on GitHub
  - [ ] Background-processing path (Celery/RQ): deferred
  - [ ] OpenAPI / Swagger UI: deferred
- [ ] 7. Publish: init git, push to a public repo, share the link
- [ ] 8. Fill in the "learning" section of the README (assignment requires it)

## Stack

Python 3.12, Django 5.2, DRF, GeoPandas/pyogrio (read), Shapely (geometry), pyproj (CRS),
SQLite, pytest-django, ruff, Docker.
