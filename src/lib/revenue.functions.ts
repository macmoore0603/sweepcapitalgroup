import { createServerFn } from '@tanstack/react-start'
import { requireSupabaseAuth } from '@/integrations/supabase/auth-middleware'

const MONTHLY_TARGET_CENTS = 10_000_00

export const getRevenueSummary = createServerFn({ method: 'GET' })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    const { supabase } = context as any
    const startOfMonth = new Date()
    startOfMonth.setUTCDate(1); startOfMonth.setUTCHours(0, 0, 0, 0)

    const [{ data: monthRows }, { data: openIntents }, { data: nurture }, { data: recent }] = await Promise.all([
      supabase.from('revenue_events').select('amount_cents,created_at,product_name,email')
        .gte('created_at', startOfMonth.toISOString()),
      supabase.from('checkout_intents').select('id').eq('status', 'open'),
      supabase.from('nurture_state').select('id').eq('stopped', false),
      supabase.from('revenue_events').select('amount_cents,product_name,email,created_at')
        .order('created_at', { ascending: false }).limit(10),
    ])

    const monthCents = (monthRows ?? []).reduce((s: number, r: any) => s + (r.amount_cents ?? 0), 0)
    const day = new Date().getUTCDate()
    const daysInMonth = new Date(Date.UTC(new Date().getUTCFullYear(), new Date().getUTCMonth() + 1, 0)).getUTCDate()
    const paceCents = Math.round((monthCents / Math.max(day, 1)) * daysInMonth)

    return {
      monthCents,
      targetCents: MONTHLY_TARGET_CENTS,
      paceCents,
      salesCount: monthRows?.length ?? 0,
      openIntents: openIntents?.length ?? 0,
      activeNurture: nurture?.length ?? 0,
      recent: recent ?? [],
    }
  })
