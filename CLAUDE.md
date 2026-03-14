# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Local development
```bash
docker compose up                              # Start all three services
docker compose exec backend python seed.py    # Seed sample data (first time)
docker compose logs -f backend                # Tail backend logs
docker compose restart backend                # Reload after Python changes
docker compose exec backend bash              # Shell into backend container
docker compose down                           # Stop everything
```

### Frontend (outside Docker)
```bash
npm run build    # TypeScript check + Vite build
npm run preview  # Preview production build locally
```

There is no test suite currently.

### Production
```bash
cd terraform && terraform apply   # Apply infrastructure changes
```

## Architecture

### Request flow
The frontend (`src/`) only talks to FastAPI — never directly to Firestore. `src/lib/api-client.ts` is the single fetch wrapper; it injects auth headers and all API calls go through `src/lib/api.ts`.

### Auth — dev vs production split
There are two completely separate auth paths:

- **Dev** (`ENVIRONMENT=development`): `AuthContext` stores a flag in `sessionStorage` when `VITE_DEV_ADMIN_PASSWORD` matches. `api-client.ts` sends `X-Dev-Admin: true` header. `backend/app/auth.py::require_admin` bypasses JWT verification and returns `dev@local`.
- **Production**: `firebase/auth` (Google Identity Platform) issues a JWT. `api-client.ts` attaches it as `Authorization: Bearer <token>`. The backend verifies it via `google.oauth2.id_token.verify_firebase_token` and checks the email against `ADMIN_EMAILS`.

### Backend route split
- `GET /api/recipes`, `GET /api/recipes/{slug}`, `GET /api/categories` — public, no auth
- `GET|POST|PUT|DELETE /api/admin/recipes` — all protected by the `require_admin` FastAPI dependency

Slug is auto-generated from title on recipe creation and never updated afterwards.

### Firestore queries
Search is not natively supported — `GET /api/recipes?search=` fetches all published recipes then filters in Python with a regex. Category filtering uses Firestore's `array_contains`. Both filters can be combined.

### Tailwind CSS v4
Config is CSS-first — no `tailwind.config.js`. All theme customisation lives in `src/index.css` using `@theme`. The plugin is `@tailwindcss/vite` in `vite.config.ts`.

## Key environment variables

| Variable | Where | Purpose |
|---|---|---|
| `VITE_API_URL` | Frontend | FastAPI base URL |
| `VITE_DEV_ADMIN_PASSWORD` | Frontend (local only) | Local admin password |
| `VITE_FIREBASE_*` | Frontend (prod only) | Identity Platform config |
| `ENVIRONMENT` | Backend | `development` enables auth bypass |
| `ADMIN_EMAILS` | Backend | Comma-separated list of admin emails |
| `FIRESTORE_EMULATOR_HOST` | Backend (local only) | Set by Docker Compose automatically |
