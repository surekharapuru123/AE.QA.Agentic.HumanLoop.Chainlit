import { Page } from '@playwright/test';

export class FulfillmentCartPage {
  constructor(private readonly page: Page) {}
  async goto() {
    await this.page.goto('https://qa3.gps.aegm.com/Fulfillment/FulfillmentCart');
  }
  async login(username: string, password: string) {
    await this.page.goto('https://qa3.gps.aegm.com');
    // (Insert Okta/app login steps using the input selectors here)
    await this.page.fill('input[type="email"]', username);
    await this.page.fill('input[type="password"]', password);
    await this.page.click('button[type="submit"]');
    await this.page.waitForURL('**/Dashboard/Index');
  }
  async selectRow(rowIdx: number) {
    await this.page.waitForSelector('tbody tr');
    const checkboxes = await this.page.$$('input[type="checkbox"]');
    if(checkboxes[rowIdx]) { await checkboxes[rowIdx].check(); }
  }
  async duplicateSelected() {
    // Click the Duplicate button (selector must match inspected DOM)
    await this.page.click('button:has-text("Duplicate")');
  }
  async expectDuplicateCreated() {
    await this.page.waitForSelector('tbody tr:nth-child(2)');
    // Add further assertions based on app behavior
  }
  async expectDuplicateBlocked() {
    await this.page.waitForSelector('.validation-error, .error, [role="alert"]');
    // Add further assertions based on app error message
  }
}
