FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=studentTravelGrant_main.settings

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bake static assets into the image; WhiteNoise serves them at runtime.
RUN python manage.py collectstatic --noinput

# Cloud Run injects $PORT (8080 by default).
ENV PORT=8080
CMD exec gunicorn studentTravelGrant_main.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --workers 3 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
