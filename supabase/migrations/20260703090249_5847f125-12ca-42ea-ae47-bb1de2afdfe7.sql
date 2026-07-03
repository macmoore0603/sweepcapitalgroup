
CREATE TABLE public.revenue_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  stripe_session_id text UNIQUE NOT NULL,
  email text,
  amount_cents integer NOT NULL,
  currency text NOT NULL DEFAULT 'usd',
  product_name text,
  environment text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT ON public.revenue_events TO authenticated;
GRANT ALL ON public.revenue_events TO service_role;
ALTER TABLE public.revenue_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "admins view revenue" ON public.revenue_events FOR SELECT TO authenticated USING (public.has_role(auth.uid(), 'admin'));

CREATE TABLE public.checkout_intents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  stripe_session_id text UNIQUE NOT NULL,
  email text,
  product_name text,
  amount_cents integer,
  currency text DEFAULT 'usd',
  environment text NOT NULL,
  status text NOT NULL DEFAULT 'open',
  recovery_sent_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON public.checkout_intents (status, created_at);
GRANT SELECT ON public.checkout_intents TO authenticated;
GRANT ALL ON public.checkout_intents TO service_role;
ALTER TABLE public.checkout_intents ENABLE ROW LEVEL SECURITY;
CREATE POLICY "admins view intents" ON public.checkout_intents FOR SELECT TO authenticated USING (public.has_role(auth.uid(), 'admin'));

CREATE TABLE public.nurture_state (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id uuid UNIQUE,
  email text NOT NULL,
  name text,
  tier text,
  step integer NOT NULL DEFAULT 0,
  last_sent_at timestamptz,
  next_send_at timestamptz NOT NULL DEFAULT now() + interval '1 day',
  stopped boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON public.nurture_state (stopped, next_send_at);
GRANT SELECT ON public.nurture_state TO authenticated;
GRANT ALL ON public.nurture_state TO service_role;
ALTER TABLE public.nurture_state ENABLE ROW LEVEL SECURITY;
CREATE POLICY "admins view nurture" ON public.nurture_state FOR SELECT TO authenticated USING (public.has_role(auth.uid(), 'admin'));
