from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from fuel.views import HealthView, RoutePlanView, route_map

urlpatterns = [
    path("", RedirectView.as_view(url="/api/docs/", permanent=False)),
    path("api/v1/route-plan/", RoutePlanView.as_view(), name="route-plan"),
    path("api/v1/route-plan/map/", route_map, name="route-map"),
    path("api/health/", HealthView.as_view(), name="health"),
    # Slashless aliases: Django can't redirect a POST, so accept both spellings.
    path("api/v1/route-plan", RoutePlanView.as_view()),
    path("api/v1/route-plan/map", route_map),
    path("api/health", HealthView.as_view()),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("admin/", admin.site.urls),
]
