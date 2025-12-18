# Salary Tracker Architecture

## Stack Overview
- **Backend**: Django 5 with Django REST Framework. We rely on server-rendered templates, built-in session auth, and a single REST endpoint (`/api/salary-timeline/`) that powers the Chart.js visualization.
- **Frontend**: Pico.css base styles plus vanilla JavaScript. Chart.js 4 renders the salary timeline; no SPA or Alpine.js dependency is required.
- **Database**: SQLite persisted on a bind-mounted volume so restarts keep both data and collected static files.
- **Container**: Docker image built from `python:3.12-slim`. The entrypoint runs migrations, seeds the initial admin user when needed, executes `collectstatic`, and starts Gunicorn.

## Authentication & Accounts
- Custom `User` model uses email as the username field and adds an `is_admin` flag. The first user created automatically becomes an admin so every deployment starts with elevated access.
- Registration happens through `accounts.views.RegisterView`, which saves the user, creates a `UserPreference`, logs the user in, and redirects to the dashboard.
- Session-based authentication with CSRF protection; Django's stock login/logout views handle the rest of the flow.
- Admin-only capabilities live in the in-app Admin Portal (`/admin/`), while Django's stock admin site remains available at `/djadmin/` for low-level maintenance.

## Domain Model
| Model | Fields | Notes |
| --- | --- | --- |
| `User` | email, password, `is_admin`, `is_staff`, `is_superuser`, timestamps | Email replaces username; first account is auto-promoted to admin.
| `Employer` | FK to `User`, `name`, timestamps | Names are unique per user and power employer filtering.
| `SalaryEntry` | FK to `User` & `Employer`, `entry_type`, `effective_date`, optional `end_date`, `amount`, `notes` | `REGULAR` rows define baseline pay; `BONUS` rows require `end_date` and are amortized over their span.
| `UserPreference` | one-to-one to `User`, `currency`, `inflation_baseline_mode`, FK to `SalaryEntry` + `InflationSource` | Stores UI currency, the CPI source, and either implicit (global/per-employer/last increase) or manual baseline behavior.
| `InflationSource` | `code`, `label`, `description`, `is_active`, `available_to_users` | Global CPI feed definitions (e.g., ECB Germany). Admins can toggle availability and activity.
| `InflationRate` | FK to `InflationSource`, `period`, `index_value`, metadata JSON, `fetched_at` | Shared CPI index values per month; upserted when admins refresh a source.

## Salary Timeline & Analytics
1. Build a contiguous month range from the earliest salary `effective_date` through the latest `end_date` (or the current month if still active).
2. Track the latest active `REGULAR` entry for each month to produce the base salary line, then add any prorated `BONUS` rows for the total compensation line.
3. Emit JSON payloads containing labels, base/total series, bonus windows, and employer-switch annotations; Chart.js consumes this payload via `/api/salary-timeline/`.
4. If the user has selected an inflation source, `_inflation_projection` compares actual pay to CPI-adjusted values. Users can choose whole-history, per-employer, last increase, or manual baseline anchors via `inflation_baseline_mode`.
5. Employer summaries reuse the same CPI data to label each employer as a gain/loss/even versus inflation and surface explanatory messages when CPI is missing.

## UI & Workflows
- **Dashboard**: salary entry form with auto-create employer support, tabular history, employer-level totals, and the interactive Chart.js visualization (base vs total vs inflation).
- **Settings**: manage employers, update currency/baseline/source preferences, and review CPI coverage reports that highlight missing months per source.
- **Admin Portal**: single page for admins to refresh CPI data, toggle source availability, add new sources, and promote/demote/delete users with guardrails (cannot remove yourself or the last admin).
- **Auth pages**: Django auth templates for login/logout plus a custom registration view that immediately signs users in and sets defaults.

## Operations
- `.env.example` documents the required settings (secret key, debug flag, DB path, default admin credentials, timezone).
- Docker entrypoint orchestrates migrations, ensures at least one admin user exists, collects static files, then boots Gunicorn.
- `docker-compose.yml` exposes port 8000 and mounts a data volume for SQLite + static assets.
- Shared inflation data lives in the primary database. Admins fetch CPI updates via the portal; end users never call the remote API directly.

## Future Enhancements
- Email verification and password reset emails via Django's email backend.
- Automatic CPI fetch scheduling (Celery/cron) so admins do not need to click refresh manually.
- CSV/JSON import-export of salary history.
- Additional inflation feeds (US CPI, Euro area aggregate) and FX conversion for multi-currency tracking.
- Richer compensation types (stock grants, allowances) with dedicated visualizations.
