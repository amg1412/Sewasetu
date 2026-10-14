# Sewa Setu — Old Age Pension Portal

Sewa Setu is a web portal for applying to and administering the Purvanchal Old Age Pension Scheme. It includes a citizen application journey, application status access, and a staff review dashboard.

## Features

### For applicants

- Verify a mobile number with a one-time password (OTP).
- Submit a six-step application with personal, address, and bank details.
- Upload age proof as a JPG or PDF (up to 5 MB), then accept the declaration and submit.
- Sign in later with the registered mobile number and password to view the application and download its acknowledgment PDF.
- Reset a forgotten status-portal password through mobile OTP verification.

### For staff

- View application totals by status, pending applications past the service deadline, and pending cases by block.
- Browse and review applications by status; approve or reject pending cases.
- Run the scheduled deemed-approval process for applications past the statutory processing period. Use its dry-run mode to preview the number of affected cases before a backfill.

## Run locally

Requirements: Docker Compose, a `.env` file, and the seed SQL file (not included in Git).

```bash
cp .env.example .env
# Set unique SS_SECRET_KEY, SS_ADMIN_PASSWORD, and POSTGRES_PASSWORD values in .env
mkdir -p seed
# Place the supplied seed.sql at seed/seed.sql
docker compose up --build
```

- Portal: http://localhost:8000
- Simulated SMS gateway: http://localhost:8000/__gateway/ (used to inspect OTP messages in this demo)
- PostgreSQL runs on the private Compose network and is not published to the host.

## Deployment

Live portal: http://172.198.60.114:8000/

The portal runs on an Ubuntu Azure VM with Docker Compose. Only the web app is exposed on port 8000; PostgreSQL and the simulated SMS service run in the Compose network. The seed file and deployment `.env` are kept on the VM and excluded from Git. See [docs/DEPLOY.md](docs/DEPLOY.md) for deployment steps.

## Project layout

- `app/` — Flask application, templates, database schema, migrations, and scheduled job.
- `smsgw/` — simulated SMS gateway used for OTP delivery in the demo.
- `seed/seed.sql` — local/deployment seed data; intentionally not tracked.
- `tests/` — regression tests for application fixes.
- `docs/DECISIONS.md` — findings, fixes, and known limitations.

To run the regression tests, install `requirements-dev.txt`, start a PostgreSQL database with the test schema, then run:

```bash
SS_DB_HOST=localhost pytest tests/
```

## Deployment notes

Seed data and operational logs may contain personal or sensitive information; keep them out of public repositories. The SMS gateway proxy displays OTP messages for this demo; restrict access or remove it before a real public deployment. The application is a project handover, not a production-ready government service.
