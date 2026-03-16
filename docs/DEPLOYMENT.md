# Production Deployment

Guide to deploying MadeForSeconds on GCP + Cloudflare.

---

## Prerequisites

- A [GCP project](https://console.cloud.google.com/) with billing enabled
  (billing is required even for free-tier usage — you won't be charged if you stay within limits)
- [`gcloud` CLI](https://cloud.google.com/sdk/docs/install) authenticated:
  ```bash
  gcloud auth login
  gcloud auth application-default login
  ```
- [Terraform ≥ 1.5](https://developer.hashicorp.com/terraform/install)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- A [Cloudflare account](https://cloudflare.com/) with your domain added

---

## First-time setup

### Step 1 — Configure Terraform

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
```

Edit `terraform/terraform.tfvars` and fill in every value:

| Variable | Description |
|----------|-------------|
| `gcp_project_id` | Your GCP project ID |
| `gcp_region` | Leave as `us-central1` (required for free egress) |
| `admin_emails` | Comma-separated admin email addresses |
| `allowed_origins` | Your frontend URL(s), e.g. `https://madeforseconds.pages.dev` |
| `backend_image` | Leave as-is — Cloud Build will push to this path |
| `github_owner` | Your GitHub username or org |
| `github_repo` | Repository name (e.g. `MadeForSeconds`) |
| `anthropic_api_key` | Anthropic API key for the recipe parser |
| `mcp_api_key` | Bearer token for Claude Projects MCP integration |

> `terraform.tfvars` is gitignored — never commit it, it contains secrets.

### Step 2 — Initialize and apply Terraform

```bash
cd terraform
terraform init
terraform apply
```

This provisions:
- Firestore database
- Artifact Registry repository
- Cloud Run service (scale-to-zero, 512 MB)
- Identity Platform (email + password auth)
- Cloud Build CI/CD trigger
- Cloudflare DNS record for the API subdomain
- All required GCP APIs and service accounts

### Step 3 — Connect GitHub to Cloud Build (one-time)

Cloud Build needs permission to read your repository before the trigger works.

1. Go to [GCP console → Cloud Build → Repositories](https://console.cloud.google.com/cloud-build/repositories)
2. Click **Connect repository**
3. Select **GitHub** and follow the OAuth flow
4. Select your `MadeForSeconds` repository and click **Connect**

This only needs to be done once.

### Step 4 — Build and push the first Docker image

Either push to `main` to trigger Cloud Build automatically, or do it manually:

```bash
# Authenticate Docker with Artifact Registry (once per machine)
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build and push from the project root
docker build -t us-central1-docker.pkg.dev/YOUR_PROJECT_ID/mfs/backend:latest ./backend
docker push us-central1-docker.pkg.dev/YOUR_PROJECT_ID/mfs/backend:latest

# Deploy to Cloud Run
gcloud run services update mfs-backend \
  --region us-central1 \
  --image us-central1-docker.pkg.dev/YOUR_PROJECT_ID/mfs/backend:latest \
  --project YOUR_PROJECT_ID
```

### Step 5 — Create an admin user

1. Go to [GCP console → Identity Platform → Users](https://console.cloud.google.com/customer-identity/users)
2. Click **Add user**
3. Enter the email address you put in `admin_emails` and set a password
4. This is the account you'll use to log in on the live site

### Step 6 — Connect frontend to Cloudflare Pages

1. Go to [Cloudflare Pages](https://pages.cloudflare.com/) → **Create a project**
2. Connect your GitHub account and select the `MadeForSeconds` repository
3. Configure the build:
   - **Build command**: `npm run build`
   - **Build output directory**: `dist`
4. Add environment variables under **Settings → Environment variables → Production**:

| Variable | Value |
|----------|-------|
| `VITE_API_URL` | Cloud Run URL — run `cd terraform && terraform output cloud_run_url` |
| `VITE_FIREBASE_API_KEY` | GCP console → Identity Platform → Application setup details |
| `VITE_FIREBASE_AUTH_DOMAIN` | `YOUR_PROJECT_ID.firebaseapp.com` |
| `VITE_FIREBASE_PROJECT_ID` | Your GCP project ID |

5. Repeat for the **Preview** environment so branch preview deployments can reach the backend.

### Step 7 — Verify

```bash
# Check Cloud Run is healthy
curl https://$(cd terraform && terraform output -raw cloud_run_url)/api/health

# Check the API returns recipes
curl https://api.yourdomain.com/api/recipes
```

Open your domain, click **Admin login**, and sign in with the account from Step 5.

---

## Day-to-day operations

### Updating the backend

Any change inside `backend/` requires a new Docker image. Run these after merging backend changes to `main`:

```bash
# 1. Authenticate Docker with Artifact Registry (once per machine)
gcloud auth configure-docker us-central1-docker.pkg.dev

# 2. Build and push the updated image
docker build -t us-central1-docker.pkg.dev/made-for-seconds/mfs/backend:latest ./backend
docker push us-central1-docker.pkg.dev/made-for-seconds/mfs/backend:latest

# 3. Deploy — rolling update, ~30–60 seconds, zero downtime
gcloud run services update mfs-backend \
  --region us-central1 \
  --image us-central1-docker.pkg.dev/made-for-seconds/mfs/backend:latest \
  --project made-for-seconds
```

**Alternatively**, push to `main` — if Cloud Build is configured (Step 3), it runs these steps automatically via `cloudbuild.yaml`.

### What requires what kind of deploy?

| Change | Action |
|--------|--------|
| Frontend only (`.tsx`, `.ts`, `.css`) | Nothing — Cloudflare Pages deploys automatically on push |
| `backend/app/*.py` | Rebuild + push Docker image → `gcloud run services update` |
| `backend/requirements.txt` | Rebuild + push Docker image → `gcloud run services update` |
| New CORS origin or env var | Update `terraform.tfvars` → `terraform apply` |
| Any `.tf` infrastructure change | `terraform apply` |

### Updating infrastructure

```bash
cd terraform

# Preview what will change
terraform plan

# Apply the changes
terraform apply
```

Common reasons to run `terraform apply`:
- Adding a new allowed CORS origin to `allowed_origins`
- Changing Cloud Run memory or CPU limits
- Adding a new secret or environment variable
- Any other `.tf` file change

### Viewing backend logs

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" resource.labels.service_name="mfs-backend"' \
  --limit 50 \
  --project made-for-seconds \
  --format "value(textPayload)"
```

Or browse them in the [GCP console → Cloud Run → mfs-backend → Logs](https://console.cloud.google.com/run).

---

## Cloudflare Pages previews

Every non-`main` branch gets an automatic preview at:
```
https://<branch-name>.madeforseconds.pages.dev
```

All `*.madeforseconds.pages.dev` origins are pre-approved in the backend's CORS config via regex — preview deployments can talk to the production API without any manual changes each time.

Make sure `VITE_API_URL` is set under **Settings → Environment variables → Preview** in Cloudflare Pages, pointing at the production backend URL.

---

## Production environment variables

### Frontend (Cloudflare Pages → Settings → Environment variables)

| Variable | Required | Description |
|----------|----------|-------------|
| `VITE_API_URL` | Yes | URL of the FastAPI backend |
| `VITE_FIREBASE_API_KEY` | Yes | Identity Platform API key |
| `VITE_FIREBASE_AUTH_DOMAIN` | Yes | Identity Platform auth domain |
| `VITE_FIREBASE_PROJECT_ID` | Yes | GCP project ID |

### Backend (managed via Terraform / Cloud Run)

| Variable | How it's set | Description |
|----------|-------------|-------------|
| `GCP_PROJECT_ID` | `terraform.tfvars` | GCP project ID |
| `ENVIRONMENT` | Hardcoded `production` in Terraform | Enables production auth |
| `ALLOWED_ORIGINS` | `terraform.tfvars → allowed_origins` | Explicit allowed CORS origins |
| `ADMIN_EMAILS` | GCP Secret Manager | Comma-separated admin emails |
| `MCP_API_KEY` | GCP Secret Manager | Bearer token for Claude Projects MCP |
| `ANTHROPIC_API_KEY` | GCP Secret Manager | Recipe parser API key |
| `REDIS_URL` | GCP Secret Manager (optional) | Upstash Redis for caching |

---

## GCP free tier summary

| Service | Free allowance | Expected usage |
|---------|---------------|----------------|
| Cloud Run | 2M req/mo · 360K GB-sec · 180K vCPU-sec | Well under for personal use |
| Firestore | 50K reads/day · 20K writes/day · 1 GiB storage | Well under |
| Artifact Registry | 0.5 GB storage | Cleanup policy keeps ≤ 5 images |
| Cloud Build | 2,500 build-min/mo | ~2 min per backend deploy |
| Identity Platform | 49,999 MAU/mo | 1 admin user |
| Cloud Logging | 50 GiB/mo | Minimal log volume |
