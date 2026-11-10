import { loadStripe, type Stripe } from "@stripe/stripe-js";
import { getStripePublicConfiguration } from '@/lib/checkout.functions';

type StripeEnv = "sandbox" | "live";

let stripePromise: Promise<Stripe | null> | null = null;

export async function getStripeConfiguration() {
  return getStripePublicConfiguration();
}

export function getStripe(): Promise<Stripe | null> {
  if (!stripePromise) {
    stripePromise = getStripeConfiguration().then(({ publishableKey }) => loadStripe(publishableKey));
    stripePromise.catch(() => { stripePromise = null; });
  }
  return stripePromise;
}

export async function getStripeEnvironment(): Promise<StripeEnv> {
  return (await getStripeConfiguration()).environment;
}
