import { createFileRoute } from '@tanstack/react-router'
import { enqueueTemplateEmail, serverSupabase } from '@/lib/email/send.server'

const SITE_URL = 'https://sweepcapitalgroup.com'

async function processAbandoned() {
  const supabase: any = serverSupabase()
  const cutoff = new Date(Date.now() - 60 * 60 * 1000).toISOString()
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

async function processNurture() {
  const supabase: any = serverSupabase()
  const now = new Date().toISOString()
  const { data: rows } = await supabase
    .from('nurture_state')
    .select('*')
    .eq('stopped', false)
    .lt('next_send_at', now)
    .lt('step', 3)
    .limit(25)
  let sent = 0
  for (const s of rows ?? []) {
    const nextStep = s.step + 1
    let template: string | null = null
    let nextDays = 0
    if (nextStep === 1) { template = 'nurture-day3'; nextDays = 4 }
    else if (nextStep === 2) { template = 'nurture-day7'; nextDays = 30 }
    else { template = null }
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
    await supabase.from('nurture_state').update({
      step: nextStep,
      last_sent_at: now,
      next_send_at: new Date(Date.now() + nextDays * 24 * 60 * 60 * 1000).toISOString(),
      stopped: nextStep >= 3,
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
        const [abandoned, nurture] = await Promise.all([
          processAbandoned().catch((e) => { console.error('abandoned', e); return 0 }),
          processNurture().catch((e) => { console.error('nurture', e); return 0 }),
        ])
        await topUpSocial()
        return Response.json({ ok: true, abandoned, nurture, at: new Date().toISOString() })
      },
      GET: async () => Response.json({ ok: true }),
    },
  },
})
