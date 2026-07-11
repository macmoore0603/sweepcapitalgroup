
CREATE TABLE public.outbound_contacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL,
  name text,
  company text,
  role text,
  source text,
  status text NOT NULL DEFAULT 'queued',
  step int NOT NULL DEFAULT 0,
  next_send_at timestamptz NOT NULL DEFAULT now(),
  last_sent_at timestamptz,
  last_error text,
  added_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT outbound_contacts_email_unique UNIQUE (email),
  CONSTRAINT outbound_contacts_status_chk CHECK (status IN ('queued','contacted','replied','converted','stopped'))
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.outbound_contacts TO authenticated;
GRANT ALL ON public.outbound_contacts TO service_role;
ALTER TABLE public.outbound_contacts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "admins read outbound" ON public.outbound_contacts
  FOR SELECT TO authenticated USING (public.has_role(auth.uid(),'admin'));
CREATE POLICY "admins insert outbound" ON public.outbound_contacts
  FOR INSERT TO authenticated WITH CHECK (public.has_role(auth.uid(),'admin'));
CREATE POLICY "admins update outbound" ON public.outbound_contacts
  FOR UPDATE TO authenticated USING (public.has_role(auth.uid(),'admin')) WITH CHECK (public.has_role(auth.uid(),'admin'));
CREATE POLICY "admins delete outbound" ON public.outbound_contacts
  FOR DELETE TO authenticated USING (public.has_role(auth.uid(),'admin'));

CREATE INDEX outbound_contacts_due_idx ON public.outbound_contacts (next_send_at)
  WHERE status IN ('queued','contacted');

CREATE TRIGGER outbound_contacts_set_updated
  BEFORE UPDATE ON public.outbound_contacts
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
