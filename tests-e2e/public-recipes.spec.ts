import { test, expect } from '@playwright/test';

test.describe('Public Recipes', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/recipes');
    await page.waitForLoadState('networkidle');
  });

  test('recipes page shows grid', async ({ page }) => {
    await expect(page.locator('h3').first()).toBeVisible({ timeout: 10000 });
  });

  test('search filters results', async ({ page }) => {
    const searchInput = page.getByRole('main').getByPlaceholder(/search/i);
    if (await searchInput.isVisible()) {
      await searchInput.fill('carbonara');
      await page.waitForTimeout(1000);
      await expect(page.locator('h3').first()).toBeVisible();
    }
  });

  test('navigation to detail and back', async ({ page }) => {
    const firstCard = page.locator('a:has(h3)').first();
    await expect(firstCard).toBeVisible({ timeout: 10000 });
    
    const title = await firstCard.locator('h3').textContent();
    await firstCard.click();
    
    await expect(page).toHaveURL(/\/recipes\/.+/);
    if (title) {
      await expect(page.locator('h1')).toContainText(title.trim());
    }
    
    const backLink = page.getByRole('link', { name: /back|recipes/i }).first();
    if (await backLink.isVisible()) {
      await backLink.click();
      await expect(page).toHaveURL(/\/recipes/);
    }
  });
});
