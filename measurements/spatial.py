"""Spatial filtering.

Works on every database through four indexed bounding-box columns. On PostgreSQL with the
PostGIS extension it additionally keeps a real ``geom`` geometry column with a GiST index and
filters with ST_Intersects, which tests the actual shape rather than just its bounding box.
GeoDjango is not used, so installing the project still needs no system GDAL.
"""
from functools import lru_cache

from django.db import connection

from .models import Feature

BBox = tuple[float, float, float, float]


def srid_from_label(crs_label: str | None) -> int:
    """'EPSG:4326' -> 4326; anything else -> 0 (unknown SRID)."""
    if crs_label and crs_label.upper().startswith("EPSG:") and crs_label[5:].isdigit():
        return int(crs_label[5:])
    return 0


@lru_cache(maxsize=4)
def _has_geom_column(database_name: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = 'geom'",
            [Feature._meta.db_table],
        )
        return cursor.fetchone() is not None


def postgis_enabled() -> bool:
    """True when running on PostgreSQL and the migration created the geom column."""
    if connection.vendor != "postgresql":
        return False
    return _has_geom_column(connection.settings_dict["NAME"])


def store_geometries(file_id, srid: int) -> None:
    """Fill the PostGIS geom column for a file's features (no-op without PostGIS)."""
    if not postgis_enabled():
        return
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {Feature._meta.db_table} "
            "SET geom = ST_SetSRID(ST_Force2D(ST_GeomFromGeoJSON(geometry::text)), %s) "
            "WHERE file_id = %s AND geometry IS NOT NULL",
            [srid, file_id],
        )


def intersecting(queryset, bbox: BBox, srid: int):
    """Features whose geometry intersects bbox (minx, miny, maxx, maxy) in the file's CRS."""
    minx, miny, maxx, maxy = bbox
    if postgis_enabled():
        return queryset.extra(
            where=["ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, %s))"],
            params=[minx, miny, maxx, maxy, srid],
        )
    return queryset.filter(minx__lte=maxx, maxx__gte=minx, miny__lte=maxy, maxy__gte=miny)
