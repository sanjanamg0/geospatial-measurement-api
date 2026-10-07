from django.conf import settings
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from .models import UploadedFile
from .serializers import (
    FeatureMeasurementSerializer,
    UploadedFileSerializer,
    UploadSerializer,
)
from .services.processor import process_file
from .services.reader import detect_type


class MeasurementPagination(LimitOffsetPagination):
    default_limit = 100
    max_limit = 1000


class FileViewSet(
    mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """
    POST /api/files/                      upload + process a .zip (Shapefile) or .kml
    GET  /api/files/{id}/                 file info and processing status
    GET  /api/files/{id}/measurements/    per-feature measurements (?limit=&offset=)
    """

    queryset = UploadedFile.objects.all()
    serializer_class = UploadedFileSerializer
    parser_classes = [MultiPartParser]

    def create(self, request, *args, **kwargs):
        upload = UploadSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        f = upload.validated_data["file"]

        record = UploadedFile.objects.create(filename=f.name, file_type=detect_type(f.name))
        suffix = ".zip" if record.file_type == "shapefile" else ".kml"
        dest = settings.UPLOADS_DIR / f"{record.id.hex}{suffix}"
        with dest.open("wb") as out:
            for chunk in f.chunks():
                out.write(chunk)

        record = process_file(record, dest)
        return Response(UploadedFileSerializer(record).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="measurements")
    def measurements(self, request, pk=None):
        record = self.get_object()
        if record.status != UploadedFile.Status.COMPLETED:
            return Response(
                {"detail": f"File is {record.status}: {record.error or 'not ready'}"},
                status=status.HTTP_409_CONFLICT,
            )
        paginator = MeasurementPagination()
        page = paginator.paginate_queryset(record.features.all(), request, view=self)
        return Response(
            {
                "file_id": record.id.hex,
                "status": record.status,
                "count": paginator.count,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
                "features": FeatureMeasurementSerializer(page, many=True).data,
            }
        )
