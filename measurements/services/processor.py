"""Orchestrates: read file -> extract features -> measure -> persist."""
import json
import logging
import time
from pathlib import Path

import geopandas as gpd
from django.db import transaction
from shapely.geometry import mapping

from measurements.models import Feature, UploadedFile
from measurements.services.errors import ProcessingError
from measurements.services.measure import measure_geometry
from measurements.services.reader import read_geofile

log = logging.getLogger(__name__)
Status = UploadedFile.Status


def _crs_label(crs) -> str:
    epsg = crs.to_epsg()
    return f"EPSG:{epsg}" if epsg else crs.to_string()


def _build_features(gdf: gpd.GeoDataFrame, file_id, method: str) -> list[Feature]:
    crs = gdf.crs
    label = _crs_label(crs)
    props = json.loads(
        gdf.drop(columns=gdf.geometry.name).to_json(orient="records", date_format="iso")
    )
    features = []
    for i, geom in enumerate(gdf.geometry):
        m = measure_geometry(geom, crs, method)
        features.append(
            Feature(
                file_id=file_id,
                index=i,
                geometry_type=None if geom is None else geom.geom_type,
                geometry=None if geom is None or geom.is_empty else mapping(geom),
                crs=label,
                properties=props[i],
                measurement_type=m.type,
                value=m.value,
                unit=m.unit,
                measured_in_crs=m.measured_in_crs,
                note=m.note,
            )
        )
    return features


def process_file(record: UploadedFile, path: Path) -> UploadedFile:
    started = time.perf_counter()
    record.status = Status.PROCESSING
    record.save(update_fields=["status"])
    try:
        gdf = read_geofile(path, record.file_type)
        features = _build_features(gdf, record.id, record.method)
        with transaction.atomic():
            Feature.objects.bulk_create(features, batch_size=500)
        record.crs = _crs_label(gdf.crs)
        record.feature_count = len(features)
        record.status = Status.COMPLETED
    except ProcessingError as exc:
        record.status, record.error = Status.FAILED, str(exc)
    except Exception:
        log.exception("Unexpected failure processing file %s", record.id)
        record.status, record.error = Status.FAILED, "Internal error while processing file."
    record.save()
    log.info(
        "Processed file %s (%s): status=%s features=%d duration_ms=%.0f",
        record.id, record.file_type, record.status, record.feature_count,
        (time.perf_counter() - started) * 1000,
    )
    return record
