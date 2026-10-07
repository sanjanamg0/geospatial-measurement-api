from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("A user with that username already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)  # AUTH_PASSWORD_VALIDATORS: minimum length, common passwords
        return value


class RegisterView(APIView):
    """Create an account and return its API token."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        request=RegisterSerializer,
        responses={
            201: inline_serializer(
                "RegisterResponse",
                {"username": serializers.CharField(), "token": serializers.CharField()},
            )
        },
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.create_user(**serializer.validated_data)
        token = Token.objects.create(user=user)
        return Response(
            {"username": user.get_username(), "token": token.key}, status=status.HTTP_201_CREATED
        )


class LoginView(ObtainAuthToken):
    """Exchange username and password for the API token."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
