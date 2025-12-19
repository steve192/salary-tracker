# Salary Tracker

A lightweight Django web application for tracking salary history across multiple employers. You can log raises and bonuses, visualize trends, compare your salary to inflation and keep track on all of that

![Manual approval screen](docs/salary-tracker.png)
![Salary negotiation support](docs/salary-negotiation.png)
## Features
- Employer management and salary entries (regular raises + time-bound bonuses).
- Compare salary development to inflation (ECB HICP data for every EU member state)

## Quick Start (Docker)
1. Copy the sample environment file and adjust values:
   ```bash
   cp .env.example .env
   ```
   Set a strong `DJANGO_SECRET_KEY`

2. Build and run the container:
   ```bash
   docker compose up --build
   ```

3. Open http://localhost:8000 and log create your initial user. 

5. Go to admin settings and add an inflation index. Data will download automatically.
6. Go to your personal settings and apply the inflation index you just added
6. Add employers and salary entries from the dashboard. The chart updates immediately based on the stored data.

## Ready to use docker-compose 
```
services:
  web:
    image: ghcr.io/steve192/salary-tracker
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      DJANGO_DB_PATH: /app/data/db.sqlite3
    volumes:
      - sqlite-data:/app/data
    restart: unless-stopped

volumes:
  sqlite-data:
```

Make sure you also use the .env.example (copy it to .env and populate the settings)

### Useful Docker Environment Variables
| Variable | Description | Default |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Secret key for Django session signing—always override in production. | `insecure-change-me` |
| `DJANGO_DEBUG` | Enables Django debug features and auto-reload; keep `false` in production. | `false` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames accepted when `DJANGO_DEBUG=false`. | `*` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | HTTPS origins allowed for CSRF-protected requests (needed behind reverse proxies). | unset |
| `DJANGO_TIME_ZONE` | Forces backend timezone; falls back to the host timezone if unset. | system tz |
| `DJANGO_DB_PATH` | SQLite path; Compose defaults to `/app/data/db.sqlite3` for persistence. | `<project>/db.sqlite3` |
| `DJANGO_FORCE_SCRIPT_NAME` | URL prefix when hosting under a sub-path (e.g., `/salary`). | unset |
| `DJANGO_STATIC_URL` | Static asset base URL; override for CDNs or when `DJANGO_FORCE_SCRIPT_NAME` is set. | derived |
| `DJANGO_MEDIA_URL` | Media asset base URL; override for CDNs or when `DJANGO_FORCE_SCRIPT_NAME` is set. | derived |
| `DJANGO_LOG_LEVEL` | Console logging verbosity (`DEBUG`, `INFO`, etc.). | `INFO` |
| `DJANGO_ALLOW_SELF_REGISTRATION` | Enables the public `/accounts/register/` form; keep `false` to require admins to onboard users manually. | `false` |
| `GUNICORN_WORKERS` | Gunicorn worker process count. | `3` |

## Local Development (without Docker)
```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env  # adjust values as needed
python manage.py migrate
python manage.py runserver
```

During local development you can leave `DJANGO_DB_PATH` unset to keep the SQLite file at the project root. Static assets are served via Django + Whitenoise, so no extra tooling is needed.
