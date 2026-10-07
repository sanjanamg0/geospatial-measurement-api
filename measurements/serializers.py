from django.conf import settings
from rest_framework import serializers

from .models import Feature, UploadedFile
from .services.reader import SUPPORTED_EXTENSIONS


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()

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
        fields = ["id", "filename", "feature_count", "crs", "status", "error", "created_at"]


class FeatureMeasurementSerializer(serializers.ModelSerializer):
    measurement = serializers.SerializerMethodField()

    class Meta:
        model = Feature
        fields = ["index", "geometry_type", "geometry", "crs", "properties", "measurement"]

    def get_measurement(self, obj):
        return {
            "type": obj.measurement_type,
            "value": obj.value,
            "unit": obj.unit,
            "measured_in_crs": obj.measured_in_crs,
            "note": obj.note,
        }
