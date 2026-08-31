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
- [Terraform 1.15.9](https://developer.hashicorp.com/terraform/install) —
  pinned exactly, not a floor. See [State storage & locking](#state-storage--locking)
  for why the version matters more than usual here.
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
| `monthly_budget_amount` | Budget cap in USD (default `15`) — see [Cost circuit breaker](#cost-circuit-breaker) |
| `alert_email` | Address that receives budget and uptime alerts |
| `instagram_user_id` | Instagram Creator account numeric ID (deprecated for now — leave blank; see [MCP server § Instagram publishing](#mcp-server-recipeexpense-automation)) |
| `instagram_access_token` | Initial long-lived Instagram token (sensitive — seeds Secret Manager; auto-rotated weekly after first deploy, if ever re-enabled — currently left blank) |
| `environment` | `production` or `development` — only these two are meaningful, injected as `ENVIRONMENT`. Defaults to `production`; leave unset unless you know why you're changing it |
| `deployment_target` | `production` or `staging` — which GCP project's infra topology this apply is for. Distinct from `environment` above: staging still runs the app in `production` mode (real auth, TOTP, Stripe test-mode webhooks), this only gates which infra exists (Cloud Scheduler jobs, Firestore backups, the budget breaker, the secret pruner, the state bucket resource). Defaults to `production` |
| `state_admin_email` | Google account of whoever runs `terraform apply` — granted `objectAdmin` on the state bucket. Must match the casing already in state if you're picking up an existing deployment; IAM preserves case and a mismatch forces the binding to be replaced |

> `terraform.tfvars` is gitignored — never commit it. It holds live Stripe keys
> and the billing account ID in plaintext. CI runs gitleaks over the full git
> history on every PR as a backstop, but the gitignore is the real defence.
>
> Every optional secret above is gated on `count = var.X != "" ? 1 : 0` in
> Terraform. A blank value doesn't just skip creating the secret — on an
> *existing* deployment it plans to destroy it. Fill in every value that
> applies to your setup before running `plan` against a live environment.

### Step 2 — Initialize and apply Terraform

Install **Terraform 1.15.9** specifically — `terraform/.terraform-version`
pins it, and `required_version` in `main.tf` enforces it. The CLI version is
part of the state format: a newer Terraform writing state makes it unreadable
to an older one on a machine you haven't upgraded yet.

```bash
cd terraform
terraform init
terraform apply
```

This provisions, across five modules (`modules/security`, `modules/storage`,
`modules/backend-service`, `modules/observability`, `modules/cost-controls`):
- Firestore database + indexes
- Artifact Registry repository (with cleanup policy — keeps ≤ 5 images)
- Cloud Run service (scale-to-zero, 512 MB, startup CPU boost)
- Cloud Storage buckets (images — public; receipts — private, versioned, and
  held under a 7-year retention policy; staging — private and ephemeral)
- Identity Platform (Firebase Auth) for admin login
- Cloud Build CI/CD trigger
- GCP Secret Manager secrets (Stripe keys, JWT secret, API keys, and
  Instagram's token if that feature is ever re-enabled — see
  [MCP server § Instagram publishing](#mcp-server-recipeexpense-automation),
  currently deprecated)
- Cloud Scheduler jobs (weekly usage report, weekly Secret Manager version
  pruning, monthly budget-breaker reset; a 4th weekly Instagram token
  rotation job only if `instagram_access_token` is set)
- Budget alerting and the auto-kill Cloud Functions
- Secret Manager version pruning Cloud Function (`secret-pruner`)
- Uptime and error-rate monitoring
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

### Step 6 — Enable Google sign-in and authorize the admin

The admin panel authenticates only with Google (`GoogleAuthProvider` in
`src/lib/auth.ts`). Email/password sign-in is deliberately disabled in
`terraform/modules/security/identity_platform.tf` — it was an unused code path
that kept a live password-hashing signer key in the project config.

1. Go to [GCP console → Identity Platform → Providers](https://console.cloud.google.com/customer-identity/providers)
2. Add the **Google** provider if it is not already present. It is configured
   here rather than in Terraform because it needs an OAuth client ID/secret.
3. Make sure the email address you want to use is listed in `admin_emails` in
   `terraform.tfvars`. Authorization is by email claim — `require_admin` in
   `backend/app/auth.py` checks the verified token's email against that list, so
   no user record needs to be pre-created.
4. Sign in at `/admin` with that Google account.

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

> **The deploy pipeline owns the running image, not Terraform.** `terraform/modules/backend-service/cloud_run.tf`
> sets `ignore_changes` on the container image, so `terraform apply` never
> re-pins the service to `var.backend_image`. That variable only seeds the
> service on first create. Without this guard an infrastructure-only apply would
> roll the backend onto whatever `:latest` happened to point at — which is
> exactly how a budget-config apply once tried to deploy an unrelated image that
> could not boot. Roll back or forward with `gcloud run services update`.

> **Apply Terraform before pushing a backend revision that depends on it.**
> Pushing to `main` deploys automatically via Cloud Build; Terraform is
> applied manually and separately. If a code change needs a new Terraform
> resource — a bucket, an env var, an IAM grant — apply Terraform *first*.
>
> A revision missing something `validate_production_settings()` requires
> (`backend/app/config.py`) — currently the three GCS bucket names, the
> WorkOS domain, the MCP resource URL, and a few others — crashes at import
> time before it ever binds a port. This is the safe failure mode, not a
> dangerous one: `cloudbuild.yaml` deploys the new revision with
> `--no-traffic --tag=candidate-$SHORT_SHA` first, so Cloud Run waits for it
> to pass its startup probe before that tagged URL responds at all, and
> `backend/scripts/smoke_test_deploy.py` then has to pass against that URL
> before `update-traffic` ever runs. A revision that crash-loops here never
> goes live — the previous, working revision keeps serving 100% of traffic
> throughout, and **no manual rollback step is needed.** Check Cloud Run's
> revision list and the crash-looping revision's logs for the `RuntimeError`
> message, fix the ordering (apply Terraform, then re-push or re-deploy the
> same image), and the next revision will start and promote normally.
>
> This check exists because earlier code silently fell back to a fake
> "upload succeeded" placeholder response whenever a bucket was unconfigured
> — in production exactly as in local dev — so a revision deployed ahead of
> `terraform apply` would report every image upload as successful while
> attaching nothing real. The startup check turns that into an impossible
> state instead of a silent one.

> **Run the image-pipeline smoke test after touching the staging bucket,
> images bucket, or their IAM.** Unit tests mock every GCS call; they prove
> the logic is correct but cannot catch a wrong deployed IAM grant, a
> mismatched signed-URL header, an unexpected bucket policy, or promotion
> behaving differently against real GCS than a mock. This is a manual,
> operator-only gate, not a CI step — it needs real credentials with write
> access to the target project's Firestore and buckets, and it creates and
> deletes disposable recipes using isolated UUID-prefixed object names, so it
> should not run unattended against production on every push.
>
> ```bash
> gcloud auth application-default login \
>     --impersonate-service-account=<backend-sa-email>
> cd backend
> python scripts/smoke_test_image_pipeline.py \
>     --project made-for-seconds \
>     --backend-url "$(terraform -chdir=../terraform output -raw cloud_run_url)"
> ```
>
> Impersonating the backend service account — not the operator's own,
> typically broader, ADC — means the script's GCS/Firestore calls run under
> the same IAM the deployed revision actually has. This needs
> `roles/iam.serviceAccountTokenCreator` on the backend SA, granted to
> `var.state_admin_email` by `backend_operator_impersonation` in
> `terraform/modules/security/service_accounts.tf`.
>
> It first confirms the deployed revision is actually healthy
> (`GET /api/health`), then requests a real signed upload URL, PUTs a
> GPS-bearing JPEG to staging, confirms staging is not publicly readable,
> attaches it through the real `create_recipe()` (which is what actually
> triggers promotion), confirms the promoted object is metadata-stripped with
> the immutable cache header, confirms Firestore holds the promoted URL,
> confirms the staged copy was deleted, and confirms a non-image payload is
> rejected without leaving a Firestore document behind. It cleans up every
> object it could have created, in both buckets, whether it passes or fails
> at any step, and reports anything it could not remove. **Treat a failure as
> blocking** — do not let normal traffic depend on a revision or apply this
> hasn't passed against.
>
> **What this does not prove**: it calls application code in-process, not
> through the deployed HTTP surface. It does not verify that a real MCP
> client can authenticate through `/mcp` (interactive WorkOS OAuth) or that
> the admin UI can authenticate through `/api/admin/*` (Firebase ID token) —
> neither has a non-interactive, scriptable auth path today.

> **Run the receipts-role smoke test after touching the receipts bucket's
> IAM.** The receipts bucket carries a 7-year retention policy, so unlike
> the image-pipeline test above it cannot exercise the real bucket — a
> synthetic test object there would be permanent. Instead it creates a
> throwaway scratch bucket with the same custom role bound and runs the
> real receipt code paths against it as the impersonated backend SA,
> deleting the scratch bucket at the end. Also a manual, operator-only gate,
> not a CI step.
>
> ```bash
> cd backend
> python scripts/smoke_test_receipt_role.py --project made-for-seconds
> ```
>
> Unlike the image-pipeline test, no separate `gcloud auth
> application-default login --impersonate-service-account=...` step is
> needed first — the script builds impersonated credentials itself for the
> exercise phase. Prerequisites the operator needs, beyond
> `roles/iam.serviceAccountTokenCreator` on the backend SA (the same grant
> the image-pipeline test relies on): `storage.buckets.{create,delete,get,
> update,getIamPolicy,setIamPolicy}` and `storage.objects.{list,delete}` on
> the project, for scratch-bucket lifecycle. **Terraform does not grant
> these** — only `roles/storage.objectAdmin` on the separate Terraform state
> bucket — so this relies on the operator's own broader project-level
> access: `roles/owner` works; **`roles/editor` does not** (confirmed —
> Editor deliberately excludes `storage.buckets.setIamPolicy`/
> `.getIamPolicy`/`.get`/`.update`, the same way it excludes `setIamPolicy`
> on most resource types). `roles/storage.admin` (plus the Token Creator
> grant above) covers everything needed with a narrower blast radius than
> Owner, if that's available instead.
>
> It creates the scratch bucket with soft-delete explicitly disabled (new
> buckets default to 7 days of it, which would leave a "deleted" bucket
> recoverable-but-orphaned for a week — confirmed live on an early version
> of this script before that fix), waits out Cloud Storage's eventually-
> consistent IAM propagation before exercising the newly bound role, then
> runs the direct-SDK-upload, signed-PUT, `get_blob`, and signed-GET code
> paths for real, plus confirms list/overwrite/delete stay denied. Cleanup
> is verified, not just attempted — the script exits non-zero if the
> scratch bucket can't be confirmed gone, even if every functional check
> passed.
>
> **What this does not prove**: same in-process caveat as the image-pipeline
> test above, plus it does not exercise the Firestore expense-receipt
> association — it is a real-GCS IAM integration test for the storage layer
> specifically, not a full-stack receipt test.

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
terraform plan -lock-timeout=5m     # Preview changes
terraform apply -lock-timeout=5m    # Apply changes
```

`-lock-timeout` matters more than it looks: state locking on the GCS backend
is automatic (see [State storage & locking](#state-storage--locking) below),
and without it a second `apply` started while one is already running fails
immediately instead of waiting its turn.

Common reasons to run `terraform apply`:
- Adding a new allowed CORS origin
- Changing Cloud Run memory or CPU limits
- Adding or rotating a secret
- Any other `.tf` file change

Infrastructure is organized into five modules under `terraform/modules/` —
`security`, `storage`, `backend-service`, `observability`, `cost-controls` —
plus a handful of root-level files for providers, variables, and the handful
of resources genuinely shared across modules (the scheduler service identity,
the shared alert notification channel, project metadata). A resource's module
tells you where to look for it; the root files are everything no single module
owns.

### State storage & locking

State lives in the versioned GCS bucket `state_backend.tf` defines
(`made-for-seconds-tf-state`), not on any one machine. A fresh clone only needs:

```bash
cd terraform
terraform init
```

Locking is automatic — the GCS backend takes a lock object for the duration of
a write, so a concurrent `apply` is refused rather than interleaved with
another. There is no separate locking service to provision. If an `apply` is
killed mid-flight the lock can outlive it; `terraform force-unlock <id>` clears
a *genuinely* stale one, but only after confirming no other apply is actually
still running — forcing while one is corrupts state. The lock ID and holder
are visible in the error message, or by reading the `.tflock` object directly:

```bash
gcloud storage cat gs://made-for-seconds-tf-state/terraform/state/default.tflock
```

### Backups & monitoring

- **Firestore**: two managed backup schedules — daily with 7-day retention
  (`google_firestore_backup_schedule.daily`) for fast recovery of recent
  mistakes, and weekly with 14-week retention
  (`google_firestore_backup_schedule.weekly`) so a problem noticed late is
  still recoverable. Firestore caps daily schedules at 7 days and any schedule
  at 14 weeks, which is why depth needs the second schedule rather than a
  longer retention on the first. List with `gcloud firestore backups list`;
  restore with `gcloud firestore databases restore`.
- **Uptime**: a Cloud Monitoring check hits `/api/health` every 15 minutes
  and emails the alert address after ~20 minutes of failures.
- **App errors**: a log-based metric + alert policy
  (`google_logging_metric.backend_errors`) emails the alert address after
  more than 5 ERROR-severity log entries in a 15-minute window.
- **5xx responses**: a log-based metric + alert policy
  (`google_logging_metric.backend_5xx`) emails the alert address after more
  than 5 HTTP 5xx responses in a 15-minute window, using Cloud Run's
  automatic per-request logs.
- **Weekly usage report**: `google_cloud_scheduler_job.weekly_usage_report`
  hits `/api/internal/usage/weekly-report` every Monday at 13:00 UTC. The
  endpoint aggregates the trailing 7 days of Cloud Run request logs (total
  requests, distinct visitor count, top request paths, error count) and
  emails the summary to `alert_email` — the same address used for the
  budget/uptime/error alerts above. The report is aggregate-only: no IP
  addresses or per-request rows ever appear in the email or get stored
  anywhere new — they're only counted in memory while the report is built.
- **Stripe webhook idempotency**: `processed_events` documents carry a `ttl`
  timestamp (30 days from creation) and a matching Firestore TTL policy
  (`google_firestore_field.processed_events_ttl`) deletes them automatically.
  30 days matches Stripe's own event-retention window — the List Events API
  (and CLI/Dashboard manual replay, which relies on it) only returns events
  created in the last 30 days, so that's the real ceiling a replayed event
  needs the reservation doc to survive, not Stripe's 24h idempotency-key
  minimum. The collection doesn't grow unbounded against the 1 GiB free-tier
  ceiling as a result. TTL-triggered deletes aren't covered by Firestore's
  free delete quota (unlike manual deletes) and are billed at $0.01 per 100K
  documents — negligible at this project's webhook volume, but a real,
  deliberately accepted cost rather than a free-tier feature. The `ttl` field
  also has its automatic single-field index disabled (`index_config {}`),
  since nothing ever queries by it.

### Receipt & financial-record recovery

Expense receipts are tax records. Two things protect them, and they cover
different failures:

| Protection | Covers | Where |
|---|---|---|
| Bucket retention policy, 7 years | Deletion or replacement of the object, by anyone — application bug, compromised runtime, or an admin with `objectAdmin` | `terraform/modules/storage/buckets.tf` |
| Object versioning | Overwrites, by keeping the superseded generation | same file |
| Firestore backups, daily 7d + weekly 14w | Loss of the *metadata* — which expense a receipt belongs to, for how much, on what date | `terraform/modules/storage/firestore.tf` |
| `receipt_associations` records | Loss of the *association* when a recipe-attached receipt is detached or its recipe deleted — written before the link goes away, so it does not expire with a backup | `backend/app/services/receipt_ledger.py` |

The retention policy is what makes the seven-year claim real. Versioning alone
does not: a caller holding `objectAdmin` can delete every generation
explicitly. GCS enforces retention itself, so no IAM grant defeats it.

**The application never deletes a receipt.** `DELETE /api/admin/recipes/{id}/receipts`
unlinks — it removes the URL from the recipe and leaves the object. Deleting a
recipe likewise keeps its receipts. Both would fail against the retention
policy anyway; unlinking makes that the intended behaviour rather than a
swallowed error.

**Restoring a receipt whose link was removed:**

Start with the association record — it says what the object was without needing
a backup, and unlike a backup it does not expire:

`gcloud` has no document-level read/list command — `firestore` only covers
`backups`/`databases`/`export`/`import`/`indexes`. A single REST `list` call
isn't a safe substitute either: Firestore paginates past the first page via
`nextPageToken`, so a bare `curl` silently omits anything beyond page one once
the collection grows past it — exactly the kind of gap that shouldn't exist in
a recovery procedure. Use the same client library the backend already depends
on (`google-cloud-firestore` — `backend/requirements.txt`); `.stream()`
handles pagination internally, so there's no token loop to get wrong:

```bash
pip install google-cloud-firestore  # if not already available locally
python3 -c "
from google.cloud import firestore
for doc in firestore.Client(project='made-for-seconds').collection('receipt_associations').stream():
    print(doc.id, doc.to_dict())
"
```

Or browse it directly: [GCP console → Firestore → Data](https://console.cloud.google.com/firestore/databases) → `(default)` → `receipt_associations` — the console's viewer paginates for you.

Each record carries the receipt URL, the recipe's id/title/slug/categories as
they were, why it was detached (`unlinked`, `recipe_deleted`,
`replaced_by_update`), when, through which interface, and which admin did it.
Records are append-only: nothing updates or deletes them.

Receipts reached through the **expenses** ledger never need this — an expense is
voided rather than deleted, and `expense_revisions` keeps the full history.
`receipt_associations` covers the narrower case of receipts attached straight to
a recipe, where the recipe document was previously the only record.

The association record names the object; finding it still means knowing where
to look. Receipts live in two places, not one: recipe receipts sit at the
bucket root (`admin_upload_recipe_receipt` in `backend/app/routes/admin.py`),
expense receipts sit under `receipts/` (`backend/app/routes/expenses.py`,
`backend/app/mcp_server.py`). Listing only `receipts/` misses every recipe
receipt, so check both:

```bash
# The object never went anywhere — it's just a question of which prefix
gcloud storage ls gs://made-for-seconds-receipts/
gcloud storage ls gs://made-for-seconds-receipts/receipts/
```

Re-attach the URL through the admin UI or MCP and that's the whole fix — the
object was never touched, only the record pointing to it was.

**Restoring an overwritten generation:**

The retention policy blocks writing a new generation over an object's
current name just as it blocks deleting it — from GCS's side, both are
"replace the retained object," so `cp` onto the same name gets the same 403
a `rm` would. Restore the generation you want to a *new* name instead, then
repoint whichever Firestore field references it — a recipe's `receipt_urls`
array entry, or an expense's `receipt_url` — at that new name. The
generation you didn't want stays exactly where it is; nothing about
retention lets you remove it either, which is the point.

```bash
gcloud storage ls -a gs://made-for-seconds-receipts/receipts/FILENAME
gcloud storage cp gs://made-for-seconds-receipts/receipts/FILENAME#GENERATION \
  gs://made-for-seconds-receipts/receipts/restored-FILENAME
```

(Drop the `receipts/` prefix for a recipe receipt — same command, bucket
root instead.)

**Restoring the metadata** (which expense the receipt belonged to) restores
into a *new* database — Firestore will not restore over a live one:

```bash
gcloud firestore backups list --location us-central1 --project made-for-seconds
gcloud firestore databases restore \
  --source-backup=projects/made-for-seconds/locations/us-central1/backups/BACKUP_ID \
  --destination-database=restore-scratch \
  --project made-for-seconds
```

Read the expense document out of `restore-scratch`, re-attach the receipt URL
through the admin UI or MCP, then delete the scratch database. Restoring is
therefore a manual, deliberate operation — which is the right shape for
something that should happen approximately never.

> **Locking the retention policy — irreversible, owner's call.**
> The policy ships **unlocked**, so `terraform apply` can still shorten or
> remove it. Locking it makes the seven years unconditional: it cannot be
> shortened or removed by anyone, including you, including Google support, and
> the bucket cannot be deleted until its last object ages out. Storage bills
> grow monotonically for seven years as a direct consequence.
>
> That is a genuine trade of reliability and cost against tamper-evidence, and
> it should be made deliberately rather than inherited from a default. When you
> decide to make it:
>
> ```bash
> gcloud storage buckets update gs://made-for-seconds-receipts \
>   --lock-retention-period --project made-for-seconds
> ```
>
> Then set `is_locked = true` in `buckets.tf` so Terraform's view matches
> reality — the field is not reversible there either once the API call lands.

#### What the backup schedules cost

Firestore backup storage has **no free-tier allowance** — unlike the 1 GiB of
live Firestore storage, every byte of backup is billed from the first one. This
is a deliberate, approved recurring charge, not an oversight, so the arithmetic
is written down here rather than left as "cents".

Backups are **full copies, not incremental**, and each is billed for the
fraction of the month it is retained. That works out to the same number as
counting concurrent copies at steady state:

| Schedule | Retention | Copies held | Cost per GiB of live DB |
|---|---|---|---|
| Daily (pre-existing) | 7 days | 7 | ≈ $0.21 /mo |
| Weekly (added here) | 14 weeks | 14 | ≈ $0.42 /mo |
| **Total** | | **21** | **≈ $0.63 /mo** |

Rate is $0.00004 per GiB-hour (≈$0.029 per GiB-month; Google's published table
rounds to $0.03). The **incremental** cost of this change is the 14 weekly
copies — the 7 daily ones were already being paid for.

Because that scales with database size, the useful number is the bound: live
Firestore storage stays inside its 1 GiB free allowance at this scale, and at
1 GiB the whole backup bill is **≈$0.63/month**. Realistic today is far less —
a recipe/expense database of a few MiB costs low single-digit cents. Measure the
actual size before assuming:

```bash
gcloud monitoring time-series list \
  --project made-for-seconds \
  --filter 'metric.type="firestore.googleapis.com/document/storage_bytes"' \
  --format 'value(points[0].value.int64Value)'
```

Not covered by the table, and deliberately left for the aggregate cost model
rather than guessed at here: restore operations (billed separately, per GiB
restored, only when a restore actually happens), and the scratch database a
restore lands in (billed as a normal database for as long as it exists — delete
it when done).

> **Approved:** the recurring weekly-backup charge is accepted at the bound
> above. The 14-week depth is load-bearing *only* until receipts carry their own
> durable association record; once that ships, this depth should be
> re-evaluated rather than kept by inertia.

### Cost circuit breaker

The project cannot quietly bill past `monthly_budget_amount` (default **$15**).

| Spend | What happens |
|---|---|
| Forecast to exceed 100% | Early-warning email — GCP projects month-end spend from run-rate, so this lands days before you actually cross. No shutdown. |
| 50% / 80% actual | Warning emails. |
| 100% actual | The `budget-killer` function **revokes public access** — it removes `allUsers` from the backend's `roles/run.invoker` binding. Visitors get 403, no instances start, request billing stops. A dedicated *"MFS site DOWN — budget cap hit"* CRITICAL alert fires, distinct from the generic uptime alert, so you know it was the breaker and not an outage. |
| 1st of month, 08:00 UTC | The `budget-breaker-reset` scheduler job re-adds `allUsers`. Idempotent — a no-op in normal months. |

Only public request traffic is stopped. Firestore, GCS, and egress keep billing,
but at this scale they are cents. The breaker deliberately does **not** detach
the billing account.

Revoking the invoker binding means Cloud Run rejects at the edge with no CORS
headers — visitors' browsers see an opaque failed fetch, identical to the site
being down for any other reason. The trip and reset also publish/clear a
`status.json` object in the public images bucket (`STATUS_BUCKET` on both
functions, `terraform/modules/cost-controls/billing_function/main.py`) so the
frontend (`src/lib/site-status.ts`, wired via `VITE_STATUS_URL` above) can
confirm a deliberate pause instead of guessing. Best-effort on both sides —
a GCS hiccup never blocks the actual revoke/restore, and the frontend already
treats a missing or stale file as "cannot confirm," never as proof.

> **Why not scale to zero?** In Cloud Run v2, `max_instance_count = 0` is
> proto3's default, so it serializes as *unset* and the API applies its default
> cap instead. It does not stop the service — in this project it silently raised
> the cap from 1 to 20, so a "kill" would have increased spend exposure 20×.
> There is no value of `max_instance_count` meaning "serve nothing". Revoking the
> invoker binding is also a single `setIamPolicy` call, so it creates no revision
> and avoids the image-resolution and `actAs` permission chain that a service
> update requires.

Recover early, without waiting for the 1st:

```bash
gcloud scheduler jobs run budget-breaker-reset --location us-central1 --project made-for-seconds
```

> Note: `terraform/modules/backend-service/cloud_run.tf` declares `max_instance_count = 1`, so a `terraform apply`
> while the breaker is tripped will also restore service — silently. If you get
> the breaker alert, find out why before applying.

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

Stripe, Resend, and the subscriber JWT secret stay manual — there is no
rotation API for the first two, and the JWT secret is self-issued but
`subscriber_auth.py` verifies against a single key with no multi-key support,
so rotating it invalidates every outstanding subscriber session (a real future
improvement, not attempted here). Recommended cadence: Stripe/Resend keys
opportunistically (a suspected leak, an offboarded team member), the JWT
secret only when you're prepared for every subscriber to need a fresh
cancellation link.

### Secret version pruning

Every `echo -n ... | gcloud secrets versions add` above leaves the old version
in place — nothing before this story ever removed one. Secret Manager bills
per active (non-destroyed) version above a 6-version free allowance **shared
across the whole billing account**, not per secret, so an unbounded count on
even one secret (`admin-emails` alone once reached 5 from a single day of
testing) eats into every other secret's free allowance too.

**Mechanism.** A dedicated Cloud Function (`secret-pruner`, its own service
account, no relation to `mfs-backend`) runs weekly via Cloud Scheduler
(`secret-version-pruner`, 05:00 UTC Monday — no functional dependency on
anything else, just spaced away from `weekly-usage-report`'s Monday 13:00 UTC
slot and `budget-breaker-reset`'s monthly one). For every
configured secret it keeps the newest 2 `ENABLED` versions — and anything at
or above that "floor," even a `DISABLED` version — and destroys everything
older. `secretmanager.versions.destroy` is deliberately never reachable from
`mfs-backend`; only `secret-pruner` holds it, and only on the application
secrets (`terraform/modules/secret-maintenance/secret_pruner.tf`).

**Dry-run by default.** A secret is only actually pruned if its `secret_id`
appears in the `secret_pruner_write_enabled_ids` tfvar (empty list by
default). Every other configured secret still runs the full selection logic
and logs exactly what it *would* destroy — check Cloud Logging for the
`secret-pruner` Cloud Run revision after a scheduled run, or invoke it by hand:
```bash
gcloud scheduler jobs run secret-version-pruner --location us-central1 --project made-for-seconds
```

**Recovery — do this before allowlisting any real secret.** Every destroy
sets `version_destroy_ttl = 604800s` (7 days) on the secret first
(`modules/security/secrets.tf`), so a "destroy" call only disables the version
immediately; permanent deletion happens a week later. A dedicated canary
secret (`secret-pruner-canary`, `terraform output secret_pruner_canary_id`)
exists solely to prove this end-to-end without ever risking a real secret.

Step 0 (automated, do this first):

```bash
cd backend
python scripts/smoke_test_secret_pruner.py --project made-for-seconds
```

This invokes the real deployed function through a real OIDC-authenticated
call (impersonating `secret-pruner`, the same identity Cloud Scheduler uses)
and, directly against the Secret Manager API, adds its own throw-away
canary versions, destroys one as `secret-pruner`, confirms the pruning
algorithm doesn't re-select it, restores it as the operator, and cleans up
after itself. It proves the IAM grant, the OIDC audience, the deployed
function's packaging, and the delayed-destroy/re-selection-avoidance logic
all work against the real API — everything test_main.py's mocked suite
structurally can't. It does **not** touch `secret_pruner_write_enabled_ids`
or run `terraform apply` — see the script's own docstring for why. Only after
this passes does the manual write-path drill below make sense to run.

Steps 1-5 (manual, exercises the actual deployed *write* path via the real
allowlist):

1. Add a couple of extra versions the normal out-of-band way:
   `echo -n "v2" | gcloud secrets versions add secret-pruner-canary --data-file=-`
   (repeat for a v3).
2. Add `"secret-pruner-canary"` to `secret_pruner_write_enabled_ids` and
   `terraform apply`.
3. Run the function (command above), then confirm the oldest version moved to
   `DISABLED` with a `scheduled_destroy_time`:
   `gcloud secrets versions list secret-pruner-canary`
4. Restore it: `gcloud secrets versions enable VERSION --secret=secret-pruner-canary`
   — this cancels the scheduled destruction. `secret-pruner`'s own role does
   **not** grant `.enable`, by design: a bug in the thing that destroys
   versions must not also compromise the thing that undoes its mistakes.
   Confirm the value is still readable:
   `gcloud secrets versions access VERSION --secret=secret-pruner-canary`
5. Remove `"secret-pruner-canary"` from `secret_pruner_write_enabled_ids` and
   `terraform apply` again. Skipping this step leaves the canary allowlisted
   for real, so next week's scheduled run destroys the very version you just
   restored — `gcloud functions describe secret-pruner --region us-central1
   --gen2 --format="value(serviceConfig.environmentVariables.WRITE_ENABLED_SECRET_IDS)"`
   should come back empty (or list only whatever real secrets you've since
   allowlisted) before you consider the drill done.

Only once that full cycle succeeds should a real secret's id go into
`secret_pruner_write_enabled_ids`.

**If pruning stops, or a destroy fails.** Three separate alert policies, not
one policy with several conditions — Cloud Monitoring requires a
`condition_matched_log` ("LogMatch") condition to be the *only* condition in
its policy, confirmed against the Monitoring alerting API docs, so the two
log-based conditions below each get their own policy, plus a third for the
Scheduler-level failure:

- **Anomaly** (`Secret pruner: non-ENABLED latest version`) — `secret-pruner`
  skips a secret entirely, rather than guessing, whenever that secret's
  numerically latest version is not `ENABLED` — usually a rotation that added
  a version and never enabled it. `gcloud secrets versions list <secret-id>`
  to see why. Version numbers never change, so the fix has to be one of:
  enable that *exact* version if its value is actually good (`gcloud secrets
  versions enable <version> --secret=<id>`), or add a fresh version on top of
  it if it's bad (`gcloud secrets versions add <id> --data-file=-`) so a
  newer enabled version becomes the latest — disabling the stray version
  again, or enabling some *other*, older version, does nothing: neither
  changes which version is numerically newest. Pruning resumes for that
  secret once its latest version is `ENABLED` again.
- **Error** (`Secret pruner: list/destroy failure`) — a secret couldn't be
  listed, or a specific version failed to destroy (e.g. an etag conflict
  from a concurrent change). This also makes the function return a non-2xx
  response, so Cloud Scheduler's own `retry_config` gets a few immediate
  attempts to recover before the alert really means something's stuck.
  Check the `secret-pruner` Cloud Run revision's logs for the
  `SECRET_PRUNE_ERROR` line naming the secret and the underlying error.
- **Scheduler execution failed** (`Secret pruner: Scheduler execution
  failed`) — the triggered HTTP call itself never reached the function's
  code at all (OIDC token minting, IAM, routing, a cold-start timeout), so
  neither marker above had a chance to fire. Backed directly by Cloud
  Scheduler's own `AttemptFinished` log records (`condition_matched_log`,
  no metric involved), filtered to exclude `debugInfo:"UNREACHABLE_5xx"` —
  that specific code means the function *was* reached and ran, just
  returned a 500, which is the **Error** alert's job above, not this one.
  Confirmed live: a `SECRET_PRUNE_ERROR` failure makes Cloud Scheduler log
  its own `severity=ERROR` entry for the same request with
  `debugInfo = "URL_UNREACHABLE-UNREACHABLE_5xx..."`, so without this
  exclusion every application failure would raise both alerts and this
  one's "never reached the function" framing would be actively wrong for
  that case. Check `gcloud logging read 'resource.type="cloud_scheduler_job"
  resource.labels.job_id="secret-version-pruner"'` for the failing attempt's
  `status`/`debugInfo`.

  **Known gap, accepted rather than worked around:** none of these three
  detect a Scheduler job that's silently paused or disabled (zero attempts
  of any kind — no success, no failure, nothing for any metric to see).
  Verified against the live Monitoring API that every mechanism capable of
  expressing "no data for N days" — `condition_absent`, MQL's `absent_for`,
  and PromQL's `absent_over_time` — rejects windows longer than ~25 hours
  for a log-based metric, and this job only legitimately produces data once
  a week. Closing that gap would mean standing up a second, more-frequent
  heartbeat job — real new infrastructure for a failure mode that only a
  manual `gcloud scheduler jobs pause` or console action can trigger in the
  first place. If pruning seems to have silently stopped and none of the
  three alerts above have fired, check manually: `gcloud scheduler jobs
  describe secret-version-pruner --location us-central1` (state should read
  `ENABLED`).

All three notify the same email channel.

**Cost.** Measured against the live project (`gcloud secrets versions list`
for all 5 pruner-managed secrets, `admin-emails` through
`subscriber-jwt-secret`, plus the 2 unrelated Cloud Build OAuth secrets that
share the same free allowance). Secret Manager bills $0.06 per active
(non-destroyed) version-month above the shared 6-version allowance.

Instagram publishing is deprecated for now (incomplete feature, and its
`instagram-token-refresh` scheduler job was failing) — `instagram_access_token`
is blanked in tfvars, which destroys that secret, its bindings, and that
scheduler job entirely, in the same apply that creates secret-pruner's own
job. Net effect on Cloud Scheduler: **one job removed, one added, still 3
jobs total** — the free allowance, not a 4th paid job. This story's Scheduler
line is therefore **$0/month**, not the $0.10/month estimated in earlier
drafts of this doc, written when Instagram's job was still going to coexist
with secret-pruner's.

| Scenario | Active versions | Secret Manager (over free 6) | + Scheduler | Total |
|---|---|---|---|---|
| Today, before this merges | 15 (13 across the original 6 managed secrets, including instagram-access-token, + 2 OAuth) | $0.54/mo | — | $0.54/mo |
| Immediately after merge/apply | 15 (instagram-access-token's secret+version gone, +1 canary seed version — nets to no change) | $0.54/mo | $0/mo (3 jobs, still free) | $0.54/mo |
| Steady-state (Step 0 has run at least once, drill done, real secrets allowlisted) | 14 (5 secrets × 2 kept + 2 OAuth + 2 canary) | $0.48/mo | $0/mo | $0.48/mo |
| Spike (all 5 managed secrets rotate the same week) | ~19 (5 × [2 kept + 1 aging out over its 7-day `version_destroy_ttl`] + 2 OAuth + 2 canary) | ~$0.78/mo | $0/mo | **~$0.78/mo** |

None of the 5 remaining managed secrets auto-rotate — they only grow when a
human manually rotates one, which the "spike" row already treats as the
worst case (all five in the same week). Without Instagram's independent
weekly schedule in the mix, every row above is otherwise a clean, static
number except for one remaining source of overhead:

The canary secret carries **two different kinds of overhead, not one**, and
the transient half is bigger than it first looks. `_cleanup_and_verify_healthy`
(`backend/scripts/smoke_test_secret_pruner.py`) converges the canary to 2
enabled versions — the same floor the real algorithm protects everywhere
else — and since Step 0 is the mandatory first move before the drill, that
2nd enabled version is a **permanent** addition from the first time anyone
runs it (already priced into the steady-state row above). On top of that
permanent 2, every run also *destroys* some number of disposable versions,
each of which then sits disabled-but-active for its own 7-day
`version_destroy_ttl` — and that number isn't a flat "+1":

- The canary's very **first** ever cleanup starts from just the Terraform
  seed version, adds 3 test versions, and settles to 2 enabled by destroying
  **2** (the seed plus the oldest test version) — both go active-but-pending
  for 7 days.
- **Every run after that** starts from an already-2-enabled canary, adds 3
  more, and destroys **3** to get back to 2 — one more than the first run,
  because there's no seed version left to also sweep up.
- Because that pending window is 7 days, running the smoke test **more than
  once within a week** doesn't reset anything — each run's pending versions
  stack on top of whatever's still pending from the runs before it.

| Scenario | Canary active versions | Total active | Billable | Total |
|---|---|---|---|---|
| Baseline (7+ days since any run) | 2 | 14 | $0.48/mo | $0.48/mo |
| Normal (one run, within its own 7-day window) | 4 (2 enabled + 2 pending) | 16 | $0.60/mo | $0.60/mo |
| Repeated (3 runs inside one week, e.g. iterating on a fix) | 10 (2 enabled + 2 + 3 + 3 pending) | 22 | $0.96/mo | $0.96/mo |
| Worst-reasonable concurrent (repeated runs *and* all 5 managed secrets rotating the same week) | 10 | 27 | $1.26/mo | **$1.26/mo** |

All four rows are transient peaks, not standing costs — every one clears back
to the $0.48/mo baseline once 7 days pass since the last contributing event
(the last smoke-test run, or the last rotation), and each bills a full-month
rate as a conservative ceiling rather than the lower prorated amount an
actual 7-day window would cost.

All of this is small next to the project's real backstop for its dominant
cost driver: the $15/month budget breaker (see
[Cost circuit breaker](#cost-circuit-breaker)) — but that breaker only stops
public Cloud Run request traffic, same as it always has; it does not cap
Secret Manager, Scheduler, or anything else this story touches. There is no
mechanism in this project that puts a hard ceiling on the numbers in this
table — they're bounded by the modeled scenarios above and by the operator
noticing the alert email, not by anything automatic.

**If Instagram publishing is re-enabled later:** setting `instagram_access_token`
back in tfvars recreates the secret and its weekly-rotating scheduler job,
which also makes secret-pruner a genuine 4th (paid, ~$0.10/month) Scheduler
job again, and reintroduces the "never settles at a clean 2" per-secret
overhead this doc used to describe for it — re-derive the numbers above
rather than assuming they still hold.

### Removing an optional secret

This applies to `redis_url`, `stripe_secret_key`, `stripe_webhook_secret`,
`subscriber_jwt_secret`, and `resend_api_key` — the five secrets
`local.optional_secret_env` in `modules/backend-service/cloud_run.tf` injects
as Cloud Run env vars. **Not** `instagram_access_token`: that one is never
injected there (see the comment above `INSTAGRAM_USER_ID` in `cloud_run.tf`
— the backend reads it from Secret Manager at runtime instead, specifically
so a rotated token doesn't need a redeploy to take effect). Blanking it only
destroys the secret, its accessor/versionAdder bindings, and the token-refresh
scheduler job — Cloud Run's revision never referenced it, so there's no
race: Instagram publishing just stops working until the token is set again,
no special procedure needed.

For the five that follow, blanking the tfvar and running a plain `terraform
apply` is **not safe**. `modules.tf`'s `time_sleep.wait_for_secret_accessors`
only protects the opposite direction — filling in a blank secret. On a
removal, Terraform destroys the secret and its accessor binding first, then
Cloud Run's revision is updated to stop referencing it — `-target` doesn't
help split this into two applies either, since backend-service's plan pulls
in module.security's pending destroy as a dependency either way. Any instance
start that lands in that window — a scale-to-zero cold start, or Cloud Run
replacing an existing instance for its own reasons (host maintenance, a
crash) — resolves a secret reference that no longer exists and fails.

Forcing a warm instance (`--min-instances=1`) only lowers how often that
window gets hit; Cloud Run doesn't guarantee an existing instance is never
replaced, so it's a reduction, not a fix. The only way to actually close the
window is to make sure nothing references the secret *before* it's
destroyed, which needs a temporary code change, not just a tfvar change:

1. In `modules/backend-service/cloud_run.tf`, temporarily add the secret
   you're removing to `local.optional_secret_env`'s exclusion — the
   comprehension already ends in a single `if`, so extend that condition
   rather than appending a second `if` (two `if` clauses on one `for` is
   invalid HCL):
   ```hcl
   ] : entry if entry.secret_id != null && entry.name != "RESEND_API_KEY"
   ```
   Leave the tfvar as it is. Apply:
   ```bash
   cd terraform && terraform apply -lock-timeout=5m
   ```
   This produces a new Cloud Run revision that no longer references the
   secret. `module.security` is untouched by this apply — the secret and its
   accessor binding still exist, so nothing about this step is destructive.
2. Confirm the new revision holds all traffic before touching Secret Manager
   — `gcloud run revisions list` shows readiness, not traffic split or
   instance counts, so it can't confirm this:
   ```bash
   gcloud run services describe mfs-backend --region us-central1 \
     --project made-for-seconds --format="value(status.traffic)"
   ```
   Confirm the new revision is the only one listed at 100%. That's the
   condition that actually matters here — Cloud Run only starts a fresh
   instance of a revision to serve traffic routed to it, so a revision sitting
   at 0% traffic won't be asked to cold-start regardless of how many (or how
   few) of its instances are still idling down in the background.
3. Revert the temporary exclusion, blank the tfvar, and apply again. The
   revision confirmed in step 2 holds all traffic and doesn't reference this
   secret, so its destruction — whenever Terraform gets to it, with or without
   the 180s wait — cannot break a running or restarting instance: nothing
   receiving traffic has anything left to reference.

Steps 1–2 are the part that actually matters; skipping straight to blanking
the tfvar is what reintroduces the race.

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
| `VITE_STATUS_URL` | No | `https://storage.googleapis.com/<gcp_project_id>-images/status.json` — the budget breaker's published cost-cap signal (see [Cost circuit breaker](#cost-circuit-breaker)). Omitting it just means an outage can never be *confirmed* as a deliberate pause; the banner still shows, with more cautious wording. |

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

**Instagram publishing** (currently deprecated — not a complete feature, and
its token-refresh scheduler job was failing; `instagram_access_token` is
blanked in tfvars, which tears down the secret and that job entirely — see
[Secret version pruning § Cost](#secret-version-pruning) for what re-enabling
it would change). The tools and code below still exist and work; they're
just unreachable without a token configured:

`publish_recipe_to_instagram(slug)` posts the
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
| Cloud Storage | 5 GB-months storage (US regions) · 100 GB/mo egress from North America | Minimal for images + receipts |
| Artifact Registry | 0.5 GiB storage-month, aggregated per billing account across every repository (confirmed via the live Cloud Billing Catalog API: SKU 8502-299A-ABAF prices in `GiBy.mo`, first tier free up to `startUsageAmount: 0.5`) | Two repositories share this allowance: `mfs` (the backend's own image, cleanup-policy-managed to ≤ 5 tagged) and `gcf-artifacts` (auto-created build output for every Gen2 Cloud Function). See below — this predates secret-pruner's own deploy, doesn't cross the allowance once measured correctly in GiB, but leaves thin headroom, and `gcf-artifacts` has no cleanup policy at all. |
| Cloud Build | 2,500 build-min/mo | ~2 min per backend deploy |
| Identity Platform | 49,999 MAU/mo | 1 admin user |
| Cloud Logging | 50 GiB/mo ingestion | Minimal log volume |
| Secret Manager | 6 active *versions* free (aggregated per billing account, not per secret) · 10K access/mo | Weekly pruning (see [Secret version pruning](#secret-version-pruning)) keeps this near the free allowance instead of growing unbounded |
| Cloud Scheduler | 3 free jobs per billing account | 3 jobs in use (weekly usage report, secret pruning, budget-breaker reset) — all free. Instagram's token-refresh job would have been a genuine 4th (~$0.10/month) had it stayed; see [Secret version pruning § Cost](#secret-version-pruning) for what re-enabling Instagram would change |

### Artifact Registry: gcf-artifacts has no cleanup policy

**The free allowance is 0.5 GiB (536,870,912 bytes), not 0.5 GB.** Confirmed
against the live Cloud Billing Catalog API (`services/149C-F9EC-3994/skus/
8502-299A-ABAF`, "Artifact Registry Storage"): `pricingExpression.usageUnit`
is `GiBy.mo` ("gibibyte month"), and the first tier is `$0` up to
`startUsageAmount: 0.5`. An earlier version of this doc treated that as 0.5
decimal GB (500,000,000 bytes) and concluded a single new image would cross
it on day one — wrong, by exactly the GB/GiB gap (536.87 vs. 500 decimal MB,
a ~7% difference that happened to matter here because the real number was
this close to the edge either way).

`gcloud artifacts repositories describe` prints "Repository Size" as decimal
MB (bytes ÷ 1e6), confirmed by comparing its human-readable output against
the underlying byte math below — that display is not itself part of the
API response body. Measured live, right before secret-pruner's own first
deploy (`gcloud functions describe secret-pruner` still 404s as of this
writing):

| Repository | Reported size |
|---|---|
| `mfs` | 339.343 MB |
| `gcf-artifacts` | 149.411 MB |
| **Combined** | **488.754 MB** ≈ 0.4552 GiB |
| Free allowance | 536.871 MB ≈ **0.5 GiB** |
| **Headroom today** | **≈ 48 MB** |

So today, pre-deploy, this project is **under** the allowance with room to
spare — not already over it as an earlier draft claimed. That doesn't make
this a non-issue; it makes it a "how much longer" question instead of an
"already broken" one, and the honest answer is: not much longer, for two
separate reasons.

- **`gcf-artifacts` carries no cleanup policy at all** — confirmed via
  `gcloud artifacts repositories describe gcf-artifacts`, no
  `cleanupPolicies` field, unlike `mfs`'s three (keep 5 tagged, delete
  untagged after 1 day, delete anything else tagged — and even that only
  bounds `mfs` by image *count*, not by size; a future backend image could
  grow larger than today's and still pass the same "≤5 tagged" policy).
  Every image budget-killer and budget-resetter have ever built is still
  sitting there: **16** versioned artifacts (8 budget-killer + 6
  budget-resetter images, plus one ~25.4 MB build-cache image for *each*
  function — every Gen2 build pushes both a deployable image and a separate
  `.../cache` image, confirmed live for both existing functions) spanning
  `2026-06-16` to `2026-08-27`, none ever removed. Adding secret-pruner as a
  third function redeploying on the same never-cleaned repository adds a
  third unbounded growth source, not just one more image — and its first
  deploy alone adds *two* new artifacts (its own image, plus its own cache),
  the same as every deploy before it.
- **But "how much each new artifact actually adds" is smaller than it
  looks, and not knowable precisely in advance.** `gcloud artifacts docker
  images list --format=json` reports each artifact's own
  `metadata.imageSizeBytes` — summed across all 16 artifacts in
  `gcf-artifacts` today, that's **≈411 MB** (411,410,515 bytes exactly).
  The repository's actual measured size is **149.411 MB** — barely a third
  of that sum, because Artifact Registry deduplicates shared layers (the
  Python 3.12 buildpack base, the interpreter, common `pip` packages) across
  every artifact in the repository. `metadata.imageSizeBytes` is each
  artifact's *full logical size*, not its marginal contribution to the
  repository's billed total, and there's no API field that reports the
  latter directly — it can only be observed as a before/after delta on the
  repository itself.

That cuts both ways for secret-pruner's first deploy, which adds **two**
new artifacts (image + cache), not one:

| Scenario | Basis | Two new artifacts' real contribution | Combined after deploy | Crosses 0.5 GiB (536.871 MB)? |
|---|---|---|---|---|
| Worst case — shares nothing | Image, full reported size same order as budget-killer/-resetter's own (~25-27 MB) + cache (~25.4 MB, consistently observed for both existing functions) | ~50-52 MB | ~539-541 MB | **Yes** — over by ~2-4 MB (≈$0.0002-0.0004/month at $0.10/GiB-month over the free tier — real, but a fraction of a cent) |
| Observed-average case — shares layers like the existing two functions do | 149.411 MB ÷ 16 artifacts already in the repo ≈ 9.3 MB/artifact × 2 new artifacts | ~19 MB | ~507 MB | No — ~30 MB headroom left |

The worst case and the observed-average case now disagree on whether this
crosses the allowance — the earlier version of this doc concluded "either
way, no," which held only when a single new artifact was priced in. With
the second artifact (the cache image every deploy also creates) counted,
the worst case is a real possibility, not one ruled out by the math, even
though it amounts to a fraction of a cent if it happens. What it does do
either way is leave thin headroom behind it — 0 to ~30 MB, shared across
three functions' worth of future redeploys with nothing ever cleaning up
after any of them, on a project where any of budget-killer, budget-resetter,
or secret-pruner could plausibly redeploy again within weeks (a dependency
bump, a bug fix). This is why the fix below is written as a prerequisite,
not a suggestion to revisit later.

**Rollout prerequisite — pick one before running `terraform apply` for this
story:**

1. **Apply the cleanup policy first (recommended).** `gcf-artifacts` is a
   platform-auto-managed repository (labeled `goog-managed-by:
   cloudfunctions`, never declared as a `google_artifact_registry_repository`
   resource anywhere in this codebase), so importing it into Terraform state
   carries real risk of a subsequent `terraform apply` fighting Cloud
   Functions' own management of it. `gcloud artifacts repositories
   set-cleanup-policies` sets a cleanup policy on an existing repository
   without requiring Terraform to own it:

   ```bash
   cat > /tmp/gcf-artifacts-cleanup.json <<'EOF'
   [
     {
       "name": "keep-3-most-recent-per-function",
       "action": {"type": "Keep"},
       "mostRecentVersions": {"keepCount": 3}
     },
     {
       "name": "delete-older-than-30-days",
       "action": {"type": "Delete"},
       "condition": {"olderThan": "30d"}
     }
   ]
   EOF

   gcloud artifacts repositories set-cleanup-policies gcf-artifacts \
     --location=us-central1 --project=made-for-seconds --dry-run \
     --policy=/tmp/gcf-artifacts-cleanup.json
   ```

   `--dry-run` does **not** show results in `gcloud artifacts docker images
   list` — dry runs execute asynchronously on a background job and Google
   documents results taking approximately a day to appear, surfaced only
   through Data Access audit logs with `validateOnly=true`, not through the
   image listing (confirmed against Artifact Registry's own cleanup-policy
   docs). To actually see what a dry run marked for deletion:

   ```bash
   # One-time: Data Access audit logs are off by default for this service.
   # Console: IAM & Admin > Audit Logs > Artifact Registry > enable "Data Write".

   # Wait ~1 day after the --dry-run call above, then:
   gcloud logging read \
     'protoPayload.serviceName="artifactregistry.googleapis.com" AND
      protoPayload.request.parent="projects/made-for-seconds/locations/us-central1/repositories/gcf-artifacts/packages/-" AND
      protoPayload.request.validateOnly=true' \
     --project=made-for-seconds
   ```

   Confirm the `names` field on those entries keeps each function's active
   image plus its intended rollback versions before removing `--dry-run` and
   applying for real:

   ```bash
   gcloud artifacts repositories set-cleanup-policies gcf-artifacts \
     --location=us-central1 --project=made-for-seconds \
     --policy=/tmp/gcf-artifacts-cleanup.json
   ```

2. **Or: proceed without it, but as an explicit decision, not a default —
   and not on the premise that the first deploy is guaranteed free.** Per
   the table above, the worst case for secret-pruner's own first deploy
   already crosses the allowance by a few MB on its own, before any future
   redeploy of anything. If the operator chooses to deploy before applying
   the cleanup policy, that's a deliberate acceptance of two things: a
   small chance of a small immediate overage (a fraction of a cent, if the
   new artifacts don't dedup as well as the observed-average case suggests),
   and the larger, near-certain overage from any redeploy after that with
   nothing ever cleaned up. Record that decision here rather than leaving
   it implicit: _(operator: note the date and choice once made)_.

Either path, this is a live mutation to a resource outside Terraform's
management — not something this story applies unilaterally alongside an
unrelated Terraform-driven PR.

**Rollout acceptance check — run after every future deploy of any of the
three functions, not just secret-pruner's first one**, since this repo has
no automated size alerting (Artifact Registry doesn't export a storage-size
metric to Cloud Monitoring at all — confirmed live: querying
`metricDescriptors` for `artifactregistry.googleapis.com/*` on this project
returns nothing — so there's no free way to alert on this the way the other
cost lines in this doc do; a manual check after each deploy is the only
option that doesn't mean standing up new paid infrastructure to guard a few
cents of exposure):

```bash
gcloud artifacts repositories describe mfs --location=us-central1 --project=made-for-seconds
gcloud artifacts repositories describe gcf-artifacts --location=us-central1 --project=made-for-seconds
```

(Read the printed "Repository Size" line — decimal MB — and compare the sum
against 536.87 MB, not 500 MB.)
