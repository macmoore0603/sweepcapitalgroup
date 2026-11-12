import { describe, expect, test } from 'bun:test';
import { buildCheckoutOptions } from './checkout-options';

const input = { priceId: 'price_existing', returnUrl: 'https://sweepcapitalgroup.com/checkout/return' };

describe('Stripe receipt checkout configuration', () => {
  test('known email is passed to Checkout and the payment receipt', () => {
    const options = buildCheckoutOptions({ ...input, customerEmail: 'buyer@example.com' });
    expect(options.customer_email).toBe('buyer@example.com');
    expect(options.payment_intent_data?.receipt_email).toBe('buyer@example.com');
  });
  test('unknown email is left for Embedded Checkout to collect', () => {
    const options = buildCheckoutOptions(input);
    expect(options.ui_mode).toBe('embedded_page');
    expect(options.customer_email).toBeUndefined();
    expect(options.payment_intent_data).toBeUndefined();
  });
  test('paid invoice creation is never enabled', () => {
    expect(buildCheckoutOptions(input).invoice_creation).toBeUndefined();
    expect(buildCheckoutOptions({ ...input, customerEmail: 'buyer@example.com' }).invoice_creation).toBeUndefined();
  });
  test('automatic tax stays enabled for one-time payment', () => {
    const options = buildCheckoutOptions(input);
    expect(options.automatic_tax?.enabled).toBe(true);
    expect(options.mode).toBe('payment');
  });
});