from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Feature, UploadedFile
from .services.reader import SUPPORTED_EXTENSIONS


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="A .kml file, or a .zip containing Shapefile(s).")
    method = serializers.ChoiceField(
        choices=UploadedFile.Method.choices,
        default=UploadedFile.Method.PROJECTED,
        required=False,
        help_text="projected (default): UTM/equal-area projection. geodesic: WGS84 ellipsoid.",
    )

    def validate_file(self, f):
        name = f.name.lower()
        if not any(name.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
            raise serializers.ValidationError(
                "Unsupported file type. Upload a .zip (Shapefile) or .kml file."
            )
        if f.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise serializers.ValidationError(f"File exceeds {settings.MAX_UPLOAD_MB} MB limit.")
        return f


class UploadedFileSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(format="hex")

    class Meta:
        model = UploadedFile
        fields = [
            "id", "filename", "feature_count", "crs", "status", "method", "error", "created_at",
        ]


class MeasurementSerializer(serializers.Serializer):
    type = serializers.CharField(allow_null=True, help_text="area, length, or null")
    value = serializers.FloatField(allow_null=True)
    unit = serializers.CharField(allow_null=True)
    measured_in_crs = serializers.CharField(allow_null=True)
    note = serializers.CharField(allow_null=True)


class FeatureMeasurementSerializer(serializers.ModelSerializer):
    measurement = serializers.SerializerMethodField()

    class Meta:
        model = Feature
        fields = ["index", "geometry_type", "geometry", "crs", "properties", "measurement"]

    @extend_schema_field(MeasurementSerializer)
    def get_measurement(self, obj):
        return {
            "type": obj.measurement_type,
            "value": obj.value,
            "unit": obj.unit,
            "measured_in_crs": obj.measured_in_crs,
            "note": obj.note,
        }


class MeasurementsResponseSerializer(serializers.Serializer):
    """Documentation-only: shape of GET /api/files/{id}/measurements/."""

    file_id = serializers.CharField()
    status = serializers.CharField()
    count = serializers.IntegerField(help_text="Total number of features in the file")
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    summary = serializers.DictField(
        help_text="by_geometry_type counts and totals of area/length per unit, over the whole file"
    )
    features = FeatureMeasurementSerializer(many=True)
