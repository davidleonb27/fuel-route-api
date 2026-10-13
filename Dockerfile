FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home app && chown -R app /app
USER app

# The station table is built from the bundled CSV at image build time, so the
# container starts ready to serve with no network access needed for geocoding.
RUN DJANGO_DEBUG=true python manage.py migrate --noinput \
    && DJANGO_DEBUG=true python manage.py load_fuel_stations \
    && DJANGO_DEBUG=true python manage.py collectstatic --noinput

ENV DJANGO_DEBUG=false \
    DJANGO_ALLOWED_HOSTS=* \
    CACHE_DIR=/app/.cache

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/')"
CMD ["gunicorn", "config.wsgi:application", "--preload", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
