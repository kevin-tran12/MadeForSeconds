# MadeForSeconds — Feature Roadmap

## Context
The recipe app is functional but needs polish, more features, and better discoverability. The audience is personal/professional — not a massive community, but should look polished and be SEO-friendly. Content focus stays on recipes only (no blog posts).

---

# Milestone 1: Foundation & Polish (implement now)

## 1.1 Hide Admin Login — Auth at /admin
Remove "Admin login" button from header. Visiting `/admin` unauthenticated shows login form inline.

**Files:**
- `src/components/layout/Header.tsx` — Remove login button, `LoginModal` import, `showLogin` state. Keep "Admin" nav link + "Log out" only when `isAdmin`.
- `src/components/admin/AdminRoute.tsx` — Render `<LoginModal onClose={() => navigate('/')} />` instead of `<Navigate to="/" />`.

## 1.2 About Page
- Create `src/pages/AboutPage.tsx` — Minimal, no personal info. "A personal recipe collection of dishes worth making again and again."
- `src/App.tsx` — Add `/about` route.
- `src/components/layout/Header.tsx` — Add "About" nav link.

## 1.3 Footer — Linktree
- `src/components/layout/Footer.tsx` — Add `https://linktr.ee/madeforseconds` link with icon. Social row + copyright row.

## 1.4 GCS Image Upload

### Terraform
- Create `terraform/storage.tf` — GCS bucket (public read, CORS, uniform access)
- `terraform/service_accounts.tf` — Add `roles/storage.objectCreator` for backend SA
- `terraform/cloud_run.tf` — Add `GCS_BUCKET_NAME` env var

### Backend
- `backend/requirements.txt` — Add `google-cloud-storage`, `python-multipart`
- `backend/app/routes/admin.py` — `POST /api/admin/upload-image`: validates type/size, uploads to GCS, returns public URL. Dev mode: local filesystem fallback.

### Frontend
- `src/lib/api-client.ts` — Add `apiUpload()` for `FormData`
- `src/lib/api.ts` — Add `adminApi.uploadImage(file)`
- `src/components/admin/RecipeForm.tsx` — File input + preview, keep URL input as fallback

## 1.5 UI Polish
- `src/pages/HomePage.tsx` — Decorative hero, "Browse by Category" heading, better spacing
- `src/components/recipe/RecipeDetail.tsx` — Prominent description (pullquote style), icons in metadata, background on ingredients section
- `src/components/recipe/RecipeCard.tsx` — Enhanced hover shadow, spacing tweaks

## 1.6 Servings Scaler
- `src/components/recipe/RecipeDetail.tsx` — +/- buttons on servings, scale ingredient amounts with scale factor, smart number formatting

## 1.7 Share Buttons
- `src/components/recipe/RecipeDetail.tsx` — Copy link (clipboard API), WhatsApp share, native share API fallback

---

# Milestone 2: Interactive Cooking Experience (future)

## 2.1 Cooking Mode / Step-by-Step View
- New component `src/components/recipe/CookingMode.tsx`
- Full-screen overlay triggered from recipe detail page ("Start Cooking" button)
- One instruction step at a time, large text, swipe/arrow to navigate
- Wake Lock API to keep screen on while cooking
- Progress indicator (step 3 of 8)
- Ingredient reference panel (slide-out or bottom sheet)
- Exit button returns to normal recipe view

## 2.2 Interactive Grocery List
- New component `src/components/recipe/GroceryList.tsx` on recipe detail page
- Renders all ingredients as checkable items (checkboxes)
- Checked items get strikethrough styling
- "Clear all" button to uncheck everything
- State stored in `localStorage` keyed by recipe slug so it persists across page loads
- Optional: "Copy to clipboard" as plain text list for pasting into a notes app

## 2.3 Recipe Ratings
- Add `rating` field (1-5 stars, nullable) to recipe model
- Backend: add `rating` to `RecipeCreate`/`RecipeUpdate` models
- Admin-only rating (you rate your own recipes to mark favorites)
- Display stars on recipe cards and detail page
- Sort/filter by rating on recipes page
- **Files:** `backend/app/models.py`, `src/lib/types.ts`, new `StarRating.tsx` component

---

# Milestone 3: Nutrition & Data (future)

## 3.1 Nutrition Info
- Add `nutrition` field to recipe model (object: `calories`, `protein`, `carbs`, `fat`, `fiber` — all optional integers, per serving)
- Backend: add to Pydantic models
- Admin form: collapsible "Nutrition" section with number inputs
- Recipe detail: nutrition facts card (styled like a standard nutrition label)
- **Files:** `backend/app/models.py`, `src/lib/types.ts`, `RecipeForm.tsx`, new `NutritionCard.tsx`

---

# Milestone 4: SEO & Discoverability (future)

## 4.1 Structured Data (Schema.org)
- Add JSON-LD `Recipe` schema to recipe detail pages
- Include: name, image, description, prepTime, cookTime, totalTime, servings, ingredients, instructions, nutrition (if available), rating
- Renders as `<script type="application/ld+json">` in the page head
- Use `react-helmet-async` or a simple component that injects into `<head>`
- This enables rich recipe cards in Google search results

## 4.2 Meta Tags & Open Graph
- Dynamic `<title>` and `<meta name="description">` per page
- Open Graph tags (`og:title`, `og:description`, `og:image`) for social sharing previews
- Twitter Card meta tags
- Consider pre-rendering / SSR for meta tag effectiveness (Cloudflare Pages can do this with Workers)

## 4.3 Sitemap
- Backend endpoint `GET /api/sitemap.xml` that lists all published recipe URLs
- Or generate a static sitemap at build time
- Submit to Google Search Console

## 4.4 RSS Feed
- Backend endpoint `GET /api/feed.xml` (RSS 2.0 or Atom)
- Lists latest published recipes with title, description, link, pubDate
- Add `<link rel="alternate" type="application/rss+xml">` to HTML head
- Lightweight way for followers to subscribe without email

---

# Milestone 5: Newsletter & Engagement (future)

## 5.1 Newsletter Signup
- Email collection form in footer or a dedicated section on the home page
- Integration with a service (Buttondown, Mailchimp, or Resend)
- Backend endpoint to proxy signup (avoid exposing API keys in frontend)
- Simple: name + email → POST to newsletter service API
- GDPR-friendly: clear opt-in language, no pre-checked boxes

---

# What to implement now

**Milestone 1 (all 7 items)** — this is the scope of work for this session. Milestones 2-5 are the roadmap for future work.

## Implementation Order
1. Admin login flow (1.1)
2. Footer Linktree (1.3)
3. About page (1.2)
4. GCS image upload (1.4) — terraform → backend → frontend
5. UI polish (1.5)
6. Servings scaler (1.6)
7. Share buttons (1.7)

## Verification
- `docker compose up` and test all features
- `npm run build` — no TypeScript errors
- Test: `/admin` shows login when unauthenticated
- Test: About page at `/about`
- Test: Linktree link in footer
- Test: Image upload in recipe form (dev mode: local storage)
- Test: Servings scaler on recipe detail
- Test: Share/copy link buttons on recipe detail
