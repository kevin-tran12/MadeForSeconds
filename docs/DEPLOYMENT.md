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
- A [Stripe account](https://stripe.com/) (for subscriptions + donations)
- A [Resend account](https://resend.com/) (for cancellation emails)

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
| `backend_image` | Leave as-is — Cloud Build pushes to this path |
| `github_owner` | Your GitHub username or org |
| `github_repo` | Repository name (e.g. `MadeForSeconds`) |
| `workos_authkit_domain` | WorkOS AuthKit domain — OAuth issuer for MCP (e.g. `https://<slug>.authkit.app`) |
| `mcp_resource_url` | Public URL of the MCP endpoint (e.g. `https://<cloud-run-url>/mcp`) |
| `stripe_secret_key` | Stripe secret key (`sk_live_…`) |
| `stripe_webhook_secret` | Stripe webhook signing secret (`whsec_…`) |
| `stripe_product_id` | (Optional) Legacy Stripe Product ID (`prod_…`) |
| `subscriber_jwt_secret` | 32+ character secret for cancel link JWTs |
| `resend_api_key` | Resend API key for cancellation emails |
| `frontend_url` | Your production frontend URL (used in email links) |
| `redis_url` | Upstash Redis URL (optional — leave blank to use in-memory cache) |
| `billing_account` | GCP billing account ID, for the budget alert |
| `monthly_budget_amount` | Budget threshold in USD that triggers the alert |
| `alert_email` | Address that receives budget and uptime alerts |
| `instagram_user_id` | Instagram Creator account numeric ID (optional — leave blank to skip) |
| `instagram_access_token` | Initial long-lived Instagram token (sensitive — seeds Secret Manager; auto-rotated weekly after first deploy) |

> `terraform.tfvars` is gitignored — never commit it. It holds live Stripe keys
> and the billing account ID in plaintext. CI runs gitleaks over the full git
> history on every PR as a backstop, but the gitignore is the real defence.

### Step 2 — Initialize and apply Terraform

```bash
cd terraform
terraform init
terraform apply
```

This provisions:
- Firestore database + indexes
- Artifact Registry repository (with cleanup policy — keeps ≤ 5 images)
- Cloud Run service (scale-to-zero, 512 MB, startup CPU boost)
- Cloud Storage buckets (images — public, receipts — private + versioned)
- Identity Platform (Firebase Auth) for admin login
- Cloud Build CI/CD trigger
- GCP Secret Manager secrets (Stripe keys, JWT secret, API keys, Instagram token)
- Cloud Scheduler job for weekly Instagram token rotation (when `instagram_access_token` is set)
- Cloudflare DNS record for the API subdomain
- All required GCP APIs and IAM service accounts

### Step 3 — Connect GitHub to Cloud Build (one-time)

Cloud Build needs permission to read your repository before the trigger works.

1. Go to [GCP console → Cloud Build → Repositories](https://console.cloud.google.com/cloud-build/repositories)
2. Click **Connect repository**
3. Select **GitHub** and follow the OAuth flow
4. Select your `MadeForSeconds` repository and click **Connect**

### Step 4 — Set up Stripe

**Configure the webhook:**
1. Go to [Stripe Dashboard → Developers → Webhooks](https://dashboard.stripe.com/webhooks)
2. Click **Add endpoint**
3. Set the URL to `https://your-api-domain.com/api/subscribe/webhook`
4. Select these events:
   - `checkout.session.completed`
   - `customer.subscription.deleted`
5. Copy the signing secret (`whsec_…`) into `terraform.tfvars → stripe_webhook_secret`

**Tax Settings:**
By default, the application marks all donations as nontaxable (`txcd_00000000`). No further action is needed unless you exceed regional tax thresholds.

### Step 5 — Build and push the first Docker image

Either push to `main` (Cloud Build will trigger automatically after Step 3), or do it manually:

```bash
# Authenticate Docker with Artifact Registry (once per machine)
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build and push from the project root
docker build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/YOUR_PROJECT_ID/mfs/backend:latest ./backend
docker push us-central1-docker.pkg.dev/YOUR_PROJECT_ID/mfs/backend:latest

# Deploy to Cloud Run
gcloud run services update mfs-backend \
  --region us-central1 \
  --image us-central1-docker.pkg.dev/YOUR_PROJECT_ID/mfs/backend:latest \
  --project YOUR_PROJECT_ID
```

### Step 6 — Create an admin user

1. Go to [GCP console → Identity Platform → Users](https://console.cloud.google.com/customer-identity/users)
2. Click **Add user**
3. Enter the email address you put in `admin_emails` and set a password
4. This is the account you'll use to log in to the admin panel

### Step 7 — Connect frontend to Cloudflare Pages

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

5. Repeat for the **Preview** environment so branch previews can reach the backend.

Security headers are applied automatically from [`public/_headers`](../public/_headers), which Cloudflare reads at deploy time — no dashboard configuration needed.

### Step 8 — Verify

```bash
# Backend health check
curl https://$(cd terraform && terraform output -raw cloud_run_url)/api/health

# Recipes endpoint
curl https://api.yourdomain.com/api/recipes
```

Confirm the frontend security headers made it through:

```bash
curl -sI https://yourdomain.com | grep -iE 'content-security-policy|strict-transport-security|x-frame-options'
```

Then load the site and check the browser console for CSP violations. The usual
cause of a broken deploy here is an edited inline script in `index.html`
invalidating the `script-src` hash — `public/_headers` documents how to
recompute it.

Open your domain, click **Admin login**, and sign in with the Identity Platform account from Step 6.

Set up TOTP 2FA for expenses:
1. Log in as admin and go to `/admin/expenses`
2. Follow the TOTP setup prompt (scan QR with Google Authenticator or similar)
3. Expenses and reports will require the 6-digit code each session

---

## Day-to-day operations

### Updating the backend

Any change inside `backend/` requires a new Docker image:

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev

docker build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/made-for-seconds/mfs/backend:latest ./backend
docker push us-central1-docker.pkg.dev/made-for-seconds/mfs/backend:latest

# Rolling deploy, ~30–60s, zero downtime
gcloud run services update mfs-backend \
  --region us-central1 \
  --image us-central1-docker.pkg.dev/made-for-seconds/mfs/backend:latest \
  --project made-for-seconds
```

Or push to `main` — Cloud Build runs these steps automatically via `cloudbuild.yaml`.

### What requires what kind of deploy?

| Change | Action |
|--------|--------|
| Frontend (`.tsx`, `.ts`, `.css`) | Nothing — Cloudflare deploys automatically |
| `backend/app/*.py` | Rebuild + push Docker image → `gcloud run services update` |
| `backend/requirements.txt` | Rebuild + push Docker image → `gcloud run services update` |
| New CORS origin or env var | Update `terraform.tfvars` → `terraform apply` |
| Any `.tf` infrastructure change | `terraform apply` |

### Updating infrastructure

```bash
cd terraform
terraform plan     # Preview changes
terraform apply    # Apply changes
```

Common reasons to run `terraform apply`:
- Adding a new allowed CORS origin
- Changing Cloud Run memory or CPU limits
- Adding or rotating a secret
- Any other `.tf` file change

### Migrating Terraform state to GCS (one-time)

State currently lives in `terraform/terraform.tfstate` on one machine — losing
that file means losing track of every managed resource, and it contains secret
material. A versioned state bucket is defined in `state_backend.tf`:

```bash
cd terraform
terraform apply                 # creates the made-for-seconds-tf-state bucket
# Uncomment the backend "gcs" block in state_backend.tf, then:
terraform init -migrate-state   # copies local state into the bucket
terraform plan                  # should show no changes
rm terraform.tfstate terraform.tfstate.backup
```

### Backups & monitoring

- **Firestore**: daily managed backup with 7-day retention
  (`google_firestore_backup_schedule.daily`). List with
  `gcloud firestore backups list`; restore with
  `gcloud firestore databases restore`.
- **Uptime**: a Cloud Monitoring check hits `/api/health` every 15 minutes
  and emails the alert address after ~20 minutes of failures.

### Viewing backend logs

```bash
gcloud logging read \
  'resource.type="cloud_run_revision" resource.labels.service_name="mfs-backend"' \
  --limit 50 \
  --project made-for-seconds \
  --format "value(textPayload)"
```

Or browse them in the [GCP console → Cloud Run → mfs-backend → Logs](https://console.cloud.google.com/run).

### Rotating secrets

All secrets are stored in GCP Secret Manager. To rotate (e.g. Stripe keys):

1. Update the secret value in the [Secret Manager console](https://console.cloud.google.com/security/secret-manager)
   or via: `echo -n "new-value" | gcloud secrets versions add SECRET_NAME --data-file=-`
2. Cloud Run reads secret values at startup — re-deploy the service to pick up the new version:
   ```bash
   gcloud run services update mfs-backend --region us-central1 --project made-for-seconds
   ```

---

## Cloudflare Pages previews

Every non-`main` branch gets an automatic preview at:
```
https://<branch-name>.madeforseconds.pages.dev
```

All `*.madeforseconds.pages.dev` origins are pre-approved in the backend's CORS config — previews can talk to the production API without any manual changes.

Set `VITE_API_URL` under **Settings → Environment variables → Preview** in Cloudflare Pages, pointing at the production backend URL.

---

## Production environment variables

### Frontend (Cloudflare Pages → Settings → Environment variables)

| Variable | Required | Description |
|----------|----------|-------------|
| `VITE_API_URL` | Yes | URL of the FastAPI backend |
| `VITE_FIREBASE_API_KEY` | Yes | Identity Platform API key |
| `VITE_FIREBASE_AUTH_DOMAIN` | Yes | Identity Platform auth domain |
| `VITE_FIREBASE_PROJECT_ID` | Yes | GCP project ID |

### Backend (managed via Terraform → Cloud Run + Secret Manager)

| Variable | How it's set | Description |
|----------|-------------|-------------|
| `GCP_PROJECT_ID` | `terraform.tfvars` | GCP project ID |
| `ENVIRONMENT` | Hardcoded `production` in Terraform | Enables production auth |
| `ALLOWED_ORIGINS` | `terraform.tfvars → allowed_origins` | Allowed CORS origins |
| `FRONTEND_URL` | `terraform.tfvars → frontend_url` | Frontend URL used in email links |
| `ADMIN_EMAILS` | GCP Secret Manager | Comma-separated admin emails |
| `STRIPE_SECRET_KEY` | GCP Secret Manager | Stripe secret key (`sk_live_…`) |
| `STRIPE_WEBHOOK_SECRET` | GCP Secret Manager | Stripe webhook signing secret (`whsec_…`) |
| `STRIPE_PRODUCT_ID` | GCP Secret Manager | Stripe Product ID (`prod_…`) |
| `SUBSCRIBER_JWT_SECRET` | GCP Secret Manager | Secret for signing cancel link JWTs (32+ chars) |
| `RESEND_API_KEY` | GCP Secret Manager | Resend API key for cancellation emails |
| `WORKOS_AUTHKIT_DOMAIN` | Plain env (Terraform) | WorkOS AuthKit domain — OAuth issuer for MCP auth |
| `MCP_RESOURCE_URL` | Plain env (Terraform) | Public URL of the `/mcp` endpoint (OAuth resource) |
| `REDIS_URL` | GCP Secret Manager (optional) | Upstash Redis URL for caching |
| `GCS_BUCKET_NAME` | Set by Terraform | Cloud Storage bucket for recipe images |
| `GCS_RECEIPTS_BUCKET_NAME` | Set by Terraform | Cloud Storage bucket for expense receipts |
| `INSTAGRAM_USER_ID` | `terraform.tfvars → instagram_user_id` | Instagram Creator account numeric ID |
| `INSTAGRAM_REFRESH_INVOKER_EMAIL` | Set by Terraform (backend SA email) | SA email the refresh endpoint accepts OIDC tokens from |
| `INSTAGRAM_REFRESH_AUDIENCE` | Set by Terraform (refresh endpoint URL) | Expected OIDC audience for the refresh endpoint |
| `instagram-access-token` (Secret Manager) | Initial value from `terraform.tfvars → instagram_access_token`; rotated by Cloud Scheduler | Instagram long-lived token — never injected as env var; read at runtime |

---

## MCP server (recipe/expense automation)

The backend exposes an MCP server at `https://<cloud-run-url>/mcp` (Streamable
HTTP). Auth is **OAuth 2.1** — the MCP server is a *resource server* that only
validates tokens; **WorkOS AuthKit** is the authorization server (login, consent,
PKCE, Dynamic Client Registration). The SDK serves
`/.well-known/oauth-protected-resource/mcp` so clients auto-discover WorkOS.
Access is gated to `ADMIN_EMAILS`. Production startup fails if
`WORKOS_AUTHKIT_DOMAIN` / `MCP_RESOURCE_URL` are unset.

**WorkOS one-time setup:** create an AuthKit-enabled environment, enable Dynamic
Client Registration, and restrict sign-in to the admin email. Set
`workos_authkit_domain` (the issuer, `https://<slug>.authkit.app`) and
`mcp_resource_url` (`https://<cloud-run-url>/mcp`) in `terraform.tfvars`.

**claude.ai custom connector:** add the URL `https://<cloud-run-url>/mcp/`,
leave the OAuth Client ID/Secret **blank** (DCR handles registration), then
complete the WorkOS login as the admin.

**Claude Code:** `claude mcp add --transport http madeforseconds https://<cloud-run-url>/mcp/`,
then run `/mcp` to authenticate via the browser. No static token needed.

Set `MCP_TIMEOUT=30000` in the client environment — the backend scales to
zero, so the first call after idle takes ~10s while Cloud Run cold-starts.
If a call times out, retry once.

Local dev (`docker compose up`) runs the MCP server **unauthenticated** (no
WorkOS dependency), matching the `require_admin` dev bypass.

**Tools**: `list_recipes`, `get_recipe`, `list_categories`, `create_recipe`,
`update_recipe`, `publish_recipe`, `unpublish_recipe`, `delete_recipe`,
`request_image_upload`, `upload_image_from_url`, `create_expense`,
`publish_instagram_post`, `publish_recipe_to_instagram`.

**Recipe workflow**: `create_recipe` saves an unpublished draft (duplicate
titles return a `slug_conflict` pointer instead of writing a second copy) →
iterate with `update_recipe` → attach a photo → `publish_recipe`.

**Image/receipt uploads** go directly to GCS via short-lived signed PUT URLs:
`request_image_upload(filename, content_type, kind)` returns `upload_url` +
a ready-to-run `curl_example`; after the PUT, pass `final_url` to
`update_recipe(image_url=…)` or `create_expense(receipt_url=…)`. Signed URLs
require the `iamcredentials` API and the backend SA's
`roles/iam.serviceAccountTokenCreator` self-grant (both in Terraform — run
`terraform apply` once after upgrading). `upload_image_from_url` copies an
already-hosted https image instead.

**Instagram publishing**: `publish_recipe_to_instagram(slug)` posts the
recipe's GCS image to Instagram and auto-builds a caption from the title,
description, link, and hashtags (pass `caption=` to override).
`publish_instagram_post(image_url, caption)` is the generic primitive for any
public HTTPS JPEG. Constraints: caption ≤ 2200 chars, ≤ 30 hashtags, 25
posts/24h; PNG/WebP may be rejected by Instagram — prefer JPEG.

> **One-time Meta setup** (do before setting `instagram_access_token` in tfvars):
> 1. Connect the Instagram Creator account via **Meta for Developers** → create an app → add the Instagram product → request scopes `instagram_business_basic` + `instagram_business_content_publish`.
> 2. Complete the OAuth exchange once to obtain the Creator account's numeric user ID and an initial long-lived token (short-lived → exchange via `GET graph.instagram.com/v23.0/access_token`).
> 3. Set `instagram_user_id` + `instagram_access_token` in `terraform.tfvars` and run `terraform apply`.

**Automatic token rotation**: The Instagram long-lived token expires after
60 days. After the first `terraform apply` with the token set, a Cloud
Scheduler job runs every Monday at 04:00 UTC, calling
`POST /api/internal/instagram/refresh-token`. The endpoint exchanges the
current token for a fresh one and writes it as a new Secret Manager version.
The backend reads `latest` at request time (short in-process cache), so
rotation is fully hands-off. Residual risk: if the scheduler is disabled for
60+ days the token lapses; a manual one-time re-auth (repeat step 2 above) is
then required.

---

## GCP free tier summary

| Service | Free allowance | Expected usage |
|---------|---------------|----------------|
| Cloud Run | 2M req/mo · 360K GB-sec · 180K vCPU-sec | Well under for personal use |
| Firestore | 50K reads/day · 20K writes/day · 1 GiB storage | Well under |
| Cloud Storage | 5 GiB storage · 1 GiB/mo egress (US) | Minimal for images + receipts |
| Artifact Registry | 0.5 GiB storage | Cleanup policy keeps ≤ 5 images |
| Cloud Build | 2,500 build-min/mo | ~2 min per backend deploy |
| Identity Platform | 49,999 MAU/mo | 1 admin user |
| Cloud Logging | 50 GiB/mo ingestion | Minimal log volume |
| Secret Manager | 6 active secrets free · 10K access/mo | Within limits |
