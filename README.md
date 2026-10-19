# MtaaMove — Phase 1 security implementation

MtaaMove is a Kenyan moving-services marketplace with a React/TypeScript frontend and a FastAPI API. This phase adds customer authentication, private booking ownership, session security, and admin authorization while retaining the existing quote calculator and demo provider list.

## Audit summary and existing limitations

The starter used a single FastAPI module, SQLAlchemy, SQLite locally, and a Render-managed PostgreSQL database in the deployment blueprint. The original booking list/detail/cancel routes were public. There was no user model, authentication, or migration framework. The original README and source identify provider data as demo-only and estimates as illustrative, not route-distance based.

Security changes in this package:
- Customer registration and login with Argon2id password hashing using `argon2-cffi`.
- Opaque random session tokens stored only as SHA-256 hashes in the database; HttpOnly session cookie; 12-hour expiry by default; logout revocation.
- CSRF double-submit validation bound to the active server-side session for authenticated state-changing requests.
- Public registration always creates the `customer` role; admin-only booking listing is protected on the backend.
- Booking creation derives the customer's name, phone and owner ID from the authenticated account, not the request payload.
- Booking listing is scoped to the current customer; unauthorized cross-customer detail/cancel requests return 404.
- Additive, repeatable migration that adds user/session tables and a nullable `bookings.user_id` without guessing ownership of historical records.
- Process-local login throttling (10 attempts per IP per minute), input validation, exact-origin CORS configuration, test coverage, and a React account/booking-history UI.

## Known limitations

- The login throttle is process-local. For a multi-instance or high-traffic production service, replace it with a shared Redis-backed rate limiter.
- Password reset email delivery is not configured. Password change is available to an authenticated user; no reset email is claimed to be sent.
- Historical bookings keep `user_id = NULL` until an administrator reconciles them through a separately reviewed process. Customers cannot see these legacy records.
- Provider accounts, provider verification, live dispatch, route-distance pricing, SMS, online payments, and audit-event retention remain outside Phase 1.
- Administrators can list all bookings. Additional admin actions should be introduced only with explicit permissions and audit logging.
- The existing provider list is demo data and must not be presented as verified movers.
- Before production launch, consider account lockout policy, shared rate limiting, security monitoring, email verification, data retention rules, and an external security review.

## Prerequisites

- Python 3.11+
- Node.js 20+
- A supported database URL (SQLite locally; PostgreSQL for the Render production database)

## Local setup (PowerShell)

### 1. Backend

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

For a fresh local database, the migration command creates the schema. If you already have a local SQLite database, back it up first; the migration is additive.

```powershell
Copy-Item .\mtaamove.db .\mtaamove.db.backup -ErrorAction SilentlyContinue
python -m app.migrate
uvicorn app.main:app --reload --port 8000
```

If this is a brand-new checkout, `mtaamove.db` may not exist before migration; that is expected. The `.env` file should contain a local SQLite `DATABASE_URL` and `CORS_ORIGINS=http://localhost:5173`.

### 2. Frontend (second terminal)

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open the Vite URL shown in the terminal (normally `http://localhost:5173`). The API defaults to `http://localhost:8000`.

## Authentication and API behavior

Authentication uses a server-side session stored in the database. The browser receives a random session token in an HttpOnly cookie and a separate CSRF cookie. Do not move session tokens into localStorage or log cookie values. In production the session cookie is `Secure` and `SameSite=Lax`.

| Method | Endpoint | Access |
|---|---|---|
| `GET` | `/health`, `/ready` | Public health checks |
| `POST` | `/api/v1/quotes` | Public estimate |
| `GET` | `/api/v1/providers` | Public demo provider list |
| `POST` | `/api/v1/auth/register` | Public registration; always creates a customer |
| `POST` | `/api/v1/auth/login` | Public login |
| `GET` | `/api/v1/auth/me` | Authenticated user |
| `POST` | `/api/v1/auth/logout` | Authenticated session + `X-CSRF-Token` |
| `POST` | `/api/v1/auth/change-password` | Authenticated session + `X-CSRF-Token` |
| `POST` | `/api/v1/bookings` | Authenticated customer + `X-CSRF-Token` |
| `GET` | `/api/v1/bookings` | Customer's own bookings; admin sees all |
| `GET` | `/api/v1/bookings/{booking_id}` | Owner or admin |
| `POST` | `/api/v1/bookings/{booking_id}/cancel` | Owner or admin + `X-CSRF-Token` |
| `GET` | `/api/v1/admin/bookings` | Admin only |

The React frontend sends credentials with requests and reads the CSRF cookie to populate `X-CSRF-Token` for state-changing operations. When using another frontend, implement the same behavior and configure `CORS_ORIGINS` to the exact frontend origin(s), with no wildcard when credentials are enabled.

Registration requires a valid email, full name, phone number, and password of at least 12 characters plus confirmation. Login failures use a generic error. Passwords and session tokens are never returned by the API.

## Create the first administrator

Run this only against the intended database after the migration has completed. It creates or promotes the account matching `ADMIN_EMAIL`; keep credentials private and use a unique password of at least 12 characters.

PowerShell example:

```powershell
$env:ADMIN_EMAIL = "admin@example.com"
$env:ADMIN_FULL_NAME = "MtaaMove Administrator"
$env:ADMIN_PHONE = "0712345678"
$env:ADMIN_PASSWORD = Read-Host "Enter a unique admin password" -AsSecureString
$env:ADMIN_PASSWORD = [System.Net.NetworkCredential]::new("", $env:ADMIN_PASSWORD).Password
python -m app.create_admin
Remove-Item Env:ADMIN_EMAIL, Env:ADMIN_FULL_NAME, Env:ADMIN_PHONE, Env:ADMIN_PASSWORD
```

Do not place the administrator password in source code, a committed `.env` file, shell history, or a public issue. For production, run the bootstrap command as a one-off command with secrets supplied through the hosting platform's secure shell/secret facility.

## Database migration, backup and rollback

The migration is idempotent and additive, but any production schema change requires an approved backup and maintenance plan.

1. Verify the production `DATABASE_URL` points to the intended database without printing its value.
2. Take a database backup using Render's supported backup/export procedure.
3. Restore that backup into a separate test database and run the migration there first.
4. Run `python -m app.migrate` once against the approved production database as a controlled one-off command, not from the web-server startup command.
5. Verify `/ready`, registration/login, and booking ownership with test accounts only.
6. If a problem occurs, stop further writes if necessary and restore the backup using the database provider's documented recovery procedure. Do not drop the new tables or remove the ownership column blindly; they may contain newly created accounts and bookings. Prefer a forward fix, or restore the pre-migration backup only with an explicit data-loss assessment.

The migration preserves existing bookings and leaves their owner unset. Do not attach legacy bookings to an account based only on matching names or phone numbers.

## Tests and build checks

From `backend` with the virtual environment active:

```powershell
pytest -q
```

Frontend production build:

```powershell
cd frontend
npm install
npm run build
```

Tests use an isolated in-memory SQLite database and do not connect to the production database.

## Render rollout

1. Review `render.yaml` and confirm the actual API service, frontend origin, and production database.
2. Set `DATABASE_URL`, `CORS_ORIGINS`, `ENVIRONMENT=production`, and session settings in Render. `CORS_ORIGINS` must contain the exact deployed frontend origin.
3. Deploy the code to a staging service or test environment first.
4. Back up the production database and run `python -m app.migrate` as a controlled one-off command.
5. Create the first admin using the documented one-off procedure.
6. Run smoke tests using test accounts. Confirm anonymous booking endpoints return `401`, cross-account booking access returns `404`, and non-admin access to `/api/v1/admin/bookings` returns `403`.
7. Promote the release only after the smoke tests and frontend build pass.

The current `render.yaml` keeps the existing service names. Confirm that its frontend URL matches the actual deployment before rollout; do not assume a URL from this README is the live production URL.

## Files changed/added for Phase 1

- `backend/app/main.py` — authentication, session and CSRF enforcement, ownership-scoped booking endpoints, role checks and validation.
- `backend/app/migrate.py` — additive schema migration.
- `backend/app/create_admin.py` — environment-driven administrator bootstrap.
- `backend/tests/test_security.py` — authentication and booking authorization tests.
- `backend/requirements.txt`, `backend/requirements-dev.txt` — runtime and test dependencies.
- `backend/.env.example`, `frontend/.env.example` — safe configuration templates.
- `frontend/src/App.tsx`, `frontend/src/style.css` — registration/login, session state, booking history and cancellation UI.
- `render.yaml` — session configuration.
- `.gitignore` — excludes local environment, database, dependency and build artifacts.
