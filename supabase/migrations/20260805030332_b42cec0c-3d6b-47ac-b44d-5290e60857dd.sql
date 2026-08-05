-- Referral program: lightweight tracking for leads who share the playbook/offer.

-- 1. Add referral code to leads
ALTER TABLE public.leads
  ADD COLUMN IF NOT EXISTS referral_code TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS referred_by TEXT;

-- 2. Track referral link clicks
CREATE TABLE IF NOT EXISTS public.referral_clicks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT NOT NULL,
  ip TEXT,
  user_agent TEXT,
  utm_source TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_referral_clicks_code ON public.referral_clicks(code);

-- 3. Track referral conversions (checkout completed)
CREATE TABLE IF NOT EXISTS public.referral_conversions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT NOT NULL,
  lead_id UUID REFERENCES public.leads(id) ON DELETE SET NULL,
  stripe_session_id TEXT,
  amount_cents INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_referral_conversions_code ON public.referral_conversions(code);

-- 4. Grants
GRANT SELECT, INSERT, UPDATE ON public.leads TO anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.referral_clicks TO anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.referral_conversions TO service_role;
GRANT SELECT ON public.referral_conversions TO authenticated;

-- 5. RLS
ALTER TABLE public.referral_clicks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Anyone can create referral clicks"
  ON public.referral_clicks FOR INSERT TO anon, authenticated WITH CHECK (true);
CREATE POLICY "Admins can view referral clicks"
  ON public.referral_clicks FOR SELECT TO authenticated USING (public.has_role(auth.uid(), 'admin'));

ALTER TABLE public.referral_conversions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role can create conversions"
  ON public.referral_conversions FOR INSERT TO service_role WITH CHECK (true);
CREATE POLICY "Admins can view conversions"
  ON public.referral_conversions FOR SELECT TO authenticated USING (public.has_role(auth.uid(), 'admin'));
