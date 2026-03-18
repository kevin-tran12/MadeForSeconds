import { test, expect } from '@playwright/test';

test.describe('Navigation', () => {
  test('all nav links work', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    
    // Check main nav links
    await page.getByRole('link', { name: 'Recipes', exact: true }).first().click();
    await expect(page).toHaveURL(/\/recipes/);
    
    await page.getByRole('link', { name: 'About', exact: true }).first().click();
    await expect(page).toHaveURL(/\/about/);
    
    // Support link is actually "Support us"
    await page.getByRole('link', { name: /support us/i }).first().click();
    await expect(page).toHaveURL(/\/support/);
  });

  test('admin link visibility', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    
    // Hidden by default
    const adminLink = page.getByRole('link', { name: /admin/i });
    await expect(adminLink).not.toBeVisible();
    
    // Login
    await page.evaluate(() => {
      sessionStorage.setItem('mfs_dev_admin', 'true');
    });
    await page.reload();
    await page.waitForLoadState('networkidle');
    
    // Visible after login
    await expect(page.getByRole('link', { name: /admin/i }).first()).toBeVisible();
  });
});
