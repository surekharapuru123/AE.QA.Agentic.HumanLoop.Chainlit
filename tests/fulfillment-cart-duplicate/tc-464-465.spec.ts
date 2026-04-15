import { test, expect } from '@playwright/test';
import { FulfillmentCartPage } from '../pages/fulfillmentCart.page';

// Test Case 464: Duplicate action duplicates selected row(s) in Fulfillment Cart
test.describe('GPS-7525 - Fulfillment Cart Duplicate', () => {
  test('TC-464: Duplicate action duplicates selected row', async ({ page }) => {
    const cart = new FulfillmentCartPage(page);
    await cart.goto();
    await cart.login();
    await cart.selectFirstRow();
    const initialRowCount = await cart.getRowCount();
    await cart.duplicateSelectedRow();
    const afterDuplicateCount = await cart.getRowCount();
    expect(afterDuplicateCount).toBe(initialRowCount + 1);
  });
  
  // Test Case 465: Prevent duplicate asset fulfillment in same request
  test('TC-465: Prevent duplicate asset fulfillment in same request', async ({ page }) => {
    const cart = new FulfillmentCartPage(page);
    await cart.goto();
    await cart.login();
    await cart.selectFirstRow();
    await cart.duplicateSelectedRow();
    // Attempt to submit cart - should trigger error if duplicate asset in single request
    await cart.attemptSubmission();
    await expect(cart.page).toHaveText('You cannot request fulfillment for the same asset twice');
  });
});
