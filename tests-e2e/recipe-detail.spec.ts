import { test, expect } from '@playwright/test';

test.describe('Recipe Detail', () => {
  test('renders all sections', async ({ page }) => {
    // Navigate to recipes and pick the first one
    await page.goto('/recipes');
    await page.waitForLoadState('networkidle');
    
    const firstRecipe = page.locator('a:has(h3)').first();
    await expect(firstRecipe).toBeVisible({ timeout: 10000 });
    await firstRecipe.click();
    
    await expect(page).toHaveURL(/\/recipes\/.+/);
    await page.waitForLoadState('networkidle');
    
    // Check key elements
    await expect(page.locator('h1')).toBeVisible();
    await expect(page.locator('h2:has-text("Grocery List")')).toBeVisible();
    await expect(page.locator('h2:has-text("Instructions")')).toBeVisible();
  });

  test('cooking mode toggle', async ({ page }) => {
    await page.goto('/recipes');
    await page.waitForLoadState('networkidle');
    
    const firstRecipe = page.locator('a:has(h3)').first();
    await firstRecipe.click();
    await page.waitForLoadState('networkidle');
    
    const cookingModeBtn = page.getByRole('button', { name: /start cooking/i });
    if (await cookingModeBtn.isVisible()) {
      await cookingModeBtn.click();
      // Wait for animation/overlay
      await page.waitForTimeout(1000);
      const exitBtn = page.getByRole('button', { name: /exit/i }).first();
      await expect(exitBtn).toBeVisible();
      await exitBtn.click();
      await expect(page.getByRole('button', { name: /start cooking/i }).first()).toBeVisible();
    }
  });
});

test.describe('Sous Chef', () => {
  test('drawer opens, explains itself, and closes on Escape', async ({ page }) => {
    await page.goto('/recipes');
    await page.waitForLoadState('networkidle');
    await page.locator('a:has(h3)').first().click();
    await page.waitForLoadState('networkidle');

    await page.getByRole('button', { name: /ask the sous chef/i }).click();
    const dialog = page.getByRole('dialog', { name: /sous chef/i });
    await expect(dialog).toBeVisible();

    // CI and staging run without an Anthropic key, so the drawer shows the
    // "off" notice; a configured backend shows the sign-in prompt instead.
    // Either proves the lazy chunk loaded and the status endpoint answered.
    await expect(
      dialog.getByText(/taking a break/i).or(dialog.getByRole('button', { name: /sign in with google/i }))
    ).toBeVisible({ timeout: 10000 });

    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(page.getByRole('button', { name: /start cooking/i }).first()).toBeVisible();
  });
});
