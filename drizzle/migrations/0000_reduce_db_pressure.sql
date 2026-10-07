CREATE INDEX IF NOT EXISTS idx_checkout_intents_recovery ON public.checkout_intents (created_at) WHERE status = 'open' AND recovery_sent_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_nurture_state_due ON public.nurture_state (next_send_at) WHERE stopped = false;
CREATE INDEX IF NOT EXISTS idx_outbound_contacts_due ON public.outbound_contacts (next_send_at) WHERE status IN ('queued','contacted');
DO $$ BEGIN
  PERFORM cron.unschedule('sierra-reminders-tick');
EXCEPTION WHEN OTHERS THEN NULL; END $$;
SELECT cron.alter_job(jobid, schedule := '*/5 * * * *') FROM cron.job WHERE jobname = 'social-agent-tick';