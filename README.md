# MadeForSeconds

A personal recipe collection — built to be fast, minimal, and run entirely on GCP's free tier.

## Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19 + Vite 6 + TypeScript + Tailwind CSS v4 |
| Backend | FastAPI (Python 3.12) |
| Database | Cloud Firestore |
| Auth | Google Identity Platform (email + password) |
| Backend hosting | GCP Cloud Run (scale to zero) |
| Frontend hosting | Cloudflare Pages |
| DNS / CDN | Cloudflare |
| CI/CD | Cloud Build |
| Infrastructure | Terraform |

All GCP services stay within the always-free tier for personal/low-traffic use.

> **Deploying to production?** See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## Project structure

```
├── backend/                 FastAPI application
│   ├── app/
│   │   ├── main.py          Entry point, CORS, routes
│   │   ├── auth.py          Identity Platform JWT verification
│   │   ├── firestore.py     Firestore client
│   │   ├── models.py        Pydantic schemas
│   │   └── routes/
│   │       ├── public.py    GET /api/recipes, /api/recipes/{slug}, /api/categories
│   │       └── admin.py     Admin CRUD (auth required)
│   ├── seed.py              Load sample data into Firestore
│   ├── Dockerfile           Production container
│   └── requirements.txt
├── src/                     React frontend
│   ├── lib/
│   │   ├── api-client.ts    Fetch wrapper → FastAPI
│   │   ├── api.ts           All API functions
│   │   ├── auth.ts          Identity Platform (firebase/auth)
│   │   └── types.ts         TypeScript interfaces
│   ├── hooks/               useRecipes, useRecipe, useCategories, useAuth
│   ├── contexts/            AuthContext
│   ├── components/          UI, recipe, layout, admin components
│   └── pages/               Route page components
├── terraform/               GCP + Cloudflare infrastructure
│   ├── apis.tf              Enable required GCP APIs
│   ├── cloud_run.tf         Cloud Run service (free-tier optimized)
│   ├── firestore.tf         Firestore database
│   ├── artifact_registry.tf Docker image registry + cleanup policy
│   ├── identity_platform.tf Auth config
│   ├── cloudbuild.tf        CI/CD trigger + IAM
│   ├── service_accounts.tf  Cloud Run service account
│   └── cloudflare.tf        DNS records
├── docs/
│   └── DEPLOYMENT.md        Production deployment guide
├── cloudbuild.yaml          Cloud Build steps (build + push + deploy)
├── docker-compose.yml       Local dev environment
├── Dockerfile.dev           Vite dev container
└── .env.local.example       Local env var template
```

---

## Local development

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Node.js 22+](https://nodejs.org/) (for running `npm install` outside Docker)

### Steps

**1. Clone and enter the repo**
```bash
git clone https://github.com/YOUR_USERNAME/MadeForSeconds.git
cd MadeForSeconds
```

**2. Set up environment variables**
```bash
cp .env.local.example .env.local
```
Edit `.env.local` and set a `VITE_DEV_ADMIN_PASSWORD` (any string — this is your local admin password).

**3. Start all services**
```bash
docker compose up
```

This starts three containers:
| Service | URL | Purpose |
|---------|-----|---------|
| Firestore emulator | `http://localhost:8080` | Local Firestore database |
| FastAPI backend | `http://localhost:8000` | Recipe API |
| Vite frontend | `http://localhost:5173` | React app |

**4. Seed sample recipes** (first time only)
```bash
docker compose exec backend python seed.py
```

**5. Open the app**

Go to `http://localhost:5173`. To access the admin panel:
1. Click **Admin login** in the header
2. Enter the password you set in `VITE_DEV_ADMIN_PASSWORD`

### Useful dev commands

```bash
# Tail backend logs only
docker compose logs -f backend

# Restart just the backend (after changing Python code)
docker compose restart backend

# Open a shell in the backend container
docker compose exec backend bash

# Stop everything
docker compose down
```

---

## Local environment variables

| Variable | Description |
|----------|-------------|
| `VITE_API_URL` | FastAPI backend URL (`http://localhost:8000`) |
| `VITE_DEV_ADMIN_PASSWORD` | Password for the local admin login modal |
| `GCP_PROJECT_ID` | GCP project ID (also used as Firestore project) |
| `ENVIRONMENT` | Set to `development` |
| `ADMIN_EMAILS` | Comma-separated admin email addresses |
| `ALLOWED_ORIGINS` | Comma-separated allowed CORS origins |
| `FIRESTORE_EMULATOR_HOST` | Set automatically by Docker Compose |
