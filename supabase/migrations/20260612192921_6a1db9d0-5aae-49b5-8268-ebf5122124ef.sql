REVOKE INSERT, UPDATE, DELETE ON public.post_metrics FROM authenticated;

CREATE POLICY "post_metrics service-role insert"
  ON public.post_metrics FOR INSERT TO service_role WITH CHECK (true);

CREATE POLICY "post_metrics service-role update"
  ON public.post_metrics FOR UPDATE TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "post_metrics service-role delete"
  ON public.post_metrics FOR DELETE TO service_role USING (true);