import { createFileRoute } from '@tanstack/react-router'
import { enqueueTemplateEmail, serverSupabase } from '@/lib/email/send.server'

const SITE_URL = 'https://sweepcapitalgroup.com'
const DEFAULT_OFFSETS = [3, 7]
const DEFAULT_RECOVERY_MIN = 60

async function loadSettings(supabase: any) {
  const { data } = await supabase
    .from('revenue_settings')
    .select('nurture_day_offsets,recovery_window_minutes')
    .eq('id', 1).maybeSingle()
  const offsetsRaw = data?.nurture_day_offsets
  const offsets = Array.isArray(offsetsRaw)
    ? offsetsRaw.map((n: any) => Number(n)).filter((n) => Number.isFinite(n) && n > 0)
    : DEFAULT_OFFSETS
  return {
    offsets: (offsets.length ? offsets : DEFAULT_OFFSETS).slice().sort((a, b) => a - b),
    recoveryMin: data?.recovery_window_minutes ?? DEFAULT_RECOVERY_MIN,
  }
}

async function processAbandoned(recoveryMin: number) {
  const supabase: any = serverSupabase()
  const cutoff = new Date(Date.now() - recoveryMin * 60 * 1000).toISOString()
  const { data: intents } = await supabase
    .from('checkout_intents')
    .select('*')
    .eq('status', 'open')
    .is('recovery_sent_at', null)
    .lt('created_at', cutoff)
    .limit(25)
  let sent = 0
  for (const it of intents ?? []) {
    if (!it.email) continue
    const r = await enqueueTemplateEmail({
      templateName: 'abandoned-checkout',
      recipientEmail: it.email,
      data: { productName: it.product_name, resumeUrl: SITE_URL },
      idempotencyKey: `abandon-${it.stripe_session_id}`,
      label: 'abandoned-checkout',
    })
    if ((r as any).queued) sent++
    await supabase.from('checkout_intents')
      .update({ recovery_sent_at: new Date().toISOString() })
      .eq('id', it.id)
  }
  return sent
}

async function processNurture(offsets: number[]) {
  const supabase: any = serverSupabase()
  const now = new Date().toISOString()
  const maxStep = Math.min(offsets.length, 2) // we have templates for up to 2 nurture emails
  const { data: rows } = await supabase
    .from('nurture_state')
    .select('*')
    .eq('stopped', false)
    .lt('next_send_at', now)
    .lt('step', maxStep + 1)
    .limit(25)
  let sent = 0
  for (const s of rows ?? []) {
    const nextStep = s.step + 1
    const templates = ['nurture-day3', 'nurture-day7']
    const template = nextStep <= maxStep ? templates[nextStep - 1] : null
    if (template) {
      const r = await enqueueTemplateEmail({
        templateName: template,
        recipientEmail: s.email,
        data: { name: s.name, siteUrl: SITE_URL },
        idempotencyKey: `nurture-${s.id}-${nextStep}`,
        label: template,
      })
      if ((r as any).queued) sent++
    }
    const nextOffset = offsets[nextStep] ?? 0 // days until step after next
    const gapDays = nextOffset > 0 ? Math.max(1, nextOffset - (offsets[nextStep - 1] ?? 0)) : 0
    await supabase.from('nurture_state').update({
      step: nextStep,
      last_sent_at: now,
      next_send_at: new Date(Date.now() + gapDays * 24 * 60 * 60 * 1000).toISOString(),
      stopped: nextStep >= maxStep,
    }).eq('id', s.id)
  }
  return sent
}


async function topUpSocial() {
  // Best-effort ping to the existing social tick
  try {
    await fetch(`${process.env.SUPABASE_URL?.replace('.supabase.co', '') ?? ''}`).catch(() => {})
  } catch {}
  return 0
}

export const Route = createFileRoute('/api/public/revenue/tick')({
  server: {
    handlers: {
      POST: async () => {
        const settings = await loadSettings(serverSupabase()).catch(() => ({ offsets: DEFAULT_OFFSETS, recoveryMin: DEFAULT_RECOVERY_MIN }))
        const [abandoned, nurture] = await Promise.all([
          processAbandoned(settings.recoveryMin).catch((e) => { console.error('abandoned', e); return 0 }),
          processNurture(settings.offsets).catch((e) => { console.error('nurture', e); return 0 }),
        ])
        await topUpSocial()
        return Response.json({ ok: true, abandoned, nurture, at: new Date().toISOString() })
      },
      GET: async () => Response.json({ ok: true }),
    },
  },
})
