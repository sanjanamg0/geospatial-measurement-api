import csv
import io
import json

from django.conf import settings
from django.db.models import Count, Sum
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from shapely.geometry import shape

from . import jobs
from .models import UploadedFile
from .serializers import (
    FeatureMeasurementSerializer,
    MeasurementsResponseSerializer,
    UploadedFileSerializer,
    UploadSerializer,
)
from .services.processor import process_file
from .services.reader import detect_type


class MeasurementPagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 1000


def _summary(record: UploadedFile) -> dict:
    """Whole-file aggregates (not just the current page)."""
    features = record.features
    by_type = {
        (gtype or "unknown"): n
        for gtype, n in features.order_by().values_list("geometry_type").annotate(n=Count("id"))
    }
    totals: dict[str, dict[str, float]] = {}
    rows = (
        features.exclude(value=None)
        .order_by()
        .values("measurement_type", "unit")
        .annotate(total=Sum("value"))
    )
    for row in rows:
        totals.setdefault(row["measurement_type"], {})[row["unit"]] = row["total"]
    return {"by_geometry_type": by_type, "totals": totals}


class FileViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    POST   /api/files/                      upload (+ process) a .zip (Shapefile) or .kml
    GET    /api/files/{id}/                 file info and processing status
    DELETE /api/files/{id}/                 delete the file, its features and the stored upload
    GET    /api/files/{id}/measurements/    per-feature measurements + summary (?limit=&offset=)
    GET    /api/files/{id}/export/          results as GeoJSON or CSV (?as=geojson|csv)
    """

    queryset = UploadedFile.objects.all()
    serializer_class = UploadedFileSerializer
    parser_classes = [MultiPartParser]

    @extend_schema(
        request={"multipart/form-data": UploadSerializer},
        responses={201: UploadedFileSerializer, 202: UploadedFileSerializer},
        description="Processes synchronously (201) or, when GEO_ASYNC=1, in the background (202).",
    )
    def create(self, request, *args, **kwargs):
        upload = UploadSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        f = upload.validated_data["file"]
        method = upload.validated_data.get("method", UploadedFile.Method.PROJECTED)

        record = UploadedFile.objects.create(
            filename=f.name, file_type=detect_type(f.name), method=method
        )
        dest = record.upload_path()
        with dest.open("wb") as out:
            for chunk in f.chunks():
                out.write(chunk)

        if settings.ASYNC_PROCESSING:
            jobs.submit(record.id, dest)
            return Response(UploadedFileSerializer(record).data, status=status.HTTP_202_ACCEPTED)

        record = process_file(record, dest)
        return Response(UploadedFileSerializer(record).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        instance.upload_path().unlink(missing_ok=True)
        instance.delete()

    def _require_completed(self, record):
        if record.status != UploadedFile.Status.COMPLETED:
            return Response(
                {"detail": f"File is {record.status}: {record.error or 'not ready'}"},
                status=status.HTTP_409_CONFLICT,
            )
        return None

    @extend_schema(
        responses={200: MeasurementsResponseSerializer},
        parameters=[
            OpenApiParameter("limit", int, description="Page size (default 100, max 1000)"),
            OpenApiParameter("offset", int, description="Number of features to skip"),
        ],
    )
    @action(detail=True, methods=["get"], url_path="measurements")
    def measurements(self, request, pk=None):
        record = self.get_object()
        if (not_ready := self._require_completed(record)) is not None:
            return not_ready
        paginator = MeasurementPagination()
        page = paginator.paginate_queryset(record.features.all(), request, view=self)
        return Response(
            {
                "file_id": record.id.hex,
                "status": record.status,
                "count": paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "summary": _summary(record),
                "features": FeatureMeasurementSerializer(page, many=True).data,
            }
        )

    @extend_schema(
        parameters=[OpenApiParameter("as", str, enum=["geojson", "csv"], default="geojson")],
        responses={(200, "application/geo+json"): dict, (200, "text/csv"): str},
        description="Download all features with their measurements. GeoJSON keeps the source CRS.",
    )
    @action(detail=True, methods=["get"], url_path="export")
    def export(self, request, pk=None):
        record = self.get_object()
        if (not_ready := self._require_completed(record)) is not None:
            return not_ready
        fmt = request.query_params.get("as", "geojson").lower()
        if fmt == "geojson":
            return self._export_geojson(record)
        if fmt == "csv":
            return self._export_csv(record)
        raise ValidationError({"as": "Must be 'geojson' or 'csv'."})

    @staticmethod
    def _measurement_fields(f) -> dict:
        return {
            "measurement_type": f.measurement_type,
            "value": f.value,
            "unit": f.unit,
            "measured_in_crs": f.measured_in_crs,
            "note": f.note,
        }

    def _export_geojson(self, record):
        body = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": record.crs}},
            "features": [
                {
                    "type": "Feature",
                    "id": f.index,
                    "geometry": f.geometry,
                    "properties": {**f.properties, **self._measurement_fields(f)},
                }
                for f in record.features.all()
            ],
        }
        resp = HttpResponse(json.dumps(body), content_type="application/geo+json")
        resp["Content-Disposition"] = f'attachment; filename="{record.id.hex}.geojson"'
        return resp

    def _export_csv(self, record):
        out = io.StringIO()
        columns = [
            "index", "geometry_type", "crs", "measurement_type", "value", "unit",
            "measured_in_crs", "note", "properties", "geometry_wkt",
        ]
        writer = csv.DictWriter(out, fieldnames=columns)
        writer.writeheader()
        for f in record.features.all():
            writer.writerow(
                {
                    "index": f.index,
                    "geometry_type": f.geometry_type,
                    "crs": f.crs,
                    **self._measurement_fields(f),
                    "properties": json.dumps(f.properties),
                    "geometry_wkt": shape(f.geometry).wkt if f.geometry else "",
                }
            )
        resp = HttpResponse(out.getvalue(), content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="{record.id.hex}.csv"'
        return resp
