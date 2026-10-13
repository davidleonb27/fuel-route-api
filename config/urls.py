from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from fuel.views import RoutePlanView, route_map

urlpatterns = [
    path("", RedirectView.as_view(url="/api/docs/", permanent=False)),
    path("api/v1/route-plan/", RoutePlanView.as_view(), name="route-plan"),
    path("api/v1/route-plan/map/", route_map, name="route-map"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("admin/", admin.site.urls),
]
