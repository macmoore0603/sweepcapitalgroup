DROP POLICY IF EXISTS "authenticated can read revenue settings" ON public.revenue_settings;

CREATE POLICY "admins can read revenue settings"
ON public.revenue_settings
FOR SELECT
TO authenticated
USING (public.has_role(auth.uid(), 'admin'));

GRANT SELECT ON public.revenue_settings TO authenticated;
GRANT ALL ON public.revenue_settings TO service_role;