# Claude Analytics Dashboard

Read-only Streamlit dashboard for the `claude_analytics` Postgres database —
multi-app revenue and experiment tracker.

## What it shows

- **Due for recheck** across all apps (action items shipped + waiting for review)
- **Action items** per app (status, priority, recheck dates, outcomes)
- **Funnel snapshots** per app (point-in-time before/after comparisons)
- **Insights** per app (historical findings, categorized)

## Architecture

- Streamlit web app in a single Python file (`app.py`)
- Connects to Postgres on the `coolify` Docker network
- Read-only access (no write UI by design — keeps things safe and simple)

## Deploy via Coolify

1. New Resource → Public Git Repository → paste this repo's URL
2. Build Pack: **Dockerfile**
3. Network: **coolify** (so it can reach the Postgres container by name)
4. Environment variables (set in Coolify UI):
   - `DB_HOST` — Postgres container name (e.g. `jo0c0k0kg4g8okko4ks48g8g`)
   - `DB_PORT` — `5432`
   - `DB_NAME` — `claude_analytics`
   - `DB_USER` — `postgres`
   - `DB_PASS` — Postgres password
   - `DASH_PASSWORD` — gate password for the dashboard
5. Port: `8501`
6. Set the FQDN to your subdomain (e.g. `dash.example.com`) — Coolify
   handles SSL via Let's Encrypt automatically.
7. Add a DNS A record at your registrar pointing the subdomain at the
   server's public IP.

## Local dev

```bash
docker compose up --build
```

Set environment variables in a `.env` file (gitignored). Visit
`http://localhost:8501`.
