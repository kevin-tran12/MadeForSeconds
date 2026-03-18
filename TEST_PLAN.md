# Comprehensive Test Suite Plan — MadeForSeconds

## Context

The project has minimal test coverage today: 3 backend tests (health check, empty list recipes, empty list categories), 4 admin tests (list/create/delete recipe + 404), and 2 E2E tests (home page load + navigation). No frontend unit tests exist. The test infrastructure (pytest, vitest, playwright) is already configured. This plan fills in comprehensive coverage across all three layers.

---

## 1. Backend Unit Tests (pytest + httpx TestClient)

### 1.1 Update `conftest.py`

**File:** `backend/tests/conftest.py`

- Add patches for new route modules: `expenses`, `reports`, `totp`, `parse`
- Add `mock_totp_session` fixture — overrides `require_totp_session` dependency
- Add `totp_authenticated_client` fixture — combines admin auth + TOTP session bypass
- Add `mock_cache` fixture — patches `app.cache` to prevent real Redis/memory cache side effects
- Add `mock_stripe` fixture — patches `stripe` module in subscriptions route
- Add `sample_recipe_doc` factory fixture — returns a MagicMock Firestore document with realistic recipe data
- Add `sample_expense_doc` factory fixture — same for expenses

### 1.2 Public Routes (`backend/tests/test_public.py`)

Expand existing file:

| Test | What it verifies |
|------|-----------------|
| `test_list_recipes_with_data` | Returns recipes with all fields populated |
| `test_list_recipes_search_filter` | `?search=carbonara` filters correctly |
| `test_list_recipes_category_filter` | `?category=italian` uses `array_contains` |
| `test_list_recipes_combined_filters` | search + category together |
| `test_list_recipes_search_by_ingredient` | `?search_by=ingredient` path |
| `test_get_recipe_by_slug` | Returns single recipe by slug |
| `test_get_recipe_not_found` | 404 for nonexistent slug |
| `test_get_recipe_unpublished` | 404 for unpublished recipe |
| `test_categories_returns_distinct` | Deduplicates categories |
| `test_sitemap_xml` | Returns valid XML with recipe URLs |
| `test_feed_xml` | Returns valid RSS XML |

### 1.3 Admin Recipe Routes (`backend/tests/test_admin.py`)

Expand existing file:

| Test | What it verifies |
|------|-----------------|
| `test_admin_update_recipe` | PUT updates fields, preserves slug |
| `test_admin_update_recipe_not_found` | 404 for nonexistent ID |
| `test_admin_create_recipe_slug_generation` | Slug auto-generated from title |
| `test_admin_create_recipe_validation_error` | 422 on missing required fields |
| `test_admin_unauthenticated_returns_401` | Requests without auth header fail |
| `test_admin_upload_image_dev_mode` | Returns mock URL in dev |

### 1.4 Supporter Moderation (`backend/tests/test_admin_supporters.py`) — NEW

| Test | What it verifies |
|------|-----------------|
| `test_list_pending_supporters` | Returns docs with note_pending set |
| `test_list_pending_empty` | Empty list when none pending |
| `test_approve_note` | Moves note_pending to note |
| `test_reject_note` | Clears note_pending |
| `test_toggle_name_visibility` | Flips name_enabled |
| `test_toggle_note_visibility` | Flips note_enabled |
| `test_list_all_supporters` | Returns merged subscribers + donations |

### 1.5 Subscription Routes (`backend/tests/test_subscriptions.py`) — NEW

| Test | What it verifies |
|------|-----------------|
| `test_create_checkout_subscription` | Calls Stripe with recurring mode, returns URL |
| `test_create_checkout_one_time` | Calls Stripe with payment mode |
| `test_create_checkout_invalid_amount` | Rejects amounts outside bounds |
| `test_webhook_checkout_completed_subscription` | Creates subscriber doc in Firestore |
| `test_webhook_checkout_completed_donation` | Creates donation doc |
| `test_webhook_idempotency` | Second delivery of same event is a no-op |
| `test_webhook_invalid_signature` | Returns 400 on bad sig |
| `test_session_info_valid` | Returns email and payment type |
| `test_session_info_invalid` | 404 for bad session ID |
| `test_setup_profile` | Writes display_name and note_pending |
| `test_cancel_request_sends_email` | Calls Resend API with cancel link |
| `test_cancel_request_rate_limit` | 429 after 3 attempts in 10 min |
| `test_cancel_confirm_valid_token` | Cancels Stripe subscription |
| `test_cancel_confirm_expired_token` | 400 on expired JWT |
| `test_public_supporters_list` | Returns only name_enabled supporters |

### 1.6 Expense Routes (`backend/tests/test_expenses.py`) — NEW

| Test | What it verifies |
|------|-----------------|
| `test_create_expense` | Creates doc with calculated project amounts |
| `test_create_expense_writes_audit_trail` | Revision 1 written to expense_revisions |
| `test_create_expense_validation` | 422 on missing required fields |
| `test_list_expenses_by_year` | Filters by date range |
| `test_list_expenses_by_month` | Narrows to specific month |
| `test_list_expenses_by_category` | Python-side category filter |
| `test_get_expense` | Returns full expense with items |
| `test_get_expense_not_found` | 404 |
| `test_update_expense` | Recalculates project amounts, increments revision |
| `test_update_expense_writes_revision_snapshot` | Pre-update snapshot in audit trail |
| `test_void_expense` | Sets status=voided, voided_at, void_reason |
| `test_void_expense_writes_revision` | Snapshot before void |
| `test_upload_receipt_dev_mode` | Returns mock path |
| `test_get_receipt_url` | Returns signed URL structure |
| `test_project_amount_calculation` | `recalculate_project_amounts` with mixed project_related items |
| `test_project_amount_zero_subtotal` | Edge case: no items, avoids divide-by-zero |

### 1.7 Reports (`backend/tests/test_reports.py`) — NEW

| Test | What it verifies |
|------|-----------------|
| `test_summary_by_year` | Correct totals and category breakdown |
| `test_summary_by_month` | Filtered to single month |
| `test_summary_empty` | Zero totals when no expenses |
| `test_export_csv` | Returns CSV with correct headers and data rows |
| `test_export_csv_includes_summary_row` | Summary row at bottom |
| `test_export_pdf` | Returns PDF content-type, non-empty body |

### 1.8 TOTP Routes (`backend/tests/test_totp.py`) — NEW

| Test | What it verifies |
|------|-----------------|
| `test_totp_status_not_configured` | Returns `{enabled: false}` |
| `test_totp_status_configured` | Returns `{enabled: true}` |
| `test_totp_setup_returns_secret_and_qr` | Secret is base32, QR is data URI |
| `test_totp_confirm_setup_valid_code` | Persists config, returns session token |
| `test_totp_confirm_setup_invalid_code` | 400 on wrong code |
| `test_totp_verify_valid` | Returns session token |
| `test_totp_verify_invalid` | 401 on wrong code |
| `test_totp_reset_valid` | Clears Firestore config |
| `test_totp_reset_invalid_code` | 401 on wrong code |
| `test_totp_session_middleware_dev_bypass` | Dev mode skips TOTP check |
| `test_totp_session_middleware_no_setup` | Allows access when TOTP not yet configured |
| `test_totp_session_middleware_valid_token` | Passes with valid JWT in header |
| `test_totp_session_middleware_expired_token` | 401 on expired JWT |

### 1.9 Auth (`backend/tests/test_auth.py`) — NEW

| Test | What it verifies |
|------|-----------------|
| `test_dev_mode_auth_bypass` | X-Dev-Admin header returns dev@local |
| `test_dev_mode_no_header` | 401 without header |
| `test_prod_mode_valid_jwt` | Verified email returned |
| `test_prod_mode_non_admin_email` | 403 when email not in ADMIN_EMAILS |
| `test_prod_mode_invalid_jwt` | 401 on bad token |

### 1.10 Models (`backend/tests/test_models.py`) — NEW

| Test | What it verifies |
|------|-----------------|
| `test_recipe_create_validation` | Required fields enforced |
| `test_recipe_update_all_optional` | Empty update is valid |
| `test_expense_create_validation` | Required fields + category enum |
| `test_recalculate_project_amounts` | Proportional tax math with known inputs |
| `test_recalculate_zero_raw_subtotal` | No divide-by-zero |
| `test_expense_category_enum` | Only valid categories accepted |

### 1.11 Cache (`backend/tests/test_cache.py`) — NEW

| Test | What it verifies |
|------|-----------------|
| `test_memory_cache_set_get` | In-memory fallback works |
| `test_memory_cache_ttl_expiry` | Expired entries return None |
| `test_cache_clear` | All keys removed |

---

## 2. Frontend Unit Tests (vitest + @testing-library/react)

### 2.1 Utility / Logic Tests

| File to create | Tests |
|----------------|-------|
| `src/lib/__tests__/api-client.test.ts` | `apiFetch` injects auth header; dev mode sends X-Dev-Admin; TOTP header attached; 403 clears TOTP token |
| `src/lib/__tests__/types-expense.test.ts` | `recalcProjectAmounts` math; edge cases (zero items, all non-project) |

### 2.2 Hook Tests

| File to create | Tests |
|----------------|-------|
| `src/hooks/__tests__/useRecipes.test.ts` | Fetches recipes; handles loading/error states; passes search params |
| `src/hooks/__tests__/useRecipe.test.ts` | Fetches single recipe; 404 error handling |
| `src/hooks/__tests__/useCategories.test.ts` | Fetches categories; handles empty list |

### 2.3 Component Tests (key components only)

| File to create | Tests |
|----------------|-------|
| `src/components/admin/__tests__/RecipeForm.test.tsx` | Renders all fields; validates required inputs; calls onSubmit with correct shape |
| `src/components/admin/__tests__/TotpGate.test.tsx` | Shows verify form when TOTP enabled; shows setup when not configured; passes through when session valid |
| `src/components/admin/__tests__/LoginModal.test.tsx` | Dev mode: password input + submit; renders Google login button in prod mode |
| `src/components/recipe/__tests__/RecipeDetail.test.tsx` | Renders ingredients, instructions; ingredient scaling works; cooking mode toggle |
| `src/components/ui/__tests__/Button.test.tsx` | Renders variants; handles click; disabled state |

---

## 3. E2E Tests (Playwright)

### 3.1 Prerequisites

- E2E tests run against Docker Compose stack (backend + Firestore emulator + Redis)
- Add Playwright `globalSetup` that seeds the Firestore emulator via the backend's seed endpoint or script
- Add dev-mode admin login helper (sets sessionStorage flag)

### 3.2 Test Files

| File to create | Tests |
|----------------|-------|
| `tests-e2e/public-recipes.spec.ts` | Home shows recipes; click recipe card navigates to detail; search filters results; category filter works; empty search shows all |
| `tests-e2e/recipe-detail.spec.ts` | All sections render (ingredients, instructions, nutrition); ingredient scaling; cooking mode toggle |
| `tests-e2e/admin-recipes.spec.ts` | Login as dev admin; create recipe via form; edit recipe; delete recipe; publish/unpublish toggle; recipe appears on public page after publish |
| `tests-e2e/admin-expenses.spec.ts` | TOTP gate appears; after TOTP bypass: create expense; edit expense; void expense; receipt upload (mock) |
| `tests-e2e/support.spec.ts` | Support page renders; amount selector works; (Stripe checkout is external — verify redirect URL is constructed) |
| `tests-e2e/navigation.spec.ts` | All nav links work; mobile menu opens/closes; admin link visible when logged in; admin link hidden when logged out |

---

## 4. Execution Order

### Phase A — Backend foundations (do first)
1. Update `conftest.py` with new fixtures
2. `test_models.py` — pure logic, no mocking
3. `test_auth.py` — auth dependency logic
4. `test_cache.py` — cache logic

### Phase B — Backend route tests
5. Expand `test_public.py`
6. Expand `test_admin.py`
7. `test_admin_supporters.py`
8. `test_subscriptions.py` (mock Stripe)
9. `test_expenses.py` (mock TOTP session)
10. `test_reports.py`
11. `test_totp.py`

### Phase C — Frontend unit tests
12. `api-client.test.ts`
13. `types-expense.test.ts`
14. Hook tests
15. Component tests

### Phase D — E2E tests
16. E2E setup (global setup, auth helper)
17. Navigation + public recipe tests
18. Admin recipe CRUD flow
19. Admin expense flow
20. Support page flow

---

## 5. Key Files to Modify/Create

**Modify:**
- `backend/tests/conftest.py` — expanded fixtures
- `backend/tests/test_public.py` — more test cases
- `backend/tests/test_admin.py` — more test cases

**Create (backend):**
- `backend/tests/test_auth.py`
- `backend/tests/test_models.py`
- `backend/tests/test_cache.py`
- `backend/tests/test_admin_supporters.py`
- `backend/tests/test_subscriptions.py`
- `backend/tests/test_expenses.py`
- `backend/tests/test_reports.py`
- `backend/tests/test_totp.py`

**Create (frontend unit):**
- `src/lib/__tests__/api-client.test.ts`
- `src/lib/__tests__/types-expense.test.ts`
- `src/hooks/__tests__/useRecipes.test.ts`
- `src/hooks/__tests__/useRecipe.test.ts`
- `src/hooks/__tests__/useCategories.test.ts`
- `src/components/admin/__tests__/RecipeForm.test.tsx`
- `src/components/admin/__tests__/TotpGate.test.tsx`
- `src/components/admin/__tests__/LoginModal.test.tsx`
- `src/components/recipe/__tests__/RecipeDetail.test.tsx`
- `src/components/ui/__tests__/Button.test.tsx`

**Create (E2E):**
- `tests-e2e/public-recipes.spec.ts`
- `tests-e2e/recipe-detail.spec.ts`
- `tests-e2e/admin-recipes.spec.ts`
- `tests-e2e/admin-expenses.spec.ts`
- `tests-e2e/support.spec.ts`
- `tests-e2e/navigation.spec.ts`

---

## 6. Verification

```bash
# Backend tests
npm run test:backend         # pytest --cov=app --cov-report=term-missing

# Frontend unit tests
npm run test:unit            # vitest run --coverage

# E2E tests (requires docker compose up)
npm run test:e2e             # playwright test
```

All three commands should pass with 0 failures. Target: >80% backend line coverage, meaningful coverage of critical frontend paths.
