import logging
import time

from django.db import DatabaseError, connections
from django.urls import get_resolver

logger = logging.getLogger(__name__)


def warm_up() -> None:
    """Pay the one-off costs (SciPy import, place and station indexes) before serving.

    Run in the gunicorn master with --preload so every forked worker inherits them.
    """
    started = time.perf_counter()
    get_resolver().resolve("/api/health/")  # imports views -> planner -> scipy

    from fuel.services.geocoding import place_index
    from fuel.services.stations import station_index

    place_index()
    try:
        stations = len(station_index())
    except DatabaseError:
        stations = 0  # not migrated yet; the first request will build it
    finally:
        connections.close_all()  # never share a DB connection across fork
    logger.info(
        "Warm-up done in %.0f ms (%d stations)", (time.perf_counter() - started) * 1000, stations
    )
