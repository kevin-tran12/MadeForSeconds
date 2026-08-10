# MadeForSeconds

A personal recipe collection with integrated supporter subscriptions, expense tracking, and a Claude-powered recipe parser — built to run entirely on GCP's free tier.

## Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19 + Vite 6 + TypeScript + Tailwind CSS v4 |
| Backend | FastAPI (Python 3.12) |
| Database | Cloud Firestore |
| Auth | Google Identity Platform (Firebase) |
| Payments | Stripe (one-time and recurring donations) |
| Email | Resend |
| Recipe import | Claude (Desktop/Projects) via MCP tools |
| Caching | Upstash Redis (optional, falls back to in-memory) |
| Backend hosting | GCP Cloud Run (scale to zero) |
| Frontend hosting | Cloudflare Pages |
| DNS / CDN | Cloudflare |
| CI/CD | GitHub Actions + Cloud Build (backend) / Cloudflare Pages (frontend) |
| Infrastructure | Terraform |

All GCP services stay within the always-free tier for personal/low-traffic use.

> **First-time production setup?** See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## Features

### Public
- Browse, search, and filter recipes by category or ingredient
- Full recipe detail with cooking mode (full-screen step-by-step), nutrition, and multi-component dishes
- RSS feed and XML sitemap
- Supporter wall with optional display name and note

### Admin
- Create, edit, and delete recipes with rich structured fields (ingredients, instructions, components, nutrition)
- Upload recipe images to Cloud Storage
- Manage subscriber and donor display names/notes (approve, reject, toggle visibility)
- Expense ledger (TOTP 2FA protected): create, edit, void expenses with receipt uploads
- Expense reports: monthly/yearly summaries by category, CSV and PDF export

### Donations
- Stripe Checkout for one-time and recurring donations
- Post-payment profile setup (display name + note, subject to admin approval)
- Self-service cancellation via signed email link

---

## Project structure

```
├── backend/                    FastAPI application
│   ├── app/
│   │   ├── main.py             Entry point, CORS, routers, cache warm-up
│   │   ├── auth.py             Identity Platform JWT verification
│   │   ├── subscriber_auth.py  JWT generation for cancel links
│   │   ├── firestore.py        Firestore client singleton
│   │   ├── cache.py            Redis / in-memory caching
│   │   ├── config.py           Settings + env var loading
│   │   ├── models.py           Pydantic schemas (Recipe, Ingredient, Instruction…)
│   │   ├── models_expense.py   Pydantic schemas (Expense, ExpenseItem…)
│   │   ├── totp.py             TOTP 2FA logic and session JWT
│   │   ├── mcp_server.py       MCP server for Claude Projects integration
│   │   └── routes/
│   │       ├── public.py       GET /api/recipes, /categories, /sitemap.xml, /feed.xml
│   │       ├── admin.py        Admin recipe CRUD, image upload, supporter moderation
│   │       ├── subscriptions.py Stripe checkout, webhooks, cancel flow
│   │       ├── expenses.py     Expense CRUD + receipt upload (TOTP-gated)
│   │       ├── reports.py      Expense summaries, CSV/PDF export (TOTP-gated)
│   │       └── totp.py         TOTP setup, verify, session endpoints
│   ├── tests/                  Pytest test suite (74 tests)
│   ├── seed.py                 Load sample recipes into Firestore emulator
│   ├── Dockerfile              Production container
│   └── requirements.txt
├── src/                        React frontend
│   ├── lib/
│   │   ├── api-client.ts       Fetch wrapper (auth + TOTP header injection)
│   │   ├── api.ts              All API functions (public + admin)
│   │   ├── auth.ts             Firebase Identity Platform init
│   │   ├── types.ts            Recipe TypeScript interfaces
│   │   └── types-expense.ts    Expense TypeScript interfaces
│   ├── hooks/                  useRecipes, useRecipe, useCategories, useAuth
│   ├── contexts/               AuthContext (dev + prod auth modes)
│   ├── components/             UI, recipe, layout, admin, search, SEO components
│   └── pages/                  Route page components
├── tests-e2e/                  Playwright E2E tests (6 spec files)
├── terraform/                  GCP + Cloudflare infrastructure as code
├── docs/
│   └── DEPLOYMENT.md           Full production setup guide
├── vitest.config.ts            Frontend unit test config
├── playwright.config.ts        E2E test config
├── docker-compose.yml          Local dev stack
└── .env.local.example          Local env var template
```

---

## Local development

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Node.js 22+](https://nodejs.org/)

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
Edit `.env.local` and set at minimum:
- `VITE_DEV_ADMIN_PASSWORD` — any string, used as your local admin password

Optional (needed for full local feature testing):
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` — Stripe test keys
- `STRIPE_PRODUCT_ID` — (Optional) Legacy Stripe Product ID
- `SUBSCRIBER_JWT_SECRET` — any 32+ character string

**3. Start all services**
```bash
docker compose up
```

| Service | URL | Purpose |
|---------|-----|---------|
| Firestore emulator | `http://localhost:8080` | Local Firestore |
| FastAPI backend | `http://localhost:8000` | Recipe + admin API |
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
docker compose logs -f backend          # Tail backend logs
docker compose restart backend          # Reload after Python changes
docker compose exec backend bash        # Shell into backend container
docker compose down                     # Stop everything

npm run build                           # TypeScript check + Vite build
npm run test:unit                       # Vitest unit tests
npm run test:backend                    # Pytest (74 tests)
npm run test:e2e                        # Playwright E2E (requires running stack)
npm run test:e2e:ui                     # Playwright with interactive UI
```

### Local Stripe testing

```bash
brew install stripe/stripe-cli/stripe
stripe login
stripe listen --forward-to localhost:8000/api/subscribe/webhook
# Copy the webhook signing secret it prints → set as STRIPE_WEBHOOK_SECRET in .env.local
```

---

## API routes

### Public (no auth required)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health / liveness check |
| GET | `/api/recipes` | List published recipes (`?search=`, `?category=`, `?search_by=`) |
| GET | `/api/recipes/{slug}` | Single recipe |
| GET | `/api/categories` | All unique categories |
| GET | `/api/sitemap.xml` | SEO sitemap |
| GET | `/api/feed.xml` | RSS feed |
| GET | `/api/subscribe/supporters` | Public supporter list |

### Admin — recipes (requires auth)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/recipes` | All recipes (including drafts) |
| POST | `/api/admin/recipes` | Create recipe (slug auto-generated) |
| PUT | `/api/admin/recipes/{id}` | Update recipe |
| DELETE | `/api/admin/recipes/{id}` | Delete recipe |
| POST | `/api/admin/upload-image` | Upload image to GCS |

### Admin — supporters (requires auth)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/supporters/pending` | Pending name/note approvals |
| GET | `/api/admin/supporters/all` | All supporters |
| POST | `/api/admin/supporters/{collection}/{id}/approve-note` | Approve note |
| POST | `/api/admin/supporters/{collection}/{id}/reject-note` | Reject note |
| POST | `/api/admin/supporters/{collection}/{id}/toggle-note` | Toggle note visibility |
| POST | `/api/admin/supporters/{collection}/{id}/toggle-name` | Toggle name visibility |

### Admin — expenses (requires auth + TOTP session)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/admin/expenses` | Create expense |
| GET | `/api/admin/expenses` | List expenses (`?year=`, `?month=`, `?category=`) |
| GET | `/api/admin/expenses/{id}` | Get expense |
| PUT | `/api/admin/expenses/{id}` | Update expense |
| DELETE | `/api/admin/expenses/{id}` | Void expense |
| POST | `/api/admin/expenses/{id}/upload-receipt` | Upload receipt to GCS |
| GET | `/api/admin/expenses/{id}/receipt-url` | Get signed receipt URL |

### Admin — reports (requires auth + TOTP session)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/reports/summary` | Expense totals by category (`?year=`, `?month=`) |
| GET | `/api/admin/reports/csv` | CSV export |
| GET | `/api/admin/reports/pdf` | PDF export |

### Admin — TOTP (requires auth)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/totp/status` | Check if TOTP is configured |
| POST | `/api/admin/totp/setup` | Generate secret + QR code |
| POST | `/api/admin/totp/confirm-setup` | Verify code and save config |
| POST | `/api/admin/totp/verify` | Verify code and get session token |
| POST | `/api/admin/totp/reset` | Clear TOTP config |

### Subscriptions

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/subscribe/checkout` | Create Stripe Checkout session (Donation) |
| POST | `/api/subscribe/webhook` | Stripe webhook receiver |
| GET | `/api/subscribe/session-info` | Info for completed donation |
| POST | `/api/subscribe/setup-profile` | Set display name/note after donation |
| POST | `/api/subscribe/cancel-request` | Request recurring donation cancellation (sends email) |
| POST | `/api/subscribe/cancel-confirm` | Confirm cancellation with token |

---

## Testing

The project has three test layers:

### Backend — pytest (74 tests)
```bash
npm run test:backend
# or: cd backend && pytest --cov=app --cov-report=term-missing
```
Covers: auth, models, cache, public routes, admin routes, supporter moderation, subscriptions, expenses, reports, TOTP.

### Frontend unit — vitest (26 tests)
```bash
npm run test:unit
```
Covers: API client, expense math, hooks (useRecipes, useRecipe, useCategories), Button component.

### E2E — Playwright (6 spec files)
```bash
npm run test:e2e             # headless
npm run test:e2e:ui          # interactive
```
Covers: home page, public recipe browsing, recipe detail, admin recipe CRUD, navigation, support page.

---

## Branching & deployment workflow

### Frontend (Cloudflare Pages — automatic)

| Branch | Deployment |
|--------|-----------|
| `main` | Production — your custom domain |
| Any other branch | Preview — `<branch-name>.madeforseconds.pages.dev` |

All `*.madeforseconds.pages.dev` preview URLs are pre-approved in the backend CORS config.

### Backend (GCP Cloud Run — manual or Cloud Build)

After merging backend changes to `main`:

```bash
# Authenticate Docker with Artifact Registry (once per machine)
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build and push
docker build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/made-for-seconds/mfs/backend:latest ./backend
docker push us-central1-docker.pkg.dev/made-for-seconds/mfs/backend:latest

# Deploy (rolling, ~30–60s, zero downtime)
gcloud run services update mfs-backend \
  --region us-central1 \
  --image us-central1-docker.pkg.dev/made-for-seconds/mfs/backend:latest \
  --project made-for-seconds
```

Or push to `main` — Cloud Build runs these steps automatically if the trigger is configured.

### What requires what kind of deploy?

| Change | Action |
|--------|--------|
| Frontend (`.tsx`, `.ts`, `.css`) | Nothing — Cloudflare deploys automatically |
| `backend/app/*.py` | Rebuild + push Docker image → `gcloud run services update` |
| `backend/requirements.txt` | Rebuild + push Docker image → `gcloud run services update` |
| CORS origins or env vars | Update `terraform.tfvars` → `terraform apply` |
| Any `.tf` file | `terraform apply` |

---

## Local environment variables

| Variable | Description |
|----------|-------------|
| `VITE_API_URL` | FastAPI URL (`http://localhost:8000`) |
| `VITE_DEV_ADMIN_PASSWORD` | Local admin login password |
| `ENVIRONMENT` | `development` |
| `ADMIN_EMAILS` | Comma-separated admin emails |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins |
| `FIRESTORE_EMULATOR_HOST` | Set automatically by Docker Compose |
| `STRIPE_SECRET_KEY` | Stripe test secret key (`sk_test_…`) |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret (`whsec_…`) |
| `STRIPE_PRODUCT_ID` | (Optional) Legacy Stripe Product ID (`prod_…`) |
| `SUBSCRIBER_JWT_SECRET` | 32+ char secret for cancel link JWTs |
| `RESEND_API_KEY` | Resend API key (cancel emails) |
| `REDIS_URL` | Upstash Redis URL (optional — falls back to in-memory) |
