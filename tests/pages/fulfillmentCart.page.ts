import { expect, type Locator, type Page } from '@playwright/test';

/**
 * Okta SSO for GPS QA (observed DOM: Username → Next → Password → Verify).
 */
export class GpsOktaLoginPage {
  readonly page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  async goto(): Promise<void> {
    await this.page.goto('/');
  }

  async login(email: string, password: string): Promise<void> {
    await this.page.getByRole('textbox', { name: 'Username' }).fill(email);
    await this.page.getByRole('button', { name: 'Next' }).click();

    const passwordField = this.page.getByRole('textbox', { name: 'Password' });
    await passwordField.waitFor({ state: 'visible', timeout: 20_000 });
    await passwordField.fill(password);

    await this.page.getByRole('button', { name: 'Verify' }).click();

    await this.page.waitForURL(/gps\.aegm\.com/i, { timeout: 90_000 });
  }
}

/**
 * Fulfillment Cart grid and navigation (DOM inspected on QA3 FulfillmentCart).
 */
export class FulfillmentCartPage {
  readonly page: Page;
  readonly cartGrid: Locator;

  constructor(page: Page) {
    this.page = page;
    this.cartGrid = page.locator('#orderSearchFulfillmentGrid');
  }

  /** Header flyout → Fulfillment → Go to Cart → fulfillment-type modal → Asset Creation. */
  async openFulfillmentCartFromMenu(): Promise<void> {
    await this.page.getByRole('heading', { name: 'Menu' }).first().click();
    await this.page.getByRole('menuitem', { name: 'Fulfillment' }).click();
    await this.page.getByText('Go to Cart', { exact: true }).click();
    await this.page.getByRole('button', { name: 'Asset Creation' }).click();
    await this.page.waitForURL(/\/Fulfillment\/FulfillmentCart/i, { timeout: 30_000 });
  }

  cartDataRows(): Locator {
    return this.cartGrid.locator('.k-grid-content tbody tr');
  }

  async getCartLineCount(): Promise<number> {
    return this.cartDataRows().count();
  }

  async selectFirstCartDataRow(): Promise<void> {
    const row = this.cartDataRows().first();
    await expect(row, 'Expected at least one cart line').toBeVisible({ timeout: 15_000 });
    const rowCheckbox = row.locator('input[type="checkbox"]').first();
    if ((await rowCheckbox.count()) > 0) {
      await rowCheckbox.check();
    } else {
      await row.click();
    }
  }

  duplicateButton(): Locator {
    return this.page.locator('#duplicateBtn');
  }

  async clickDuplicate(): Promise<void> {
    await expect(this.duplicateButton()).toBeVisible({ timeout: 15_000 });
    await expect(this.duplicateButton()).toBeEnabled();
    await this.duplicateButton().click();
  }

  requestFulfillmentButton(): Locator {
    return this.page.getByRole('button', { name: 'Request Fulfillment' });
  }

  saveButton(): Locator {
    return this.page.getByRole('button', { name: 'Save' });
  }
}
