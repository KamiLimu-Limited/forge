# Forge - KamiLimu Learning System

Forge is the backend REST API for the KamiLimu mentorship programme. It manages cohorts,
sessions, attendance, points and graduation, extra activities, peer mentorship,
leaderboards, notifications and analytics. It is API-only; a separate frontend consumes it.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [API documentation](#api-documentation)
- [API conventions](#api-conventions)
- [Programme rules](#programme-rules)
- [Background jobs](#background-jobs)
- [Development](#development)
- [Testing](#testing)
- [Deployment](#deployment)

## Features

| Area | What it covers |
|------|----------------|
| Authentication | Invitation-only onboarding (single, bulk JSON or CSV upload), activation, JWT access/refresh tokens with rotation and revocation, password reset, rate limiting |
| Users & admin | Profiles, account suspension, global and cohort-scoped roles, invitation management, audit trail |
| Cohorts | Cohorts with KamiLimu month boundaries, ICT tracks, skills and rating windows; enrollments with 1:1 peer mentor groups |
| Sessions | Thursday, Saturday and peer mentorship sessions; publish, reschedule (with history), cancel; mentors and resources; calendars |
| Attendance | Category-based attendance windows, submissions with feedback ratings, per-mentee override requests, automatic `missed` marking |
| Points & graduation | Core and extra points, rates by month, track and type, graduation status (`on_track`, `warning`, `at_risk`), cohort report |
| Extra activities | Academic, event, opportunity and consultation activities with typed details and committee validation |
| Peer mentorship | Encrypted private notes, ICT progress notes, group tasks with submissions and reminders |
| Skills | Early, mid and late-programme self-ratings and progress |
| Leaderboard & competitions | Six-dimension leaderboard with an anonymity toggle and CSV export; competitions, rounds and entries |
| Dashboards | Mentee, 1:1 peer mentor, ICT peer mentor, professional mentor and committee views |
| Notifications | In-app notifications for every programme event, queued email delivery with retries, broadcasts |
| Analytics & exports | Trends, track performance, session quality, health trajectory, engagement, cross-cohort comparison, daily snapshots, CSV exports |

## Requirements

- Python 3.11+
- PostgreSQL 14+ (Docker Compose provides one for development)
- Optional: a [Resend](https://resend.com) API key for email delivery

## Quick start

```bash
# 1. Install
uv venv && uv pip install -e ".[dev]"      # or: python -m venv .venv && pip install -e ".[dev]"

# 2. Start Postgres (port 5433; creates `forge` and `forge_test` databases)
docker compose up -d db

# 3. Configure
cp .env.example .env                        # defaults already point at the compose database

# 4. Migrate and create the first admin
alembic upgrade head
forge-cli create-admin --email admin@kamilimu.org --first-name Admin --last-name User

# 5. Run
uvicorn forge.main:app --reload
```

Then open http://localhost:8000/api/v1/docs.

**On NixOS**, run `nix-shell` (or `nix-shell --command fish`) first. It provides Python, uv,
ruff and the Postgres client, exposes the system libraries that prebuilt wheels such as
greenlet need, and activates `.venv`, creating it on first use.

## Configuration

All settings are environment variables (or `.env`) read by `forge.core.config.Settings`.
`.env.example` lists every one of them.

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host:port/db` | compose database |
| `SECRET_KEY` | JWT signing key (`openssl rand -hex 32`) | insecure dev value |
| `DATA_ENCRYPTION_KEY` | Fernet key for private notes; derived from `SECRET_KEY` if empty | — |
| `ACCESS_TOKEN_EXPIRE_MINUTES` / `REFRESH_TOKEN_EXPIRE_DAYS` | Token lifetimes | `60` / `7` |
| `INVITATION_TOKEN_EXPIRE_DAYS` / `PASSWORD_RESET_TOKEN_EXPIRE_HOURS` | Link lifetimes | `7` / `24` |
| `CORS_ORIGINS` | Comma-separated allowed origins | `http://localhost:3000` |
| `FRONTEND_URL` | Base URL used in email links | `http://localhost:3000` |
| `RESEND_API_KEY`, `EMAIL_FROM_ADDRESS`, `EMAIL_FROM_NAME` | Email delivery; without a key emails are skipped and logged | — |
| `SCHEDULER_ENABLED`, `SCHEDULER_INTERVAL_SECONDS` | Background jobs | `false`, `300` |
| `RATE_LIMIT_ENABLED`, `RATE_LIMIT_AUTH_TIMES`, `RATE_LIMIT_AUTH_SECONDS` | Auth endpoint rate limit | `true`, `10` per `60`s |
| `DEFAULT_GRADUATION_THRESHOLD`, `GRADUATION_WARNING_MARGIN` | Graduation rule | `80`, `5` |
| `THURSDAY_WINDOW_HOURS`, `SATURDAY_WINDOW_HOURS`, `PEER_MENTORSHIP_WINDOW_HOURS` | Attendance windows after a session ends | `24`, `48`, `72` |
| `OVERRIDE_EXTENSION_HOURS` | Default extension when an override is approved | `48` |
| `DEFAULT_SESSION_POINTS`, `EXTRA_ACTIVITY_DEFAULT_POINTS` | Points defaults | `10`, `5` per type |
| `DEFAULT_SKILL_NAMES` | Skills used when a cohort doesn't define its own | six programme skills |

## API documentation

Interactive docs are generated by FastAPI:

- Swagger UI: `/api/v1/docs` (use **Authorize** with an access token)
- ReDoc: `/api/v1/redoc`
- OpenAPI schema: `/api/v1/openapi.json`

Every endpoint is described there with its request and response schemas, permissions and
error responses. Endpoints are grouped by tag: Authentication, Users, Admin, Audit, Cohorts,
Sessions, Attendance, Mentee Progress, Extra Activities, Peer Mentorship, Skills,
Leaderboard & Competitions, Dashboards, Notifications, Analytics, Exports, Health.

### Authentication flow

```text
POST /api/v1/auth/invite            (admin)  -> email with activation link
POST /api/v1/auth/activate          {token, password} -> {access_token, refresh_token}
POST /api/v1/auth/login             {email, password} -> {access_token, refresh_token, expires_in}
     Authorization: Bearer <access_token>   on every other request
POST /api/v1/auth/refresh           {refresh_token} -> new pair; the old refresh token is revoked
POST /api/v1/auth/logout            revokes the access token (and refresh token if sent)
```

Bulk onboarding a cohort from CSV:

```bash
curl -X POST localhost:8000/api/v1/auth/bulk-invite/csv \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@cohort11.csv" -F "cohort_id=$COHORT_ID"
```

The CSV has the columns `email,first_name,last_name,roles`. Separate multiple roles with `;`.

## API conventions

- **Errors** always share one shape: `{"success": false, "error": "<code>", "detail": ...}`.
  The codes are `bad_request`, `unauthorized`, `forbidden`, `not_found`, `conflict`,
  `business_rule_violation`, `validation_error` and `rate_limited`.
- **Pagination**: list endpoints accept `page` (from 1) and `page_size` (≤ 100) and return
  `{items, total, page, page_size, total_pages}`. Unknown query parameters are rejected.
- **Rate limiting**: login, activation and reset requests are limited per client IP and return
  `429` when exceeded. The limiter is in-memory per process; with several workers, also limit at
  the reverse proxy.
- **Access control** is enforced in the API layer (it replaces the plan's Postgres RLS
  policies, since Forge uses its own JWTs and a single database role):
  - users read and write their own records;
  - 1:1 peer mentors read their group's;
  - ICT peer mentors read mentees on their track;
  - committee members manage their cohort;
  - admins can do everything.

  Roles can be global or scoped to a cohort.

## Programme rules

These defaults stand in for the PRD and are all configurable.

- **Attendance windows** open when a session starts. They close 24h (Thursday) or 48h
  (Saturday) after it ends, or at the session's explicit deadline (peer mentorship; otherwise
  the cohort or default allowance). An approved override extends the window for one mentee.
- **Counting**: a session counts for a mentee once it has started and is published or
  completed. It must also apply to the mentee: they enrolled before it started, and for an ICT
  session they're on its track.
  - `attended` earns the session's points.
  - `not_attended`, `missed` and `disputed` earn nothing.
  - `excused` sessions leave the denominator.
  - Sessions still inside their window without a submission are *upcoming* and not yet counted.
- **Combined rate** = (core points earned + approved extra-activity points) / core points
  available, capped at 100%.
- **Graduation status**:
  - `on_track` at or above threshold + margin (85% by default);
  - `warning` at or above the threshold (80%);
  - otherwise `at_risk`.

  Once a cohort is `completed` the status becomes final: `graduated` or `not_graduated`.

## Background jobs

With `SCHEDULER_ENABLED=true` the app runs these jobs every `SCHEDULER_INTERVAL_SECONDS`. A
Postgres advisory lock makes sure only one worker runs them:

1. close expired attendance windows and record `missed` attendance;
2. send window-closing reminders to mentees who haven't submitted;
3. announce launched peer-mentor tasks and send deadline reminders;
4. send weekly graduation warnings to `warning` and `at_risk` mentees;
5. deliver queued notification emails, retrying up to `NOTIFICATION_MAX_ATTEMPTS`;
6. purge expired revoked tokens;
7. take a daily analytics snapshot of each active cohort.

## Development

```text
src/forge/
  main.py            app factory: lifespan, middleware, exception handlers, docs metadata
  api/
    deps.py          DB session, auth, role dependencies (RequireRoles, AdminUser, ...)
    router.py        aggregates every router under /api/v1
    routes/          one module per domain
  core/              settings, JWT, password hashing, encryption, rate limiting, exceptions
  db/                declarative base, session factory, EncryptedText column type
  models/            SQLAlchemy models
  schemas/           Pydantic request/response models
  services/          business logic (points engine, windows, notifications, analytics, ...)
  cli.py             forge-cli create-admin
alembic/versions/    001 auth schema, 002 programme schema
tests/               unit/ and integration/ (real Postgres)
```

```bash
ruff check src tests && ruff format src tests
mypy src
```

Routes stay thin. Services raise domain exceptions (`forge.core.exceptions`), and one
exception handler turns them into the error envelope. Responses are declared with
`response_model` or return annotations and built directly from ORM objects.

## Testing

Tests run against a real PostgreSQL database. Migrations are applied once per run, and each
test runs inside a transaction that is rolled back afterwards.

```bash
docker compose up -d db                     # provides forge_test on port 5433
pytest                                      # unit + integration, with coverage
TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/forge_test pytest
```

## Deployment

The `Dockerfile` builds the API image. `docker-compose.prod.yaml` runs migrations on start
(`alembic upgrade head`), then serves with uvicorn. Set at least `DATABASE_URL`,
`SECRET_KEY`, `RESEND_API_KEY`, `FRONTEND_URL` and `CORS_ORIGINS`. `/health` is the liveness
probe and `/health/ready` checks the database.

### Render (dev)

`render.yaml` is a Render Blueprint for the dev environment: a Docker web service
(`forge-api-dev`, deploys on every push to `develop`) and a Postgres 16 database
(`forge-db-dev`), both in Frankfurt. Migrations run as the pre-deploy command, and
`DATABASE_URL` is wired from the database (plain `postgres://` URLs are converted to
`postgresql+asyncpg://` automatically).

1. In the Render dashboard choose **New → Blueprint** and select this repository.
2. Fill in the values marked "sync: false": `RESEND_API_KEY`, `FRONTEND_URL`,
   `CORS_ORIGINS` and `DATA_ENCRYPTION_KEY`. Generate the encryption key with
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   and keep it; private notes can't be decrypted without it.
3. After the first deploy, open **Shell** on the service and run
   `forge-cli create-admin --email … --first-name … --last-name …`.

## License

Proprietary - KamiLimu. For support contact support@kamilimu.org.
