import io
import zipfile

import geopandas as gpd
import pytest
from rest_framework.test import APIClient
from shapely.geometry import LineString, Point, box

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>square</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
    77.0,0.0 77.01,0.0 77.01,0.01 77.0,0.01 77.0,0.0
  </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  <Placemark><name>road</name><LineString><coordinates>
    77.0,0.0 77.0,0.01
  </coordinates></LineString></Placemark>
  <Placemark><name>well</name><Point><coordinates>77.005,0.005</coordinates></Point></Placemark>
</Document></kml>
"""


@pytest.fixture(autouse=True)
def isolated_uploads(settings, tmp_path):
    settings.UPLOADS_DIR = tmp_path / "uploads"
    settings.UPLOADS_DIR.mkdir()


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def kml_bytes() -> bytes:
    return KML.encode()


def _zip_dir(directory) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in directory.iterdir():
            zf.write(p, p.name)
    return buf.getvalue()


@pytest.fixture
def shapefile_zip(tmp_path) -> bytes:
    """Projected (EPSG:32643) shapefile: a 100x200 m rectangle and a 500 m line."""
    src = tmp_path / "shp"
    src.mkdir()
    # A shapefile holds one geometry type, so use two layers in one archive.
    gpd.GeoDataFrame({"name": ["plot"]}, geometry=[box(500000, 0, 500100, 200)], crs=32643).to_file(
        src / "plots.shp"
    )
    gpd.GeoDataFrame(
        {"name": ["path"]}, geometry=[LineString([(500000, 0), (500300, 400)])], crs=32643
    ).to_file(src / "paths.shp")
    return _zip_dir(src)


@pytest.fixture
def no_crs_shapefile_zip(tmp_path) -> bytes:
    src = tmp_path / "nocrs"
    src.mkdir()
    gpd.GeoDataFrame({"name": ["a"]}, geometry=[Point(1, 1)]).to_file(src / "nocrs.shp")
    return _zip_dir(src)
