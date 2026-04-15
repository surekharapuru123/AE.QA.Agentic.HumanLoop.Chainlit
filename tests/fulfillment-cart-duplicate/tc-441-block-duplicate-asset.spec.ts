import { test, expect } from '@playwright/test';
import { FulfillmentCartPage } from '../pages/fulfillmentCart.page';

test('System prevents duplicate fulfillment requests for the same asset', async ({ page }) => {
  const cart = new FulfillmentCartPage(page);
  await cart.goto();
  await cart.login('qaauto.test@aenetworks.com', 'Test@123');
  await cart.selectRow(1);
  await cart.duplicateSelected();
  await cart.expectDuplicateBlocked();
});
