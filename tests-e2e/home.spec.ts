import { test, expect } from '@playwright/test';

test('home page loads and shows title', async ({ page }) => {
  page.on('console', msg => console.log('PAGE LOG:', msg.text()));
  page.on('pageerror', err => console.log('PAGE ERROR:', err.message));

  await page.goto('/');
  // Use a more specific selector to avoid strict mode violation
  await expect(page.getByRole('link', { name: 'MadeForSeconds', exact: true }).first()).toBeVisible();
});

test('debug environment', async ({ page }) => {
  await page.goto('/');
  const apiUrl = await page.evaluate(() => (window as any).import?.meta?.env?.VITE_API_URL || 'unknown');
  console.log('DEBUG: VITE_API_URL on page is', apiUrl);
  
  // Check if API is reachable from page
  const apiHealth = await page.evaluate(async (url) => {
    try {
      const resp = await fetch(`${url}/api/health`);
      return await resp.json();
    } catch (e: any) {
      return { error: e.message };
    }
  }, apiUrl === 'unknown' ? 'http://mfs-backend:8000' : apiUrl);
  console.log('DEBUG: API Health from page:', apiHealth);
});

test('navigation to recipes page', async ({ page }) => {
  await page.goto('/');
  // Use exact: true to avoid matching "Browse recipes" button and header link
  await page.getByRole('link', { name: 'Recipes', exact: true }).first().click();
  await expect(page).toHaveURL(/\/recipes/);
});
