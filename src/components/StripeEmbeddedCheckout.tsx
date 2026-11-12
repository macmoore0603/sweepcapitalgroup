import { EmbeddedCheckoutProvider, EmbeddedCheckout } from "@stripe/react-stripe-js";
import { getStripe, getStripeEnvironment } from "@/lib/stripe";
import { createCheckoutSession } from "@/lib/checkout.functions";
import { useEffect, useState } from 'react';
import type { Stripe } from '@stripe/stripe-js';

interface Props {
  priceId: string;
  customerEmail?: string;
  returnUrl?: string;
  referralCode?: string;
}

export function StripeEmbeddedCheckout({ priceId, customerEmail, returnUrl, referralCode }: Props) {
  const [stripe, setStripe] = useState<Stripe | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    getStripe().then((client) => {
      if (active) setStripe(client);
    }).catch(() => { if (active) setError('Payments are temporarily unavailable. Please contact us to enroll.'); });
    return () => { active = false; };
  }, []);
  const fetchClientSecret = async (): Promise<string> => {
    try {
      const secret = await createCheckoutSession({
      data: {
        priceId,
        customerEmail,
        returnUrl:
          returnUrl ||
          `${window.location.origin}/checkout/return?session_id={CHECKOUT_SESSION_ID}`,
        environment: await getStripeEnvironment(),
        referralCode,
      },
    });
    if (!secret) throw new Error("Failed to create checkout session");
    return secret;
    } catch (cause) {
      setError('Payments are temporarily unavailable for this program. Please contact us to enroll.');
      throw cause;
    }
  };

  if (error) return <p role="alert" className="py-8 text-foreground">{error}</p>;
  if (!stripe) return <p role="status" className="py-8 text-muted-foreground">Loading checkout…</p>;

  return (
    <div id="checkout">
      <EmbeddedCheckoutProvider stripe={stripe} options={{ fetchClientSecret }}>
        <EmbeddedCheckout />
      </EmbeddedCheckoutProvider>
    </div>
  );
}
