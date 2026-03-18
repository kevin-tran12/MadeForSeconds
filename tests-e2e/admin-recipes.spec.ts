import { test, expect } from '@playwright/test';

test.describe('Admin Recipes', () => {
  test.beforeEach(async ({ page }) => {
    // Dev login bypass - set item then navigate
    await page.goto('/');
    await page.evaluate(() => {
      sessionStorage.setItem('mfs_dev_admin', 'true');
    });
    // Now navigate to admin
    await page.goto('/admin');
    await page.waitForLoadState('networkidle');
  });

  test('admin dashboard loads', async ({ page }) => {
    // Check for a button that is only in the admin dashboard
    await expect(page.getByRole('button', { name: /new recipe/i })).toBeVisible({ timeout: 10000 });
  });

  test('create recipe flow', async ({ page }) => {
    await page.getByRole('button', { name: /new recipe/i }).click();
    await expect(page).toHaveURL(/\/admin\/new/);
    
    await page.getByLabel(/title/i).fill('E2E Test Recipe');
    await page.getByLabel(/description/i).fill('Description for E2E test');
    
    // Fill first ingredient (already exists in DOM)
    await page.getByPlaceholder('1.5').first().fill('1');
    await page.getByPlaceholder('Ingredient name').first().fill('Water');
    
    // Fill first instruction (already exists in DOM) - using exact placeholder
    await page.getByPlaceholder(/Step 1/).first().fill('Boil the water.');

    // Click "Create recipe"
    const createBtn = page.getByRole('button', { name: /create recipe/i });
    await createBtn.click();
    
    // Should redirect back to admin home
    await expect(page).toHaveURL(/\/admin$/);
    // Use .first() because multiple E2E test runs might have created multiple recipes
    await expect(page.getByText('E2E Test Recipe').first()).toBeVisible({ timeout: 15000 });
  });
});
