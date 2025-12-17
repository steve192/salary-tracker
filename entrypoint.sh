#!/bin/bash
set -euo pipefail

if [ -n "${DJANGO_DB_PATH:-}" ]; then
	mkdir -p "$(dirname "$DJANGO_DB_PATH")"
fi

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn salary_tracker.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3}
