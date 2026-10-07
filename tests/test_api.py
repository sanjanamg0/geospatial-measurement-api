import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

pytestmark = pytest.mark.django_db


def _upload(client, name, content):
    payload = {"file": SimpleUploadedFile(name, content)}
    return client.post("/api/files/", payload, format="multipart")


def test_upload_kml_end_to_end(client, kml_bytes):
    r = _upload(client, "survey.kml", kml_bytes)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "COMPLETED"
    assert body["feature_count"] == 3
    assert body["crs"] == "EPSG:4326"

    info = client.get(f"/api/files/{body['id']}/")
    assert info.status_code == 200 and info.json()["filename"] == "survey.kml"

    meas = client.get(f"/api/files/{body['id']}/measurements/").json()
    assert meas["count"] == 3
    by_name = {f["properties"]["Name"]: f for f in meas["features"]}
    assert by_name["square"]["measurement"]["value"] == pytest.approx(1.2309e6, rel=0.01)
    assert by_name["road"]["measurement"]["type"] == "length"
    assert by_name["well"]["measurement"]["type"] is None
    assert by_name["well"]["geometry"]["type"] == "Point"


def test_upload_shapefile_projected(client, shapefile_zip):
    r = _upload(client, "survey.zip", shapefile_zip)
    assert r.status_code == 201 and r.json()["crs"] == "EPSG:32643"
    meas = client.get(f"/api/files/{r.json()['id']}/measurements/").json()
    by_name = {f["properties"]["name"]: f["measurement"] for f in meas["features"]}
    assert by_name["plot"]["value"] == pytest.approx(20000)  # 100 x 200 m
    assert by_name["path"]["value"] == pytest.approx(500)  # 300/400 offsets -> 500 m


def test_unsupported_extension_rejected(client):
    assert _upload(client, "notes.txt", b"hello").status_code == 400


def test_missing_file_rejected(client):
    assert client.post("/api/files/", {}, format="multipart").status_code == 400


def test_corrupt_zip_marks_file_failed(client):
    r = _upload(client, "bad.zip", b"not a zip")
    assert r.status_code == 201 and r.json()["status"] == "FAILED"
    assert client.get(f"/api/files/{r.json()['id']}/measurements/").status_code == 409


def test_shapefile_without_crs_fails_cleanly(client, no_crs_shapefile_zip):
    r = _upload(client, "nocrs.zip", no_crs_shapefile_zip)
    assert r.json()["status"] == "FAILED" and "CRS" in r.json()["error"]


def test_unknown_id_404(client):
    missing = "0" * 32
    assert client.get(f"/api/files/{missing}/").status_code == 404
    assert client.get(f"/api/files/{missing}/measurements/").status_code == 404
