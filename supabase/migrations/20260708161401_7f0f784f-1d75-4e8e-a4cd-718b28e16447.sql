
CREATE TABLE public.revenue_settings (
  id smallint PRIMARY KEY DEFAULT 1,
  target_cents integer NOT NULL DEFAULT 1000000,
  nurture_day_offsets jsonb NOT NULL DEFAULT '[3,7]'::jsonb,
  recovery_window_minutes integer NOT NULL DEFAULT 60,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT revenue_settings_singleton CHECK (id = 1)
);

GRANT SELECT ON public.revenue_settings TO authenticated;
GRANT ALL ON public.revenue_settings TO service_role;

ALTER TABLE public.revenue_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "authenticated can read revenue settings"
  ON public.revenue_settings FOR SELECT TO authenticated USING (true);

CREATE POLICY "admins can update revenue settings"
  ON public.revenue_settings FOR UPDATE TO authenticated
  USING (public.has_role(auth.uid(), 'admin'))
  WITH CHECK (public.has_role(auth.uid(), 'admin'));

CREATE POLICY "admins can insert revenue settings"
  ON public.revenue_settings FOR INSERT TO authenticated
  WITH CHECK (public.has_role(auth.uid(), 'admin'));

INSERT INTO public.revenue_settings (id) VALUES (1) ON CONFLICT DO NOTHING;
