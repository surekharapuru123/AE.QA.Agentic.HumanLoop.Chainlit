import { test, expect } from '@playwright/test';
import { getEnvironment } from '../config/environments';
import { attachStepEvidence } from '../utils/test-helpers';
import {
  FulfillmentCartPage,
  GpsOktaLoginPage,
} from '../pages/fulfillmentCart.page';

test.describe('Fulfillment Cart Duplicate @regression @fulfillment-cart-duplicate', () => {
  test('User can duplicate a cart row via Duplicate button (Qase 389, Jira GPS-7525) @automated', async ({
    page,
  }, testInfo) => {
    const env = getEnvironment(process.env.TEST_ENV);
    if (!env) {
      throw new Error('Missing environment — set TEST_ENV (e.g. gps-qa3) in tests/config/environments.ts');
    }

    const loginPage = new GpsOktaLoginPage(page);
    const cartPage = new FulfillmentCartPage(page);

    await test.step('Log in at GPS', async () => {
      await loginPage.goto();
      await loginPage.login(env.credentials.email, env.credentials.password);
      await attachStepEvidence(testInfo, page, '01-after-login');
    });

    await test.step('Navigate to Fulfillment Cart', async () => {
      await cartPage.openFulfillmentCartFromMenu();
      await expect(
        page.getByRole('heading', { name: 'Fulfillment Cart' }),
      ).toBeVisible();
      await attachStepEvidence(testInfo, page, '02-fulfillment-cart');
    });

    const initialRows = await cartPage.getCartLineCount();
    if (initialRows < 1) {
      test.skip(
        true,
        'Precondition: Fulfillment Cart must contain at least one asset line. Seed the cart for GPS_EMAIL on this environment, then re-run.',
      );
    }

    await test.step('Select a cart row and duplicate', async () => {
      await cartPage.selectFirstCartDataRow();
      await attachStepEvidence(testInfo, page, '03-row-selected');

      await cartPage.clickDuplicate();
      await expect
        .poll(async () => cartPage.getCartLineCount(), { timeout: 20_000 })
        .toBeGreaterThan(initialRows);
      await attachStepEvidence(testInfo, page, '04-after-duplicate');
    });

    await test.step('Attempt submit with duplicates; verify system blocks or stays invalid if required', async () => {
      const submit = cartPage.requestFulfillmentButton();
      if (await submit.isEnabled()) {
        await submit.click();
        const blocked = page.getByText(
          /Error!|duplicate|invalid|cannot|blocked|not allowed|warning/i,
        );
        await expect(blocked.first()).toBeVisible({ timeout: 15_000 });
      } else {
        await expect(submit).toBeDisabled();
      }
      await attachStepEvidence(testInfo, page, '05-submit-attempt');
    });
  });
});
