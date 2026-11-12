import type Stripe from 'stripe';

export function buildCheckoutOptions(data: {
  priceId: string;
  returnUrl: string;
  customerEmail?: string;
  referralCode?: string;
}, now = Date.now()): Stripe.Checkout.SessionCreateParams {
  return {
    line_items: [{ price: data.priceId, quantity: 1 }],
    mode: 'payment',
    ui_mode: 'embedded_page',
    return_url: data.returnUrl,
    automatic_tax: { enabled: true },
    expires_at: Math.floor(now / 1000) + 30 * 60,
    ...(data.customerEmail && {
      customer_email: data.customerEmail,
      payment_intent_data: { receipt_email: data.customerEmail },
    }),
    ...(data.referralCode && { client_reference_id: data.referralCode }),
  };
}