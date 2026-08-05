ALTER TABLE public.checkout_intents
  ADD COLUMN IF NOT EXISTS referral_code TEXT;

GRANT SELECT, INSERT, UPDATE ON public.checkout_intents TO service_role;
GRANT SELECT, INSERT, UPDATE ON public.checkout_intents TO authenticated;
GRANT SELECT, INSERT, UPDATE ON public.checkout_intents TO anon;
