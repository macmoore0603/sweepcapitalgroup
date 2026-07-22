
-- 1. AI personalization columns for outbound
ALTER TABLE public.outbound_contacts
  ADD COLUMN IF NOT EXISTS ai_angle TEXT,
  ADD COLUMN IF NOT EXISTS ai_first_message TEXT;

-- 2. Inbound replies
CREATE TABLE IF NOT EXISTS public.inbound_replies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  from_email TEXT NOT NULL,
  subject TEXT,
  body TEXT,
  intent TEXT,
  confidence NUMERIC,
  auto_reply_sent BOOLEAN NOT NULL DEFAULT false,
  related_contact_id UUID REFERENCES public.outbound_contacts(id) ON DELETE SET NULL,
  raw JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT ON public.inbound_replies TO authenticated;
GRANT ALL ON public.inbound_replies TO service_role;
ALTER TABLE public.inbound_replies ENABLE ROW LEVEL SECURITY;
CREATE POLICY "admins read replies" ON public.inbound_replies FOR SELECT TO authenticated
  USING (public.has_role(auth.uid(), 'admin'));
CREATE POLICY "service writes replies" ON public.inbound_replies FOR ALL TO service_role
  USING (true) WITH CHECK (true);
CREATE INDEX IF NOT EXISTS inbound_replies_from_email_idx ON public.inbound_replies(from_email);
CREATE INDEX IF NOT EXISTS inbound_replies_created_at_idx ON public.inbound_replies(created_at DESC);

-- 3. Daily reports
CREATE TABLE IF NOT EXISTS public.daily_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  report_date DATE NOT NULL UNIQUE,
  summary TEXT NOT NULL,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT ON public.daily_reports TO authenticated;
GRANT ALL ON public.daily_reports TO service_role;
ALTER TABLE public.daily_reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY "admins read reports" ON public.daily_reports FOR SELECT TO authenticated
  USING (public.has_role(auth.uid(), 'admin'));
CREATE POLICY "service writes reports" ON public.daily_reports FOR ALL TO service_role
  USING (true) WITH CHECK (true);
