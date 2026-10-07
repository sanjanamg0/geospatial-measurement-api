from django.conf import settings
from rest_framework.permissions import BasePermission


class AuthIfRequired(BasePermission):
    """Open access unless GEO_REQUIRE_AUTH=1, then a valid token is mandatory.

    Read at request time (not import time) so it can be toggled in tests.
    """

    def has_permission(self, request, view):
        if not settings.REQUIRE_AUTH:
            return True
        return bool(request.user and request.user.is_authenticated)
