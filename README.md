# MtaaMove — MVP starter

MtaaMove is a starter project for a Kenyan moving-services marketplace with a customer-facing React UI and FastAPI API. It includes an initial quote flow, booking submission, a small demo provider list, a SQLite local database, and a Render Blueprint template.

## Important prototype limitations

This is a development scaffold, not a production-ready moving marketplace. The quote is a transparent illustrative formula and is **not based on real route distance**. Provider records are demo data and not verified. Authentication, role-based access, provider dispatch, Google Maps geocoding/routing, live tracking, SMS notifications, real payment collection, and admin workflows are not implemented. The booking list/detail endpoints currently have no authentication and must not be exposed to real customers before access controls are added. Do not enter sensitive customer information into a public deployment.

## Prerequisites

- Python 3.11+
- Node.js 20+
- Git (optional)

## Run locally

### API

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs and http://localhost:8000/health.

### Frontend (new terminal)

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open the Vite URL, usually http://localhost:5173. The API's CORS defaults allow this local origin.

## API endpoints in this scaffold

- `GET /health` — process health
- `GET /ready` — database readiness
- `POST /api/v1/quotes` — illustrative KES estimate
- `POST /api/v1/bookings` — save a demo booking
- `GET /api/v1/bookings` — demo listing (currently unauthenticated; local use only)
- `GET /api/v1/bookings/{id}` — demo detail (currently unauthenticated; local use only)
- `POST /api/v1/bookings/{id}/cancel` — demo cancellation
- `GET /api/v1/providers` — sample, explicitly unverified demo provider records

## Render deployment

1. Push this folder to a new GitHub repository.
2. In Render, choose **New → Blueprint** and select the repository containing `render.yaml`.
3. Replace both `REPLACE-WITH-YOUR-...` origins with the actual Render URLs. Set the API `CORS_ORIGINS` to the exact frontend origin and the frontend `VITE_API_BASE_URL` to the API URL.
4. Review the database plan/pricing before creating resources; choose a plan suitable for your expected usage.
5. After the first deploy, check `/health`, `/ready`, and `/docs` on the API.

For a production rollout, add migrations (Alembic), authentication/authorization, per-customer record ownership, provider onboarding and verification, atomic job assignment, rate limiting, audit logging, privacy controls, and Google Maps Routes/Places with restricted keys before inviting real customers. Vite variables prefixed with `VITE_` are public in the browser bundle; never put server secrets there.
