import { Page } from '@playwright/test';

export class FulfillmentCartPage {
  constructor(public page: Page) {}

  async goto() {
    await this.page.goto('https://qa3.gps.aegm.com/Fulfillment/FulfillmentCart');
  }

  async login() {
    // If not already authenticated, log in with known credentials
    if (await this.page.isVisible('input[type="email"]')) {
      await this.page.fill('input[type="email"]', 'qaauto.test@aenetworks.com');
      await this.page.fill('input[type="password"]', 'Test@123');
      await this.page.click('button:has-text("Sign In")');
      await this.page.waitForURL('**/Dashboard/Index');
    }
  }

  async selectFirstRow() {
    // Selects first row checkbox - adjust selector as needed
    await this.page.check('table tbody tr:first-child input[type="checkbox"]');
  }

  async getRowCount() {
    return await this.page.locator('table tbody tr').count();
  }

  async duplicateSelectedRow() {
    await this.page.click('button:has-text("Duplicate")');
    await this.page.waitForTimeout(1000); // wait for new row (adjust if needed)
  }

  async attemptSubmission() {
    await this.page.click('button:has-text("Submit")');
  }
}
