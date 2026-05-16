CREATE OR REPLACE FUNCTION public.reschedule_lead_call(_lead_id uuid, _slot timestamptz)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  updated int;
BEGIN
  IF _slot IS NOT NULL AND (_slot < now() OR _slot > now() + interval '60 days') THEN
    RETURN false;
  END IF;
  UPDATE public.leads
    SET scheduled_at = _slot, updated_at = now()
    WHERE id = _lead_id
      AND scheduled_at IS NOT NULL
      AND scheduled_at > now();
  GET DIAGNOSTICS updated = ROW_COUNT;
  RETURN updated > 0;
END;
$$;

REVOKE ALL ON FUNCTION public.reschedule_lead_call(uuid, timestamptz) FROM public;
GRANT EXECUTE ON FUNCTION public.reschedule_lead_call(uuid, timestamptz) TO anon, authenticated;