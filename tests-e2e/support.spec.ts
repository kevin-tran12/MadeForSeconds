import { test, expect } from '@playwright/test';

test.describe('Support Page', () => {
  test('renders support page', async ({ page }) => {
    await page.goto('/support');
    await expect(page.getByRole('heading', { name: /support madeforseconds/i })).toBeVisible();
  });

  test('amount selector and checkout redirect', async ({ page }) => {
    await page.goto('/support');
    
    // Select an amount ($10)
    await page.getByRole('button', { name: /^\$10$/ }).click();
    
    // Check for checkout button which should now say "Support — $10/month"
    const checkoutBtn = page.locator('button').filter({ hasText: /support — \$10/i });
    await expect(checkoutBtn).toBeVisible();
    await expect(checkoutBtn).not.toBeDisabled();
  });
});
