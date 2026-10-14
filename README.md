# Sewa Setu — Old Age Pension Portal

Handover copy. Vendor maintenance contract ended 31/01/2026.

## Running

```
docker compose up --build
```

- Portal: http://localhost:8000
- SMS gateway console (simulated telecom): http://localhost:8000/__gateway/ —
  "sent" OTPs appear here once delivered. The gateway runs on the internal
  network and is served through the portal, so only one port is exposed.
- Database: Postgres, loaded from `seed/seed.sql` on first boot

## Deployment

Live portal: http://172.198.60.114:8000/

The portal is hosted on an Ubuntu Azure VM with Docker Compose. The app is
available on port 8000; Postgres and the simulated SMS gateway run inside the
Compose network. The seed file and deployment `.env` stay on the VM and are
excluded from Git. See `docs/DEPLOY.md` for deployment steps.

Production server logs (Jan–Jun 2026) are provided in `logs/`.

Listen to `dc-briefing.mp3` first (the DC's briefing), then read `BRIEF.md`.


---
Fellow notes: see `docs/DECISIONS.md` (findings and fixes), `docs/DEPLOY.md` (how to run it), `tests/` (`SS_DB_HOST=localhost pytest tests/`).
