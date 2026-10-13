import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

from fuel.warmup import warm_up  # noqa: E402  (needs Django set up first)

warm_up()
