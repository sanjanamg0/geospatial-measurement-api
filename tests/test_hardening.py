import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from pyproj import CRS, Geod
from shapely.geometry import LineString, MultiPolygon, Polygon, box

from measurements.services import measure, reader
from measurements.services.measure import measure_geometry

pytestmark = pytest.mark.django_db

WGS84 = CRS.from_epsg(4326)
UTM43 = CRS.from_epsg(32643)
GEOD = Geod(ellps="WGS84")


def _upload(client, name, content):
    payload = {"file": SimpleUploadedFile(name, content)}
    return client.post("/api/files/", payload, format="multipart")


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ---- independent validation: projected result vs ellipsoidal (geodesic) result ----
AREA_SITES = [(77.0, 12.9), (-122.4, 37.8), (151.2, -33.9), (10.0, 60.0), (0.1, 0.1)]


@pytest.mark.parametrize("lon,lat", AREA_SITES)
def test_area_matches_geodesic_reference(lon, lat):
    poly = box(lon, lat, lon + 0.02, lat + 0.02)
    reference = abs(GEOD.geometry_area_perimeter(poly)[0])
    assert measure_geometry(poly, WGS84).value == pytest.approx(reference, rel=0.005)


@pytest.mark.parametrize("lon,lat", [(77.0, 12.9), (-122.4, 37.8), (151.2, -33.9), (10.0, 60.0)])
def test_length_matches_geodesic_reference(lon, lat):
    line = LineString([(lon, lat), (lon + 0.05, lat + 0.03)])
    reference = GEOD.geometry_length(line)
    assert measure_geometry(line, WGS84).value == pytest.approx(reference, rel=0.005)


# ---- invalid geometry ----
def test_bow_tie_polygon_is_repaired_and_flagged():
    bow_tie = Polygon([(0, 0), (200, 200), (200, 0), (0, 200)])
    assert bow_tie.area == pytest.approx(0)  # naive area cancels out
    m = measure_geometry(bow_tie, UTM43)
    assert m.value == pytest.approx(20000)
    assert "make_valid" in m.note


# ---- multipart and 3D ----
def test_multipolygon_area_is_sum_of_parts():
    mp = MultiPolygon([box(0, 0, 10, 10), box(100, 100, 120, 120)])
    assert measure_geometry(mp, UTM43).value == pytest.approx(100 + 400)


def test_z_coordinates_do_not_break_measurement():
    poly = Polygon([(77, 0, 5), (77.01, 0, 9), (77.01, 0.01, 7), (77, 0.01, 1)])
    assert measure_geometry(poly, WGS84).value == pytest.approx(1.2309e6, rel=0.01)


# ---- antimeridian and polar ----
def test_polygon_crossing_antimeridian():
    poly = Polygon([(179.9, 0), (180.1, 0), (180.1, 0.2), (179.9, 0.2)])
    crossing = Polygon([(179.9, 0), (-179.9, 0), (-179.9, 0.2), (179.9, 0.2)])
    reference = abs(GEOD.geometry_area_perimeter(poly)[0])
    m = measure_geometry(crossing, WGS84)
    assert m.value == pytest.approx(reference, rel=0.005)
    assert m.measured_in_crs in {"EPSG:32660", "EPSG:32601"}  # centroid sits on the zone edge


def test_polar_polygon_uses_equal_area_crs():
    poly = box(10, 86, 12, 87)
    reference = abs(GEOD.geometry_area_perimeter(poly)[0])
    m = measure_geometry(poly, WGS84)
    assert m.measured_in_crs.startswith("LAEA")
    assert m.value == pytest.approx(reference, rel=0.005)


# ---- performance ----
def test_transformers_are_cached():
    measure._transformer.cache_clear()
    for _ in range(5):
        measure_geometry(box(77, 0, 77.01, 0.01), WGS84)
    info = measure._transformer.cache_info()
    assert info.misses == 1 and info.hits == 4


# ---- upload safety ----
def test_zip_slip_archive_is_rejected(client):
    r = _upload(client, "evil.zip", _zip({"../evil.shp": b"x"}))
    assert r.json()["status"] == "FAILED" and "unsafe" in r.json()["error"]


def test_zip_with_too_many_members_is_rejected(client, monkeypatch):
    monkeypatch.setattr(reader, "MAX_ARCHIVE_MEMBERS", 1)
    r = _upload(client, "many.zip", _zip({"a.txt": b"1", "b.txt": b"2"}))
    assert r.json()["status"] == "FAILED" and "too many" in r.json()["error"]


def test_zip_expanding_too_large_is_rejected(client, monkeypatch):
    monkeypatch.setattr(reader, "MAX_UNCOMPRESSED_BYTES", 10)
    r = _upload(client, "big.zip", _zip({"a.txt": b"x" * 100}))
    assert r.json()["status"] == "FAILED" and "allowed size" in r.json()["error"]


def test_oversize_upload_rejected(client, settings, kml_bytes):
    settings.MAX_UPLOAD_MB = 0
    assert _upload(client, "survey.kml", kml_bytes).status_code == 400


def test_extracted_files_are_cleaned_up(client, shapefile_zip, settings):
    assert _upload(client, "survey.zip", shapefile_zip).json()["status"] == "COMPLETED"
    leftovers = [p for p in settings.UPLOADS_DIR.iterdir() if p.is_dir()]
    assert leftovers == []


# ---- KML layers and pagination ----
TWO_FOLDER_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
 <Folder><name>fields</name><Placemark><name>f1</name><Polygon><outerBoundaryIs>
  <LinearRing><coordinates>77,0 77.01,0 77.01,0.01 77,0.01 77,0</coordinates></LinearRing>
  </outerBoundaryIs></Polygon></Placemark></Folder>
 <Folder><name>roads</name><Placemark><name>r1</name><LineString><coordinates>
   77,0 77,0.01</coordinates></LineString></Placemark></Folder>
</Document></kml>"""


def test_kml_with_multiple_folders_reads_all_layers(client):
    body = _upload(client, "layers.kml", TWO_FOLDER_KML).json()
    assert body["status"] == "COMPLETED" and body["feature_count"] == 2


def test_measurements_are_paginated(client, kml_bytes):
    file_id = _upload(client, "survey.kml", kml_bytes).json()["id"]
    first = client.get(f"/api/files/{file_id}/measurements/?limit=2").json()
    assert first["count"] == 3 and len(first["features"]) == 2 and first["next"]
    assert [f["index"] for f in first["features"]] == [0, 1]
    rest = client.get(f"/api/files/{file_id}/measurements/?limit=2&offset=2").json()
    assert len(rest["features"]) == 1 and rest["next"] is None and rest["previous"]
