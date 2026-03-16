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
| CI/CD | Cloud Build (backend) / Cloudflare Pages (frontend) |
| Infrastructure | Terraform |

All GCP services stay within the always-free tier for personal/low-traffic use.

> **First-time production setup?** See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

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
│   ├── cloud_run.tf         Cloud Run service (free-tier optimized)
│   ├── firestore.tf         Firestore database
│   ├── artifact_registry.tf Docker image registry + cleanup policy
│   ├── cloudbuild.tf        CI/CD trigger + IAM
│   └── ...
├── docs/
│   └── DEPLOYMENT.md        Full production setup guide
├── vitest.config.ts         Unit test config (separate from vite.config.ts)
├── cloudbuild.yaml          Cloud Build steps (build + push + deploy)
├── docker-compose.yml       Local dev environment
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
# Tail backend logs
docker compose logs -f backend

# Restart just the backend after changing Python code
docker compose restart backend

# Open a shell in the backend container
docker compose exec backend bash

# Stop everything
docker compose down

# TypeScript check + production build
npm run build

# Run unit tests
npm run test:unit

# Run e2e tests (requires a running local stack)
npm run test:e2e
```

---

## Branching & deployment workflow

### Frontend (automatic via Cloudflare Pages)

Every push triggers a build automatically:

| Branch | Deployment |
|--------|-----------|
| `main` | Production — `madeforseconds.pages.dev` (and your custom domain) |
| Any other branch | Preview — `<branch-name>.madeforseconds.pages.dev` |

Frontend changes never need a manual step — just push and Cloudflare builds it.

> All `*.madeforseconds.pages.dev` preview URLs are pre-approved in the backend's CORS config, so previews can talk to the production API without any extra setup.

### Backend (manual push required)

The backend runs on Cloud Run. Changes to anything in `backend/` need a new Docker image to take effect. Run these commands after merging backend changes to `main`:

```bash
# 1. Authenticate Docker with Artifact Registry (one-time per machine)
gcloud auth configure-docker us-central1-docker.pkg.dev

# 2. Build and push the new image
docker build --platform linux/amd64 -t us-central1-docker.pkg.dev/made-for-seconds/mfs/backend:latest ./backend
docker push us-central1-docker.pkg.dev/made-for-seconds/mfs/backend:latest

# 3. Deploy the new image to Cloud Run
gcloud run services update mfs-backend \
  --region us-central1 \
  --image us-central1-docker.pkg.dev/made-for-seconds/mfs/backend:latest \
  --project made-for-seconds
```

Step 3 takes about 30–60 seconds. Cloud Run performs a rolling deploy with zero downtime.

**Alternatively**, push to `main` — Cloud Build will build and deploy automatically if the trigger is configured (see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).

### When does the backend need a redeploy?

| Change | Needs backend redeploy? |
|--------|------------------------|
| Frontend (`.tsx`, `.ts`, `.css`) | No — Cloudflare handles it |
| `backend/app/*.py` | **Yes** |
| `backend/requirements.txt` | **Yes** |
| Terraform (`.tf` files) | Run `terraform apply` instead |
| `ALLOWED_ORIGINS` / env vars | Run `terraform apply` instead |

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
