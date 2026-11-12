import { createServerFn } from "@tanstack/react-start";
import { type StripeEnv, createStripeClient } from "@/lib/stripe.server";
import { assertProgramAvailable } from '@/lib/payment-catalog';
import { buildCheckoutOptions } from '@/lib/checkout-options';

export const getStripePublicConfiguration = createServerFn({ method: 'GET' })
  .handler(async () => {
    const environment: StripeEnv = process.env.STRIPE_CHECKOUT_ENVIRONMENT === 'sandbox' ? 'sandbox' : 'live';
    const publishableKey = environment === 'sandbox' ? process.env.STRIPE_TEST_PUBLISHABLE_KEY : process.env.STRIPE_PUBLISHABLE_KEY;
    if (!publishableKey?.startsWith(environment === 'sandbox' ? 'pk_test_' : 'pk_live_')) {
      throw new Error('Payment setup is incomplete: a matching Stripe publishable key is required.');
    }
    return { environment, publishableKey };
  });

export const createCheckoutSession = createServerFn({ method: "POST" })
  .inputValidator(
    (data: {
      priceId: string;
      customerEmail?: string;
      returnUrl: string;
      environment: StripeEnv;
      referralCode?: string;
    }) => {
      if (!/^[a-zA-Z0-9_-]+$/.test(data.priceId)) throw new Error("Invalid priceId");
      if (data.environment !== "sandbox" && data.environment !== "live") {
        throw new Error("Invalid environment");
      }
      if (!data.returnUrl || !/^https?:\/\//.test(data.returnUrl)) {
        throw new Error("Invalid returnUrl");
      }
      if (data.referralCode && !/^[a-zA-Z0-9]{4,20}$/.test(data.referralCode)) {
        throw new Error("Invalid referralCode");
      }
      return data;
    },
  )
  .handler(async ({ data }) => {
    const tier = assertProgramAvailable(data.priceId, data.environment, process.env.STRIPE_MANAGED_TRADING_APPROVED === 'true');
    if (process.env.STRIPE_TAX_READY !== 'true') throw new Error('Payments are temporarily unavailable while tax setup is completed.');
    const stripe = createStripeClient(data.environment);

    const stripePrice = data.environment === 'live'
      ? await stripe.prices.retrieve(tier.livePrice)
      : (await stripe.prices.list({ lookup_keys: [data.priceId], active: true })).data[0];
    if (!stripePrice || !stripePrice.active || stripePrice.unit_amount !== tier.amount || stripePrice.currency !== 'usd' || stripePrice.recurring) throw new Error('Program price is not configured correctly');

    const session = await stripe.checkout.sessions.create(buildCheckoutOptions({
      priceId: stripePrice.id,
      returnUrl: data.returnUrl,
      customerEmail: data.customerEmail,
      referralCode: data.referralCode,
    }));

    // Fire-and-forget: record intent so Revenue Agent can chase abandons
    try {
      const url = process.env.SUPABASE_URL;
      const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
      if (url && key) {
        const { createClient } = await import("@supabase/supabase-js");
        const sb: any = createClient(url, key);
        await sb.from("checkout_intents").upsert({
          stripe_session_id: session.id,
          email: data.customerEmail ?? null,
          product_name: (stripePrice as any).nickname ?? data.priceId,
          amount_cents: stripePrice.unit_amount ?? null,
          currency: stripePrice.currency,
          environment: data.environment,
          status: "open",
          referral_code: data.referralCode ?? null,
        }, { onConflict: "stripe_session_id" });
      }
    } catch (e) { console.error("intent seed", e); }

    return session.client_secret;
  });

export const getCheckoutSessionStatus = createServerFn({ method: "POST" })
  .inputValidator(
    (data: { sessionId: string; environment: StripeEnv }) => {
      if (!/^cs_[a-zA-Z0-9_]+$/.test(data.sessionId)) throw new Error("Invalid sessionId");
      if (data.environment !== "sandbox" && data.environment !== "live") {
        throw new Error("Invalid environment");
      }
      return data;
    },
  )
  .handler(async ({ data }) => {
    const stripe = createStripeClient(data.environment);
    const session = await stripe.checkout.sessions.retrieve(data.sessionId, {
      expand: ["line_items", "payment_intent"],
    });

    const paymentStatus = session.payment_status;
    const status = session.status;
    const pi = typeof session.payment_intent === "object" ? session.payment_intent : null;
    const piStatus = pi?.status ?? null;
    const lastError = pi?.last_payment_error?.message ?? null;

    let outcome: "success" | "pending" | "failed";
    if (paymentStatus === "paid" || paymentStatus === "no_payment_required" || piStatus === "succeeded") {
      outcome = "success";
    } else if (
      status === "expired" ||
      piStatus === "canceled" ||
      piStatus === "requires_payment_method"
    ) {
      outcome = "failed";
    } else {
      outcome = "pending";
    }

    const lineItem = session.line_items?.data?.[0];
    return {
      outcome,
      paymentStatus,
      sessionStatus: status,
      piStatus,
      errorMessage: lastError,
      customerEmail: session.customer_details?.email ?? session.customer_email ?? null,
      amountTotal: (session.amount_total ?? 0) / 100,
      currency: (session.currency ?? "usd").toUpperCase(),
      productName: lineItem?.description ?? null,
    };
  });
