from functools import lru_cache

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class UpstreamServiceError(Exception):
    pass


@lru_cache(maxsize=1)
def session() -> requests.Session:
    retry = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    http = requests.Session()
    http.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=10))
    http.mount("http://", HTTPAdapter(max_retries=retry, pool_maxsize=10))
    http.headers["User-Agent"] = settings.FUEL["HTTP_USER_AGENT"]
    return http


def get_json(url: str, params: dict | None = None) -> dict | list:
    try:
        response = session().get(url, params=params, timeout=settings.FUEL["HTTP_TIMEOUT_SECONDS"])
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        raise UpstreamServiceError(f"Request to {url} failed: {exc}") from exc
