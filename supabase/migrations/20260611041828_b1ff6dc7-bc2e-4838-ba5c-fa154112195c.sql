UPDATE public.sierra_settings
SET system_prompt = REPLACE(system_prompt, 'Lexus Nexus Capital', 'Sweep Capital Group'),
    updated_at = now()
WHERE system_prompt LIKE '%Lexus Nexus Capital%';

DO $$
BEGIN
  PERFORM cron.unschedule('sierra-reminders-tick');
EXCEPTION WHEN OTHERS THEN
  NULL;
END $$;

SELECT cron.schedule(
  'sierra-reminders-tick',
  '* * * * *',
  $$
  SELECT net.http_post(
    url := 'https://sweepcapitalgroup.lovable.app/api/public/sierra/reminders/tick',
    headers := '{"Content-Type":"application/json","apikey":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InV2d3FoeWVlenNvdHN0bGl0cmxvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg4ODk1MDAsImV4cCI6MjA5NDQ2NTUwMH0.A02_xertH6HqKFxIHTcryldzlhCmYqjyl9UIqY8sbCQ"}'::jsonb,
    body := '{}'::jsonb
  );
  $$
);

DROP POLICY IF EXISTS "Users can only subscribe to their own channels" ON realtime.messages;
CREATE POLICY "Users can only subscribe to their own channels"
ON realtime.messages
FOR SELECT
TO authenticated
USING (
  auth.uid() IS NOT NULL
  AND split_part(realtime.topic(), ':', 2) = auth.uid()::text
);