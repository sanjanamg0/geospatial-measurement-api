from rest_framework.routers import DefaultRouter

from .views import FileViewSet

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register("files", FileViewSet, basename="file")

urlpatterns = router.urls
