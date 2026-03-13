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

## Production deployment

### Prerequisites

- A [GCP project](https://console.cloud.google.com/) with billing enabled
  (billing is required even for free-tier usage — you won't be charged if you stay within limits)
- [`gcloud` CLI](https://cloud.google.com/sdk/docs/install) authenticated: `gcloud auth login && gcloud auth application-default login`
- [Terraform ≥ 1.5](https://developer.hashicorp.com/terraform/install)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- A [Cloudflare account](https://cloudflare.com/) with your domain added

### Step 1 — Configure Terraform

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
```

Edit `terraform/terraform.tfvars` and fill in every value:

| Variable | Description |
|----------|-------------|
| `gcp_project_id` | Your GCP project ID |
| `gcp_region` | Leave as `us-central1` (required for free egress) |
| `cloudflare_api_token` | API token with **Zone: DNS: Edit** permission |
| `cloudflare_zone_id` | Found in Cloudflare dashboard → your domain → Overview |
| `domain` | Your root domain (e.g. `recipes.example.com`) |
| `admin_emails` | Comma-separated admin email addresses |
| `allowed_origins` | Your frontend URL (e.g. `https://recipes.example.com`) |
| `backend_image` | Leave as-is — Cloud Build will push to this path |
| `github_owner` | Your GitHub username or org |
| `github_repo` | Repository name (e.g. `MadeForSeconds`) |

### Step 2 — Initialize and apply Terraform

```bash
cd terraform
terraform init
terraform apply
```

This provisions:
- Firestore database
- Artifact Registry repository
- Cloud Run service (scale-to-zero, 256 MB)
- Identity Platform (email + password auth)
- Cloud Build CI/CD trigger
- Cloudflare DNS record for the API subdomain
- All required GCP APIs

### Step 3 — Connect GitHub to Cloud Build (one-time)

Cloud Build needs permission to read your repository before the trigger works.

1. Go to [GCP console → Cloud Build → Repositories](https://console.cloud.google.com/cloud-build/repositories)
2. Click **Connect repository**
3. Select **GitHub** and follow the OAuth flow
4. Select your `MadeForSeconds` repository and click **Connect**

This only needs to be done once.

### Step 4 — Build and push the first Docker image

Either push to `main` to trigger the Cloud Build pipeline automatically, or run a manual build:

```bash
# Get the registry path from Terraform output
cd terraform
terraform output artifact_registry_repo

# Submit a manual build (from project root)
cd ..
gcloud builds submit \
  --config cloudbuild.yaml \
  --substitutions _IMAGE=$(cd terraform && terraform output -raw artifact_registry_repo)/backend \
  .
```

Cloud Build uses the `e2-standard-2` machine type, which is included in the 2,500 free build-minutes/month.

### Step 5 — Create an admin user

1. Go to [GCP console → Identity Platform → Users](https://console.cloud.google.com/customer-identity/users)
2. Click **Add user**
3. Enter the email address you put in `admin_emails` and set a password
4. This is the account you'll use to log in on the live site

### Step 6 — Deploy the frontend to Cloudflare Pages

1. Go to [Cloudflare Pages](https://pages.cloudflare.com/) → **Create a project**
2. Connect your GitHub account and select the `MadeForSeconds` repository
3. Configure the build:
   - **Build command**: `npm run build`
   - **Build output directory**: `dist`
4. Add environment variables (Settings → Environment variables → Production):

| Variable | Value |
|----------|-------|
| `VITE_API_URL` | Your Cloud Run URL (from `terraform output cloud_run_url`) or `https://api.yourdomain.com` |
| `VITE_FIREBASE_API_KEY` | GCP console → Identity Platform → Application setup details |
| `VITE_FIREBASE_AUTH_DOMAIN` | `YOUR_PROJECT_ID.firebaseapp.com` |
| `VITE_FIREBASE_PROJECT_ID` | Your GCP project ID |

5. Click **Save and deploy**

### Step 7 — Verify the deployment

```bash
# Check Cloud Run is healthy
curl https://$(cd terraform && terraform output -raw cloud_run_url)/api/health

# Check the API returns recipes (assuming you've added some via admin)
curl https://api.yourdomain.com/api/recipes
```

Open your domain in a browser, click **Admin login**, and sign in with the account created in Step 5.

---

## Environment variables reference

### Frontend (`.env.local` for local dev, Cloudflare Pages env vars for production)

| Variable | Required | Description |
|----------|----------|-------------|
| `VITE_API_URL` | Yes | URL of the FastAPI backend (`http://localhost:8000` locally) |
| `VITE_FIREBASE_API_KEY` | Prod only | Identity Platform API key |
| `VITE_FIREBASE_AUTH_DOMAIN` | Prod only | Identity Platform auth domain |
| `VITE_FIREBASE_PROJECT_ID` | Prod only | GCP project ID |
| `VITE_DEV_ADMIN_PASSWORD` | Local only | Password for the local admin login modal |

### Backend (set via Docker Compose env for local dev, Cloud Run env vars for production)

| Variable | Required | Description |
|----------|----------|-------------|
| `GCP_PROJECT_ID` | Yes | GCP project ID (also used as Firestore project) |
| `ENVIRONMENT` | Yes | `development` or `production` |
| `ADMIN_EMAILS` | Yes | Comma-separated admin email addresses |
| `ALLOWED_ORIGINS` | Yes | Comma-separated allowed CORS origins |
| `FIRESTORE_EMULATOR_HOST` | Local only | Set automatically by Docker Compose |

---

## GCP free tier summary

This project is designed to stay within GCP's always-free limits:

| Service | Free allowance | Expected usage |
|---------|---------------|----------------|
| Cloud Run | 2M req/mo · 360K GB-sec | Well under for personal use |
| Firestore | 50K reads/day · 20K writes/day · 1 GiB storage | Well under |
| Artifact Registry | 0.5 GB storage | Cleanup policy keeps ≤5 images |
| Cloud Build | 2,500 build-min/mo | ~2 min per deploy |
| Identity Platform | 49,999 MAU/mo | 1 admin user |
| Cloud Logging | 50 GiB/mo | Minimal log volume |
