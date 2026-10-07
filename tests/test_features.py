import csv
import io
import json
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from pyproj import CRS, Geod
from shapely.geometry import LineString, MultiPolygon, Polygon, box

from measurements import jobs
from measurements.models import UploadedFile
from measurements.services.measure import measure_geometry

pytestmark = pytest.mark.django_db

WGS84 = CRS.from_epsg(4326)
GEOD = Geod(ellps="WGS84")


def _upload(client, name, content, **extra):
    payload = {"file": SimpleUploadedFile(name, content), **extra}
    return client.post("/api/files/", payload, format="multipart")


# ---- geodesic method ----
def test_geodesic_area_matches_pyproj_exactly():
    poly = box(77.0, 12.9, 77.02, 12.92)
    m = measure_geometry(poly, WGS84, "geodesic")
    assert m.value == pytest.approx(abs(GEOD.geometry_area_perimeter(poly)[0]), rel=1e-9)
    assert m.unit == "m²" and "geodesic" in m.measured_in_crs


def test_geodesic_subtracts_holes_whatever_the_ring_orientation():
    outer = [(77, 0), (77.02, 0), (77.02, 0.02), (77, 0.02)]
    hole = [(77.005, 0.005), (77.005, 0.01), (77.01, 0.01), (77.01, 0.005)]
    full = measure_geometry(Polygon(outer), WGS84, "geodesic").value
    holed = measure_geometry(Polygon(outer, [hole]), WGS84, "geodesic").value
    holed_reversed = measure_geometry(Polygon(outer, [hole[::-1]]), WGS84, "geodesic").value
    assert holed == pytest.approx(holed_reversed) and holed < full


def test_geodesic_multipolygon_and_line():
    mp = MultiPolygon([box(77, 0, 77.01, 0.01), box(78, 0, 78.01, 0.01)])
    one = measure_geometry(box(77, 0, 77.01, 0.01), WGS84, "geodesic").value
    assert measure_geometry(mp, WGS84, "geodesic").value == pytest.approx(2 * one, rel=0.01)
    line = LineString([(77, 0), (77, 0.01)])
    assert measure_geometry(line, WGS84, "geodesic").value == pytest.approx(
        GEOD.geometry_length(line)
    )


def test_geodesic_for_projected_source_goes_back_to_wgs84():
    utm43 = CRS.from_epsg(32643)
    rect = box(500000, 0, 500100, 200)  # 100 x 200 m, close to the central meridian
    assert measure_geometry(rect, utm43, "geodesic").value == pytest.approx(20000, rel=0.002)


def test_unknown_method_rejected_in_service_and_api(client, kml_bytes):
    with pytest.raises(ValueError):
        measure_geometry(box(0, 0, 1, 1), WGS84, "magic")
    assert _upload(client, "s.kml", kml_bytes, method="magic").status_code == 400


def test_geodesic_upload_agrees_with_projected_within_half_percent(client, kml_bytes):
    results = {}
    for method in ("projected", "geodesic"):
        body = _upload(client, "survey.kml", kml_bytes, method=method).json()
        assert body["method"] == method
        feats = client.get(f"/api/files/{body['id']}/measurements/").json()["features"]
        results[method] = {f["properties"]["Name"]: f["measurement"]["value"] for f in feats}
    assert results["geodesic"]["square"] == pytest.approx(results["projected"]["square"], rel=0.005)
    assert results["geodesic"]["road"] == pytest.approx(results["projected"]["road"], rel=0.005)


# ---- summary ----
def test_measurements_include_whole_file_summary(client, kml_bytes):
    file_id = _upload(client, "survey.kml", kml_bytes).json()["id"]
    page = client.get(f"/api/files/{file_id}/measurements/?limit=1").json()
    assert len(page["features"]) == 1  # summary still covers all three features
    summary = page["summary"]
    assert summary["by_geometry_type"] == {"Polygon": 1, "LineString": 1, "Point": 1}
    assert summary["totals"]["area"]["m²"] == pytest.approx(1.2309e6, rel=0.01)
    assert summary["totals"]["length"]["m"] == pytest.approx(1105.7, rel=0.01)


# ---- export ----
def test_export_geojson(client, kml_bytes):
    file_id = _upload(client, "survey.kml", kml_bytes).json()["id"]
    r = client.get(f"/api/files/{file_id}/export/")
    assert r.status_code == 200 and r["Content-Type"] == "application/geo+json"
    assert "attachment" in r["Content-Disposition"]
    data = json.loads(r.content)
    assert data["type"] == "FeatureCollection" and len(data["features"]) == 3
    assert data["crs"]["properties"]["name"] == "EPSG:4326"
    polygon = next(f for f in data["features"] if f["properties"]["Name"] == "square")
    assert polygon["properties"]["measurement_type"] == "area"
    assert polygon["geometry"]["type"] == "Polygon"


def test_export_csv(client, kml_bytes):
    file_id = _upload(client, "survey.kml", kml_bytes).json()["id"]
    r = client.get(f"/api/files/{file_id}/export/?as=csv")
    assert r.status_code == 200 and r["Content-Type"] == "text/csv"
    rows = list(csv.DictReader(io.StringIO(r.content.decode())))
    assert len(rows) == 3
    square = next(row for row in rows if "square" in row["properties"])
    assert square["measurement_type"] == "area" and square["geometry_wkt"].startswith("POLYGON")


def test_export_of_failed_file_is_409(client):
    bad = _upload(client, "bad.zip", b"not a zip").json()["id"]
    assert client.get(f"/api/files/{bad}/export/").status_code == 409


def test_export_unknown_format(client, kml_bytes):
    file_id = _upload(client, "survey.kml", kml_bytes).json()["id"]
    assert client.get(f"/api/files/{file_id}/export/?as=shp").status_code == 400


# ---- delete + retention ----
def test_delete_removes_record_features_and_upload(client, kml_bytes):
    file_id = _upload(client, "survey.kml", kml_bytes).json()["id"]
    record = UploadedFile.objects.get(pk=file_id)
    path = record.upload_path()
    assert path.exists()
    assert client.delete(f"/api/files/{file_id}/").status_code == 204
    assert not path.exists()
    assert not UploadedFile.objects.filter(pk=file_id).exists()
    assert client.get(f"/api/files/{file_id}/").status_code == 404
    assert client.delete(f"/api/files/{file_id}/").status_code == 404


def test_cleanup_command_deletes_only_old_files(client, kml_bytes, capsys):
    old_id = _upload(client, "old.kml", kml_bytes).json()["id"]
    new_id = _upload(client, "new.kml", kml_bytes).json()["id"]
    UploadedFile.objects.filter(pk=old_id).update(created_at=timezone.now() - timedelta(days=40))
    old_path = UploadedFile.objects.get(pk=old_id).upload_path()

    call_command("cleanup_uploads", "--days", "30", "--dry-run")
    assert UploadedFile.objects.filter(pk=old_id).exists()  # dry run changes nothing

    call_command("cleanup_uploads", "--days", "30")
    assert not UploadedFile.objects.filter(pk=old_id).exists() and not old_path.exists()
    assert UploadedFile.objects.filter(pk=new_id).exists()
    assert "Deleted 1 file(s)" in capsys.readouterr().out


# ---- async mode ----
def test_async_upload_returns_202_then_completes(client, kml_bytes, settings, monkeypatch):
    settings.ASYNC_PROCESSING = True
    queued = []
    monkeypatch.setattr(jobs, "submit", lambda record_id, path: queued.append((record_id, path)))

    r = _upload(client, "survey.kml", kml_bytes)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "PENDING" and body["feature_count"] == 0
    assert client.get(f"/api/files/{body['id']}/measurements/").status_code == 409  # not ready

    assert len(queued) == 1
    jobs.run(*queued[0])  # what the worker thread does

    done = client.get(f"/api/files/{body['id']}/").json()
    assert done["status"] == "COMPLETED" and done["feature_count"] == 3
    assert client.get(f"/api/files/{body['id']}/measurements/").status_code == 200


def test_job_for_deleted_file_is_ignored(tmp_path):
    jobs.run("00000000-0000-0000-0000-000000000000", tmp_path / "gone.kml")  # must not raise


# ---- OpenAPI ----
def test_openapi_schema_and_swagger_ui(client):
    schema = client.get("/api/schema/?format=json")
    assert schema.status_code == 200
    paths = json.loads(schema.content)["paths"]
    for p in ("/api/files/", "/api/files/{id}/", "/api/files/{id}/measurements/",
              "/api/files/{id}/export/"):
        assert p in paths
    assert client.get("/api/docs/").status_code == 200
