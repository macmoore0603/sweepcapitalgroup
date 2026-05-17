import { createServerFn } from "@tanstack/react-start";
import { type StripeEnv, createStripeClient } from "@/lib/stripe.server";

export const createCheckoutSession = createServerFn({ method: "POST" })
  .inputValidator(
    (data: {
      priceId: string;
      customerEmail?: string;
      returnUrl: string;
      environment: StripeEnv;
    }) => {
      if (!/^[a-zA-Z0-9_-]+$/.test(data.priceId)) throw new Error("Invalid priceId");
      if (data.environment !== "sandbox" && data.environment !== "live") {
        throw new Error("Invalid environment");
      }
      if (!data.returnUrl || !/^https?:\/\//.test(data.returnUrl)) {
        throw new Error("Invalid returnUrl");
      }
      return data;
    },
  )
  .handler(async ({ data }) => {
    const stripe = createStripeClient(data.environment);

    const prices = await stripe.prices.list({ lookup_keys: [data.priceId] });
    if (!prices.data.length) throw new Error("Price not found");
    const stripePrice = prices.data[0];

    const session = await stripe.checkout.sessions.create({
      line_items: [{ price: stripePrice.id, quantity: 1 }],
      mode: "payment",
      ui_mode: "embedded_page",
      return_url: data.returnUrl,
      managed_payments: { enabled: true },
      ...(data.customerEmail && { customer_email: data.customerEmail }),
    } as any);

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
