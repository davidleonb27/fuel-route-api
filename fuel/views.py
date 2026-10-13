import logging
from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import FuelStation
from .serializers import RoutePlanRequestSerializer, RoutePlanResponseSerializer
from .services.geocoding import GeocodingError
from .services.optimizer import InfeasibleRouteError
from .services.planner import PlanOptions, build_plan, detailed_route_geometry
from .services.routing import NoRouteError, RoutingError

logger = logging.getLogger(__name__)


class Unprocessable(APIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = "unprocessable"


class UpstreamUnavailable(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "upstream_unavailable"


def run_plan(data) -> tuple[dict, dict]:
    serializer = RoutePlanRequestSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    params = serializer.validated_data
    options = PlanOptions(
        params["corridor_miles"], params["initial_fuel_gallons"], params["stop_cost"]
    )
    try:
        plan = build_plan(params["start"], params["finish"], options)
    except GeocodingError as exc:
        raise ValidationError({"detail": str(exc)}) from exc
    except (InfeasibleRouteError, NoRouteError) as exc:
        raise Unprocessable(str(exc)) from exc
    except RoutingError as exc:
        logger.warning("Routing failed: %s", exc)
        raise UpstreamUnavailable(str(exc)) from exc
    return plan, params


EXAMPLE_REQUEST = {"start": "New York, NY", "finish": "Los Angeles, CA"}


class RoutePlanView(APIView):
    """Plan a route between two US locations with the cheapest fuel stops."""

    @extend_schema(
        parameters=[RoutePlanRequestSerializer],
        responses=RoutePlanResponseSerializer,
        summary="Plan route and fuel stops (query string)",
    )
    def get(self, request):
        return self._respond(request, request.query_params)

    @extend_schema(
        request=RoutePlanRequestSerializer,
        responses=RoutePlanResponseSerializer,
        summary="Plan route and fuel stops (JSON body)",
        examples=[OpenApiExample("Coast to coast", value=EXAMPLE_REQUEST, request_only=True)],
    )
    def post(self, request):
        return self._respond(request, request.data)

    def _respond(self, request, data):
        plan, params = run_plan(data)
        query = {"start": params["start"], "finish": params["finish"]}
        for optional in ("corridor_miles", "initial_fuel_gallons", "stop_cost"):
            if optional in data:
                query[optional] = params[optional]
        map_url = request.build_absolute_uri(f"{reverse('route-map')}?{urlencode(query)}")
        return Response({**plan, "map_url": map_url})


class HealthView(APIView):
    """Liveness plus a readiness hint: are fuel stations loaded?"""

    throttle_classes: list = []

    @extend_schema(summary="Health check", responses={200: dict})
    def get(self, request):
        located = FuelStation.objects.filter(latitude__isnull=False).count()
        return Response(
            {"status": "ok" if located else "no_stations_loaded", "stations": located},
            status=status.HTTP_200_OK if located else status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def route_map(request):
    """HTML map of the same plan; reuses the cached plan, so no extra routing call."""
    try:
        plan, _ = run_plan(request.GET)
    except APIException as exc:
        return render(request, "fuel/map.html", {"error": exc.detail}, status=exc.status_code)
    if detailed := detailed_route_geometry(plan):
        line = plan["geojson"]["features"][0]
        plan["geojson"]["features"][0] = {
            **line,
            "geometry": {**line["geometry"], "coordinates": detailed},
        }
    return render(request, "fuel/map.html", {"plan": plan})
