from django.urls import path
from rest_framework.routers import DefaultRouter

from .auth_views import LoginView, RegisterView
from .views import FileViewSet

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("files", FileViewSet, basename="file")

urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/token/", LoginView.as_view(), name="token"),
    *router.urls,
]
