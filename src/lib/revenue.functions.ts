import { createServerFn } from '@tanstack/react-start'
import { requireSupabaseAuth } from '@/integrations/supabase/auth-middleware'

const DEFAULT_TARGET_CENTS = 1_000_000
const DEFAULT_NURTURE_OFFSETS = [3, 7]
const DEFAULT_RECOVERY_WINDOW_MIN = 60

async function loadSettings(supabase: any) {
  const { data } = await supabase
    .from('revenue_settings')
    .select('target_cents,nurture_day_offsets,recovery_window_minutes')
    .eq('id', 1).maybeSingle()
  const offsetsRaw = data?.nurture_day_offsets
  const nurture_day_offsets = Array.isArray(offsetsRaw)
    ? offsetsRaw.map((n: any) => Number(n)).filter((n) => Number.isFinite(n) && n > 0)
    : DEFAULT_NURTURE_OFFSETS
  return {
    target_cents: data?.target_cents ?? DEFAULT_TARGET_CENTS,
    nurture_day_offsets: nurture_day_offsets.length ? nurture_day_offsets : DEFAULT_NURTURE_OFFSETS,
    recovery_window_minutes: data?.recovery_window_minutes ?? DEFAULT_RECOVERY_WINDOW_MIN,
  }
}

export const getRevenueSettings = createServerFn({ method: 'GET' })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => loadSettings((context as any).supabase))

export const updateRevenueSettings = createServerFn({ method: 'POST' })
  .middleware([requireSupabaseAuth])
  .inputValidator((input: { target_cents?: number; nurture_day_offsets?: number[]; recovery_window_minutes?: number }) => input)
  .handler(async ({ data, context }) => {
    const { supabase, userId } = context as any
    const { data: isAdmin } = await supabase.rpc('has_role', { _user_id: userId, _role: 'admin' })
    if (!isAdmin) throw new Error('Forbidden')

    const patch: Record<string, any> = { updated_at: new Date().toISOString() }
    if (typeof data.target_cents === 'number' && data.target_cents >= 100_000 && data.target_cents <= 100_000_000) {
      patch.target_cents = Math.round(data.target_cents)
    }
    if (Array.isArray(data.nurture_day_offsets)) {
      const cleaned = data.nurture_day_offsets
        .map((n) => Number(n))
        .filter((n) => Number.isFinite(n) && n >= 1 && n <= 365)
      if (cleaned.length >= 1 && cleaned.length <= 6) {
        // ensure strictly increasing
        const sorted = [...new Set(cleaned)].sort((a, b) => a - b)
        patch.nurture_day_offsets = sorted
      }
    }
    if (typeof data.recovery_window_minutes === 'number' && data.recovery_window_minutes >= 5 && data.recovery_window_minutes <= 10_080) {
      patch.recovery_window_minutes = Math.round(data.recovery_window_minutes)
    }

    const { error } = await supabase.from('revenue_settings').update(patch).eq('id', 1)
    if (error) throw new Error(error.message)
    return loadSettings(supabase)
  })

export const getRevenueSummary = createServerFn({ method: 'GET' })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    const { supabase } = context as any
    const settings = await loadSettings(supabase)
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
      targetCents: settings.target_cents,
      paceCents,
      salesCount: monthRows?.length ?? 0,
      openIntents: openIntents?.length ?? 0,
      activeNurture: nurture?.length ?? 0,
      recent: recent ?? [],
      settings,
    }
  })

