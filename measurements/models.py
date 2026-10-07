import uuid

from django.db import models


class UploadedFile(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        PROCESSING = "PROCESSING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=16)  # "shapefile" | "kml"
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    crs = models.CharField(max_length=64, null=True, blank=True)
    feature_count = models.PositiveIntegerField(default=0)
    error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Feature(models.Model):
    file = models.ForeignKey(UploadedFile, on_delete=models.CASCADE, related_name="features")
    index = models.PositiveIntegerField()
    geometry_type = models.CharField(max_length=32, null=True, blank=True)
    geometry = models.JSONField(null=True, blank=True)  # GeoJSON in the source CRS
    crs = models.CharField(max_length=64, null=True, blank=True)
    properties = models.JSONField(default=dict)

    # Measurement result
    measurement_type = models.CharField(max_length=16, null=True, blank=True)  # area | length
    value = models.FloatField(null=True, blank=True)
    unit = models.CharField(max_length=16, null=True, blank=True)
    measured_in_crs = models.CharField(max_length=64, null=True, blank=True)
    note = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["index"]
        constraints = [
            models.UniqueConstraint(fields=["file", "index"], name="unique_feature_index_per_file")
        ]
