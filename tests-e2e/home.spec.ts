import { test, expect } from '@playwright/test';

test('home page loads and shows title', async ({ page }) => {
  page.on('console', msg => console.log('PAGE LOG:', msg.text()));
  page.on('pageerror', err => console.log('PAGE ERROR:', err.message));

  await page.goto('/');
  // Use a more specific selector to avoid strict mode violation
  await expect(page.getByRole('link', { name: 'MadeForSeconds', exact: true }).first()).toBeVisible();
});

test('navigation to recipes page', async ({ page }) => {
  await page.goto('/');
  // Use exact: true to avoid matching "Browse recipes" button and header link
  await page.getByRole('link', { name: 'Recipes', exact: true }).first().click();
  await expect(page).toHaveURL(/\/recipes/);
});
