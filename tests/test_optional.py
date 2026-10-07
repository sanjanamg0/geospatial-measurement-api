"""Optional production features: authentication, Celery, PostgreSQL and spatial filtering."""
import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection

from geoproject import celery_app
from geoproject.settings import _database_from_url
from measurements import jobs, spatial
from measurements.models import UploadedFile

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery"
on_postgis = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="needs PostgreSQL with PostGIS"
)


def _upload(client, name, content, **extra):
    payload = {"file": SimpleUploadedFile(name, content), **extra}
    return client.post("/api/files/", payload, format="multipart")


def _register(client, username):
    r = client.post("/api/auth/register/", {"username": username, "password": PASSWORD})
    assert r.status_code == 201, r.content
    return r.json()["token"]


def _as(client, token):
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    return client


# ---------------------------------------------------------------- authentication
@pytest.fixture
def auth_required(settings):
    settings.REQUIRE_AUTH = True


def test_open_by_default_and_files_get_no_owner(client, kml_bytes):
    body = _upload(client, "s.kml", kml_bytes).json()
    assert UploadedFile.objects.get(pk=body["id"]).owner is None


def test_auth_required_rejects_anonymous_requests(client, auth_required, kml_bytes):
    assert _upload(client, "s.kml", kml_bytes).status_code == 401
    assert client.get("/api/files/").status_code == 401
    assert client.get("/api/files/" + "0" * 32 + "/").status_code == 401


def test_register_login_and_upload_with_token(client, auth_required, kml_bytes):
    token = _register(client, "alice")
    login = client.post("/api/auth/token/", {"username": "alice", "password": PASSWORD})
    assert login.status_code == 200 and login.json()["token"] == token

    _as(client, token)
    r = _upload(client, "s.kml", kml_bytes)
    assert r.status_code == 201 and r.json()["status"] == "COMPLETED"
    assert UploadedFile.objects.get(pk=r.json()["id"]).owner.username == "alice"


def test_users_only_see_their_own_files(client, auth_required, kml_bytes):
    alice = _register(client, "alice")
    bob = _register(client, "bob")
    file_id = _upload(_as(client, alice), "s.kml", kml_bytes).json()["id"]

    _as(client, bob)
    assert client.get(f"/api/files/{file_id}/").status_code == 404
    assert client.get(f"/api/files/{file_id}/measurements/").status_code == 404
    assert client.get(f"/api/files/{file_id}/export/").status_code == 404
    assert client.delete(f"/api/files/{file_id}/").status_code == 404
    assert client.get("/api/files/").json()["count"] == 0

    _as(client, alice)
    assert client.get(f"/api/files/{file_id}/").status_code == 200
    listing = client.get("/api/files/").json()
    assert listing["count"] == 1 and listing["results"][0]["id"] == file_id


def test_auth_endpoints_accept_form_encoded_and_json_bodies(client):
    form = client.post(
        "/api/auth/register/",
        f"username=formuser&password={PASSWORD}",
        content_type="application/x-www-form-urlencoded",
    )
    assert form.status_code == 201
    as_json = client.post(
        "/api/auth/register/", {"username": "jsonuser", "password": PASSWORD}, format="json"
    )
    assert as_json.status_code == 201


def test_register_validation_and_wrong_password(client):
    for weak in ("short", "password"):  # too short, and a commonly used password
        r = client.post("/api/auth/register/", {"username": "x", "password": weak})
        assert r.status_code == 400
    _register(client, "carol")
    dup = client.post("/api/auth/register/", {"username": "CAROL", "password": PASSWORD})
    assert dup.status_code == 400
    bad = client.post("/api/auth/token/", {"username": "carol", "password": "wrong-password"})
    assert bad.status_code == 400


def test_invalid_token_is_rejected_even_when_auth_is_optional(client, kml_bytes):
    client.credentials(HTTP_AUTHORIZATION="Token not-a-real-token")
    assert _upload(client, "s.kml", kml_bytes).status_code == 401


# ---------------------------------------------------------------- Celery
@pytest.fixture
def celery_eager(settings, monkeypatch):
    settings.ASYNC_BACKEND = "celery"
    settings.ASYNC_PROCESSING = True
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    monkeypatch.setattr(celery_app.conf, "task_eager_propagates", True)


def test_celery_backend_runs_task_and_file_completes(client, celery_eager, kml_bytes):
    r = _upload(client, "s.kml", kml_bytes)
    assert r.status_code == 202 and r.json()["status"] == "PENDING"  # response is pre-processing
    done = client.get(f"/api/files/{r.json()['id']}/").json()
    assert done["status"] == "COMPLETED" and done["feature_count"] == 3


def test_celery_task_is_registered_with_stable_name():
    assert "measurements.process_uploaded_file" in celery_app.tasks


def test_thread_backend_is_still_selectable(client, settings, monkeypatch, kml_bytes):
    settings.ASYNC_BACKEND = "thread"
    settings.ASYNC_PROCESSING = True
    queued = []

    class FakeExecutor:
        def submit(self, *args):
            queued.append(args)

    monkeypatch.setattr(jobs, "_executor", FakeExecutor)
    assert _upload(client, "s.kml", kml_bytes).status_code == 202
    assert len(queued) == 1


# ---------------------------------------------------------------- database settings
def test_database_url_parsing():
    cfg = _database_from_url("postgres://geo:p%40ss@db.example.com:5433/measurements")
    assert cfg["ENGINE"] == "django.db.backends.postgresql"
    assert (cfg["NAME"], cfg["USER"], cfg["PASSWORD"]) == ("measurements", "geo", "p@ss")
    assert (cfg["HOST"], cfg["PORT"]) == ("db.example.com", 5433)
    with pytest.raises(ValueError):
        _database_from_url("mysql://x@y/z")


def test_srid_from_label():
    assert spatial.srid_from_label("EPSG:4326") == 4326
    assert spatial.srid_from_label("EPSG:32643") == 32643
    assert spatial.srid_from_label("LAEA(lat_0=90)") == 0
    assert spatial.srid_from_label(None) == 0


# ---------------------------------------------------------------- bbox filtering
# Features: square (77..77.01, 0..0.01), road (x=77, y 0..0.01), well (77.005, 0.005)
def _features(client, file_id, query):
    r = client.get(f"/api/files/{file_id}/measurements/?bbox={query}")
    assert r.status_code == 200, r.content
    return r.json()


def test_bbox_filters_measurements_and_summary(client, kml_bytes):
    file_id = _upload(client, "s.kml", kml_bytes).json()["id"]
    everything = _features(client, file_id, "76.9,-1,77.1,1")
    assert everything["count"] == 3
    only_well = _features(client, file_id, "77.004,0.004,77.006,0.006")
    names = {f["properties"]["Name"] for f in only_well["features"]}
    assert names == {"square", "well"}  # the road at x=77 is outside; the square contains the well
    assert only_well["summary"]["by_geometry_type"] == {"Polygon": 1, "Point": 1}
    assert _features(client, file_id, "10,10,11,11")["count"] == 0


def test_bbox_applies_to_export(client, kml_bytes):
    file_id = _upload(client, "s.kml", kml_bytes).json()["id"]
    r = client.get(f"/api/files/{file_id}/export/?bbox=10,10,11,11")
    assert json.loads(r.content)["features"] == []
    csv_url = f"/api/files/{file_id}/export/?as=csv&bbox=10,10,11,11"
    assert len(client.get(csv_url).content.decode().strip().splitlines()) == 1  # header only


@pytest.mark.parametrize("bad", ["1,2,3", "a,b,c,d", "5,0,1,1", "0,5,1,1", ""])
def test_bbox_validation(client, kml_bytes, bad):
    file_id = _upload(client, "s.kml", kml_bytes).json()["id"]
    r = client.get(f"/api/files/{file_id}/measurements/?bbox={bad}")
    assert r.status_code == 400 and "bbox" in r.json()


L_SHAPE_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>L</name><Polygon>
<outerBoundaryIs><LinearRing><coordinates>
 0,0 10,0 10,1 1,1 1,10 0,10 0,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></Document></kml>"""
INSIDE_THE_CORNER = "5,5,9,9"  # overlaps the L's bounding box but not the L itself


def test_bbox_fallback_matches_on_bounding_box_only(client):
    if spatial.postgis_enabled():
        pytest.skip("PostGIS filters on the real shape, covered by the next test")
    file_id = _upload(client, "l.kml", L_SHAPE_KML).json()["id"]
    assert _features(client, file_id, INSIDE_THE_CORNER)["count"] == 1  # bbox overlap


@on_postgis
def test_postgis_extension_and_geom_column_exist():
    assert spatial.postgis_enabled()
    with connection.cursor() as cursor:
        cursor.execute("SELECT postgis_version()")
        assert cursor.fetchone()[0]
        cursor.execute("SELECT indexdef FROM pg_indexes WHERE indexname LIKE '%geom_gist'")
        assert "gist" in cursor.fetchone()[0].lower()


@on_postgis
def test_postgis_stores_geometries_and_filters_on_real_shape(client, kml_bytes):
    kml_id = _upload(client, "s.kml", kml_bytes).json()["id"]
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*), count(geom), min(ST_SRID(geom)) FROM measurements_feature "
            "WHERE file_id = %s", [kml_id],
        )
        assert cursor.fetchone() == (3, 3, 4326)

    l_id = _upload(client, "l.kml", L_SHAPE_KML).json()["id"]
    assert _features(client, l_id, INSIDE_THE_CORNER)["count"] == 0  # exact: misses the L
    assert _features(client, l_id, "0.5,0.5,0.6,0.6")["count"] == 1  # inside the L
    assert _features(client, l_id, "9,0.5,9.5,0.9")["count"] == 1  # on the L's foot


@on_postgis
def test_postgis_accepts_kml_with_z_coordinates(client):
    # Real KML files carry ",0" altitudes; the 2D geom column must still accept them.
    z_kml = L_SHAPE_KML.replace(b"0,0 10,0 10,1 1,1 1,10 0,10 0,0",
                                b"0,0,5 10,0,5 10,1,5 1,1,5 1,10,5 0,10,5 0,0,5")
    body = _upload(client, "z.kml", z_kml).json()
    assert body["status"] == "COMPLETED", body
    assert _features(client, body["id"], "0.5,0.5,0.6,0.6")["count"] == 1


@on_postgis
def test_postgis_filter_uses_the_spatial_index(client, kml_bytes):
    file_id = _upload(client, "s.kml", kml_bytes).json()["id"]
    with connection.cursor() as cursor:
        cursor.execute("SET enable_seqscan = off")
        cursor.execute(
            "EXPLAIN SELECT 1 FROM measurements_feature "
            "WHERE ST_Intersects(geom, ST_MakeEnvelope(77, 0, 77.1, 0.1, 4326))"
        )
        plan = "\n".join(row[0] for row in cursor.fetchall())
    assert "measurements_feature_geom_gist" in plan
    assert file_id
