import { test, expect } from '@playwright/test';

test('home page loads and shows title', async ({ page }) => {
  await page.goto('/');
  // Check if "MadeForSeconds" is visible (adjust based on your actual UI)
  await expect(page.getByText('MadeForSeconds')).toBeVisible();
});

test('navigation to recipes page', async ({ page }) => {
  await page.goto('/');
  // Click on a link that goes to /recipes (adjust based on your actual UI)
  await page.getByRole('link', { name: 'Recipes' }).click();
  await expect(page).toHaveURL(/\/recipes/);
});
