import { test, expect } from '@playwright/test';

test.describe('Support Page', () => {
  test('renders support page', async ({ page }) => {
    await page.goto('/support');
    await expect(page.getByRole('heading', { name: /donate madeforseconds/i })).toBeVisible();
  });

  test('amount selector and checkout redirect', async ({ page }) => {
    await page.goto('/support');
    
    // Select an amount ($5)
    await page.getByRole('button', { name: /^\$5$/ }).click();
    
    // Check for checkout button which should now say "Donate — $5" (default is one-time)
    const checkoutBtn = page.locator('button').filter({ hasText: /donate — \$5/i });
    await expect(checkoutBtn).toBeVisible();
    await expect(checkoutBtn).not.toBeDisabled();
  });
});
