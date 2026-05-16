-- Add booking_token to leads
ALTER TABLE public.leads
  ADD COLUMN IF NOT EXISTS booking_token uuid NOT NULL DEFAULT gen_random_uuid();

-- Drop old function signatures
DROP FUNCTION IF EXISTS public.schedule_lead_call(uuid, timestamptz);
DROP FUNCTION IF EXISTS public.reschedule_lead_call(uuid, timestamptz);

-- Recreate schedule_lead_call with token verification
CREATE OR REPLACE FUNCTION public.schedule_lead_call(
  _lead_id uuid,
  _token uuid,
  _slot timestamptz
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  updated_count int;
BEGIN
  IF _slot IS NULL OR _slot <= now() OR _slot > now() + interval '60 days' THEN
    RETURN false;
  END IF;

  UPDATE public.leads
    SET scheduled_at = _slot,
        updated_at = now()
    WHERE id = _lead_id
      AND booking_token = _token
      AND scheduled_at IS NULL;

  GET DIAGNOSTICS updated_count = ROW_COUNT;
  RETURN updated_count > 0;
END;
$$;

-- Recreate reschedule_lead_call with token verification (supports cancel when _slot IS NULL)
CREATE OR REPLACE FUNCTION public.reschedule_lead_call(
  _lead_id uuid,
  _token uuid,
  _slot timestamptz
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  updated_count int;
BEGIN
  IF _slot IS NOT NULL AND (_slot <= now() OR _slot > now() + interval '60 days') THEN
    RETURN false;
  END IF;

  UPDATE public.leads
    SET scheduled_at = _slot,
        updated_at = now()
    WHERE id = _lead_id
      AND booking_token = _token
      AND (scheduled_at IS NULL OR scheduled_at > now());

  GET DIAGNOSTICS updated_count = ROW_COUNT;
  RETURN updated_count > 0;
END;
$$;

REVOKE ALL ON FUNCTION public.schedule_lead_call(uuid, uuid, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.reschedule_lead_call(uuid, uuid, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.schedule_lead_call(uuid, uuid, timestamptz) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reschedule_lead_call(uuid, uuid, timestamptz) TO anon, authenticated;