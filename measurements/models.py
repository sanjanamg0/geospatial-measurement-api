import uuid

from django.conf import settings
from django.db import models


class UploadedFile(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        PROCESSING = "PROCESSING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    class Method(models.TextChoices):
        PROJECTED = "projected"
        GEODESIC = "geodesic"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="geo_files",
    )
    filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=16)  # "shapefile" | "kml"
    method = models.CharField(max_length=16, choices=Method.choices, default=Method.PROJECTED)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    crs = models.CharField(max_length=64, null=True, blank=True)
    feature_count = models.PositiveIntegerField(default=0)
    error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def upload_path(self):
        suffix = ".zip" if self.file_type == "shapefile" else ".kml"
        return settings.UPLOADS_DIR / f"{self.id.hex}{suffix}"


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

    # Bounding box of the geometry in the source CRS (used by ?bbox= filtering)
    minx = models.FloatField(null=True, blank=True)
    miny = models.FloatField(null=True, blank=True)
    maxx = models.FloatField(null=True, blank=True)
    maxy = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["index"]
        constraints = [
            models.UniqueConstraint(fields=["file", "index"], name="unique_feature_index_per_file")
        ]
        indexes = [
            models.Index(fields=["file", "minx", "maxx", "miny", "maxy"], name="feature_bbox_idx")
        ]
