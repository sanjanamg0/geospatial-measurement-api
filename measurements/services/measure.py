"""CRS selection and measurement calculation.

Strategy
--------
* Geographic CRS (degrees, e.g. EPSG:4326): reproject each feature to a metric CRS
  chosen from its own centroid, then measure in metres:
    - between 80 S and 84 N  -> the UTM zone of the centroid
    - outside that band      -> a Lambert azimuthal equal-area CRS centred on the pole
  Features crossing the antimeridian are first shifted onto a continuous 0..360 range.
* Projected CRS: measure in the source CRS and report its linear unit.
* Invalid geometries (e.g. self-intersecting polygons) are repaired with make_valid
  before measuring, and the repair is reported in the note.
"""
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import shapely
from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry

AREA_TYPES = {"Polygon", "MultiPolygon"}
LENGTH_TYPES = {"LineString", "MultiLineString", "LinearRing"}
NO_MEASURE_TYPES = {"Point", "MultiPoint"}

UTM_MIN_LAT, UTM_MAX_LAT = -80.0, 84.0  # latitude band where UTM is defined


@dataclass
class Measurement:
    type: str | None = None
    value: float | None = None
    unit: str | None = None
    measured_in_crs: str | None = None
    note: str | None = None


def utm_epsg_for(lon: float, lat: float) -> int:
    zone = int((lon + 180) // 6) % 60 + 1
    return (32600 if lat >= 0 else 32700) + zone


def _unit(crs: CRS) -> str:
    name = crs.axis_info[0].unit_name if crs.axis_info else "metre"
    return "m" if name in ("metre", "meter") else name


def _unwrap_antimeridian(geom: BaseGeometry) -> BaseGeometry:
    """Shift negative longitudes by +360 when a geometry straddles the 180 meridian."""
    minx, _, maxx, _ = geom.bounds
    if maxx - minx <= 180:
        return geom

    def shift(coords: np.ndarray) -> np.ndarray:
        out = coords.copy()
        out[out[:, 0] < 0, 0] += 360.0
        return out

    return shapely.transform(geom, shift)


def _metric_crs_for(geom: BaseGeometry) -> tuple[CRS, str]:
    """Return (CRS, label) of the metric CRS used to measure a geographic geometry."""
    c = geom.centroid
    lon = ((c.x + 180.0) % 360.0) - 180.0
    if UTM_MIN_LAT <= c.y <= UTM_MAX_LAT:
        epsg = utm_epsg_for(lon, c.y)
        return CRS.from_epsg(epsg), f"EPSG:{epsg}"
    lat_0 = 90 if c.y > 0 else -90
    crs = CRS.from_proj4(
        f"+proj=laea +lat_0={lat_0} +lon_0={lon:.6f} +datum=WGS84 +units=m +no_defs"
    )
    return crs, f"LAEA(lat_0={lat_0},lon_0={lon:.2f})"


@lru_cache(maxsize=256)
def _transformer(source: CRS, target: CRS) -> Transformer:
    return Transformer.from_crs(source, target, always_xy=True)


def _project(geom: BaseGeometry, source: CRS, target: CRS) -> BaseGeometry:
    transformer = _transformer(source, target)
    return shapely.transform(
        geom, lambda c: np.column_stack(transformer.transform(c[:, 0], c[:, 1]))
    )


def measure_geometry(geom: BaseGeometry | None, source_crs: CRS) -> Measurement:
    if geom is None or geom.is_empty:
        return Measurement(note="Empty or missing geometry.")

    gtype = geom.geom_type
    if gtype in NO_MEASURE_TYPES:
        return Measurement(note="No measurement defined for points.")
    if gtype in AREA_TYPES:
        kind = "area"
    elif gtype in LENGTH_TYPES:
        kind = "length"
    else:
        return Measurement(note=f"Measurement not supported for geometry type {gtype}.")

    notes = []
    if not geom.is_valid:
        geom = shapely.make_valid(geom)
        notes.append("Invalid geometry repaired with make_valid before measuring.")

    if source_crs.is_geographic:
        geom = _unwrap_antimeridian(geom)
        target, label = _metric_crs_for(geom)
        projected = _project(geom, source_crs, target)
        unit = "m"
    else:
        target, label, projected, unit = source_crs, source_crs.to_string(), geom, _unit(source_crs)

    raw = projected.area if kind == "area" else projected.length
    return Measurement(
        type=kind,
        value=float(raw),
        unit=f"{unit}²" if kind == "area" else unit,
        measured_in_crs=label,
        note=" ".join(notes) or None,
    )
