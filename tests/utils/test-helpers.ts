import { Page, expect, type TestInfo } from '@playwright/test';

/**
 * Attach a full-page screenshot to the **current** `test.step` (Playwright JSON report + executor/Qase).
 * Call once at the end of each step so Qase step rows show the UI that step actually reached — not only
 * `test-finished-1.png` after the whole test.
 */
export async function attachStepEvidence(
  testInfo: TestInfo,
  page: Page,
  label: string
): Promise<void> {
  await testInfo.attach(`${label.replace(/[^a-zA-Z0-9_-]+/g, '-')}.png`, {
    body: await page.screenshot({ fullPage: true }),
    contentType: 'image/png',
  });
}

export async function waitForPageLoad(page: Page): Promise<void> {
  await page.waitForLoadState('networkidle');
}

export async function takeScreenshotOnFailure(
  page: Page,
  testName: string
): Promise<string> {
  const path = `test-results/screenshots/${testName}-${Date.now()}.png`;
  await page.screenshot({ path, fullPage: true });
  return path;
}

export async function clearAndType(
  page: Page,
  selector: string,
  text: string
): Promise<void> {
  await page.locator(selector).clear();
  await page.locator(selector).fill(text);
}

export async function verifyToastMessage(
  page: Page,
  expectedText: string
): Promise<void> {
  const toast = page.locator('[role="alert"], .toast, .notification');
  await expect(toast).toBeVisible({ timeout: 5000 });
  await expect(toast).toContainText(expectedText);
}

export function generateTestData(prefix: string): Record<string, string> {
  const timestamp = Date.now();
  return {
    email: `${prefix}_${timestamp}@test.com`,
    username: `${prefix}_${timestamp}`,
    password: `Test@${timestamp}`,
  };
}
