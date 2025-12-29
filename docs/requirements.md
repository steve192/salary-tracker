# Salary Tracker – Implemented Requirements

## Core Application
- Multi-tenant SaaS: every signed-up user owns their employers, salary entries, and preferences.
- Custom email-based `User` model with `is_admin` flag; first registered user becomes an admin automatically.
- Employers are stored separately so entries can reuse them; duplicates per user are prevented.
- Salary entries support `REGULAR` and `BONUS` types, optional `end_date`, notes, and automatic validation (bonus rows must have an end date, `end_date` cannot precede `effective_date`).
- `UserPreference` stores currency, inflation baseline mode (whole history, per-employer, last increase, manual), the selected shared inflation source, and (for manual mode) the chosen baseline entry.

## Dashboard Experience
- Quick salary entry form with autocomplete-style employer field that creates missing employers on the fly.
- Table of existing entries with delete controls and context about effective/end dates.
- Chart.js visualization showing base vs total compensation, bonus window annotations, employer-switch callouts, and inflation-adjusted projections when enabled.
- Employer summary cards/tables compare actual earned compensation versus inflation-adjusted targets with gain/loss badges.

## Settings & Insights
- Manage employers (create/delete) and update user preferences from a single page.
- View inflation summary cards (coverage range, last fetch timestamp, record counts) for each shared source.
- Gap report highlights missing CPI months across the range of the user’s salary history so admins know when data refresh is required.

## Inflation & Admin Capabilities
- CPI data is stored globally per `InflationSource`; users merely select which shared source to consume.
- Admin Portal (`/admin/`) allows admins to refresh CPI data with one click, toggle source availability, add new sources, and mark them active/inactive.
- Admin Portal also provides user management controls (promote/demote admins, delete accounts with guardrails).
- CPI refresh flow upserts records and auto-enables `available_to_users` so users can immediately opt in to newly populated sources.

## Technical & Deployment
- Django 6 + DRF backend, SQLite persistence, Pico.css + vanilla JS frontend, Chart.js 4 for charts.
- Docker image based on `python:3.12-slim`; entrypoint applies migrations, ensures an admin exists, collects static assets, and boots Gunicorn.
- `.env.example` documents secrets, DB path, debug flag, timezone, and initial admin credentials; `docker-compose.yml` maps port 8000 and persists the SQLite database.
