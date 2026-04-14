import { test, expect } from '@playwright/test';
import { FulfillmentCartPage } from '../pages/fulfillmentCart.page';

test.describe('Fulfillment Cart - Duplicate Feature', () => {
  test('User can duplicate a row in the Fulfillment Cart', async ({ page }) => {
    const cart = new FulfillmentCartPage(page);
    await cart.goto();
    await cart.login('qaauto.test@aenetworks.com', 'Test@123');
    await cart.selectRow(1);
    await cart.duplicateSelected();
    await cart.expectDuplicateCreated();
  });
});
