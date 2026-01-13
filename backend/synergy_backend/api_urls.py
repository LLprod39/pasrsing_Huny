from __future__ import annotations

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.api import StudentViewSet
from apps.billing.api import StripeCheckoutSessionCreateView, StripeWebhookView
from apps.jobs.api import JobViewSet
from apps.synergy.api import MaterialViewSet


class HealthView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request):
        return Response({"status": "ok"})


router = DefaultRouter()
router.register(r"students", StudentViewSet, basename="student")
router.register(r"jobs", JobViewSet, basename="job")
router.register(r"materials", MaterialViewSet, basename="material")


urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("billing/stripe/checkout-session/", StripeCheckoutSessionCreateView.as_view(), name="stripe_checkout_session"),
    path("billing/stripe/webhook/", StripeWebhookView.as_view(), name="stripe_webhook"),
    path("", include(router.urls)),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]

