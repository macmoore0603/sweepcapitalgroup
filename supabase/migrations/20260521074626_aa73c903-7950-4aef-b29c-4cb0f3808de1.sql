
-- Sierra: personal AI assistant tables

CREATE TABLE public.sierra_settings (
  user_id uuid PRIMARY KEY,
  twilio_phone_e164 text,
  system_prompt text NOT NULL DEFAULT 'You are Sierra, a sharp, warm, restrained personal AI concierge for the owner of Lexus Nexus Capital. Speak briefly and directly, like a top executive assistant — no fluff, no emojis. Use tools to actually get things done: schedule social posts, set reminders, search the web, send emails. When you take an action, confirm it crisply. When you do not know, say so. You are speaking by SMS or phone, so keep responses tight (1-3 short sentences for voice, up to ~300 chars for SMS unless the user asks for detail).',
  voice text NOT NULL DEFAULT 'Polly.Joanna-Neural',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.sierra_settings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Owner reads own sierra settings" ON public.sierra_settings FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "Owner inserts own sierra settings" ON public.sierra_settings FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Owner updates own sierra settings" ON public.sierra_settings FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE TRIGGER sierra_settings_updated_at BEFORE UPDATE ON public.sierra_settings FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE public.sierra_owners (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  phone_e164 text NOT NULL,
  label text,
  is_admin boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (phone_e164)
);
CREATE INDEX sierra_owners_user_idx ON public.sierra_owners(user_id);
ALTER TABLE public.sierra_owners ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Owner reads own sierra owners" ON public.sierra_owners FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "Owner inserts own sierra owners" ON public.sierra_owners FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Owner updates own sierra owners" ON public.sierra_owners FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Owner deletes own sierra owners" ON public.sierra_owners FOR DELETE TO authenticated USING (auth.uid() = user_id);

CREATE TABLE public.sierra_conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone_e164 text NOT NULL UNIQUE,
  owner_user_id uuid NOT NULL,
  last_channel text NOT NULL DEFAULT 'sms' CHECK (last_channel IN ('sms','voice')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.sierra_conversations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Owner reads own sierra conversations" ON public.sierra_conversations FOR SELECT TO authenticated USING (auth.uid() = owner_user_id);
CREATE TRIGGER sierra_conv_updated_at BEFORE UPDATE ON public.sierra_conversations FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE public.sierra_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES public.sierra_conversations(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('user','assistant','tool','system')),
  channel text NOT NULL CHECK (channel IN ('sms','voice')),
  content text NOT NULL DEFAULT '',
  parts jsonb,
  twilio_sid text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sierra_messages_conv_idx ON public.sierra_messages(conversation_id, created_at);
ALTER TABLE public.sierra_messages ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Owner reads own sierra messages" ON public.sierra_messages FOR SELECT TO authenticated USING (
  EXISTS (SELECT 1 FROM public.sierra_conversations c WHERE c.id = sierra_messages.conversation_id AND c.owner_user_id = auth.uid())
);

ALTER PUBLICATION supabase_realtime ADD TABLE public.sierra_messages;
ALTER TABLE public.sierra_messages REPLICA IDENTITY FULL;

CREATE TABLE public.sierra_reminders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id uuid NOT NULL,
  phone_e164 text NOT NULL,
  body text NOT NULL,
  due_at timestamptz NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','cancelled','failed')),
  sent_at timestamptz,
  error text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sierra_reminders_due_idx ON public.sierra_reminders(status, due_at);
ALTER TABLE public.sierra_reminders ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Owner reads own sierra reminders" ON public.sierra_reminders FOR SELECT TO authenticated USING (auth.uid() = owner_user_id);
CREATE POLICY "Owner inserts own sierra reminders" ON public.sierra_reminders FOR INSERT TO authenticated WITH CHECK (auth.uid() = owner_user_id);
CREATE POLICY "Owner updates own sierra reminders" ON public.sierra_reminders FOR UPDATE TO authenticated USING (auth.uid() = owner_user_id) WITH CHECK (auth.uid() = owner_user_id);
CREATE POLICY "Owner deletes own sierra reminders" ON public.sierra_reminders FOR DELETE TO authenticated USING (auth.uid() = owner_user_id);

-- pg_cron: tick reminders every minute
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

SELECT cron.schedule(
  'sierra-reminders-tick',
  '* * * * *',
  $$
  SELECT net.http_post(
    url := 'https://lexusnexuscapital.lovable.app/api/public/sierra/reminders/tick',
    headers := '{"Content-Type":"application/json","apikey":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InV2d3FoeWVlenNvdHN0bGl0cmxvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg4ODk1MDAsImV4cCI6MjA5NDQ2NTUwMH0.A02_xertH6HqKFxIHTcryldzlhCmYqjyl9UIqY8sbCQ"}'::jsonb,
    body := '{}'::jsonb
  );
  $$
);
