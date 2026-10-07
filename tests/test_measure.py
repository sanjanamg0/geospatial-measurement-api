import pytest
from pyproj import CRS
from shapely.geometry import GeometryCollection, LineString, MultiPoint, Point, Polygon

from measurements.services.measure import measure_geometry, utm_epsg_for

WGS84 = CRS.from_epsg(4326)


@pytest.mark.parametrize(
    "lon,lat,epsg",
    [(77.0, 12.9, 32643), (-122.4, 37.8, 32610), (151.2, -33.9, 32756), (179.9, 0.0, 32660)],
)
def test_utm_zone_selection(lon, lat, epsg):
    assert utm_epsg_for(lon, lat) == epsg


def test_polygon_in_degrees_is_measured_in_metres():
    # 0.01 x 0.01 degrees at the equator is about 1113 m x 1106 m.
    poly = Polygon([(77, 0), (77.01, 0), (77.01, 0.01), (77, 0.01)])
    m = measure_geometry(poly, WGS84)
    assert m.type == "area" and m.unit == "m²"
    assert m.measured_in_crs == "EPSG:32643"
    assert m.value == pytest.approx(1.2309e6, rel=0.01)


def test_linestring_length_metres():
    m = measure_geometry(LineString([(77, 0), (77, 0.01)]), WGS84)
    assert m.type == "length" and m.unit == "m"
    assert m.value == pytest.approx(1105.7, rel=0.01)


def test_projected_crs_measured_in_place():
    m = measure_geometry(Polygon([(0, 0), (100, 0), (100, 50), (0, 50)]), CRS.from_epsg(32643))
    assert m.value == pytest.approx(5000)
    assert m.measured_in_crs == "EPSG:32643"


def test_point_has_no_measurement():
    m = measure_geometry(Point(77, 0), WGS84)
    assert m.type is None and m.value is None and m.note


@pytest.mark.parametrize(
    "geom", [MultiPoint([(0, 0), (1, 1)]), GeometryCollection([Point(0, 0)]), None]
)
def test_unsupported_or_missing_geometry_does_not_crash(geom):
    m = measure_geometry(geom, WGS84)
    assert m.value is None and m.note
