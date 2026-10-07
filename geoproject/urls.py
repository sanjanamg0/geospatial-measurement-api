from django.http import JsonResponse
from django.urls import include, path

urlpatterns = [
    path("api/", include("measurements.urls")),
    path("health/", lambda request: JsonResponse({"status": "ok"})),
]
