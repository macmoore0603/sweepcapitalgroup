import { createServerFn } from '@tanstack/react-start'
import { requireSupabaseAuth } from '@/integrations/supabase/auth-middleware'
import { callAI } from '@/lib/ai.server'
import { PLATFORMS, type Platform } from '@/lib/social/types'
import { buildSystemPrompt } from '@/lib/social/prompts'
import { runGuardrails } from '@/lib/social/guardrails'

async function assertAdmin(context: any) {
  const { data: isAdmin } = await context.supabase.rpc('has_role', {
    _user_id: context.userId,
    _role: 'admin',
  })
  if (!isAdmin) throw new Error('Forbidden')
}

/**
 * Generate personalized "angles" + first-message drafts for outbound contacts
 * that don't have one yet. Runs on-demand from the /agent dashboard.
 */
export const enrichOutboundAngles = createServerFn({ method: 'POST' })
  .middleware([requireSupabaseAuth])
  .inputValidator((input: { limit?: number }) => input ?? {})
  .handler(async ({ data, context }) => {
    await assertAdmin(context)
    const { supabase } = context as any
    const limit = Math.min(Math.max(data.limit ?? 20, 1), 50)

    const { data: rows } = await supabase
      .from('outbound_contacts')
      .select('id,email,name,company,role')
      .is('ai_angle', null)
      .eq('status', 'queued')
      .limit(limit)

    let updated = 0
    for (const r of rows ?? []) {
      try {
        const raw = await callAI(
          [
            {
              role: 'system',
              content:
                'You write cold-email outreach for Sweep Capital Group, a futures/ICT-style trading mentorship. Output ONLY JSON: {"angle": "<1 sentence hook tailored to this person>", "message": "<2-3 sentence personal opener, no signature>"}. Be specific, no hype, no guarantees.',
            },
            {
              role: 'user',
              content: `Prospect: ${r.name ?? 'trader'} | role: ${r.role ?? 'unknown'} | company: ${r.company ?? 'unknown'} | email: ${r.email}`,
            },
          ],
          { maxTokens: 300, temperature: 0.8 },
        )
        const json = raw.match(/\{[\s\S]*\}/)?.[0]
        if (!json) continue
        const parsed = JSON.parse(json)
        await supabase
          .from('outbound_contacts')
          .update({ ai_angle: parsed.angle, ai_first_message: parsed.message })
          .eq('id', r.id)
        updated++
      } catch (e) {
        console.error('enrich failed for', r.email, e)
      }
    }
    return { updated, total: rows?.length ?? 0 }
  })

/**
 * Auto-fill the next N days of social posts across all connected accounts.
 * Uses the existing scheduled_posts table.
 */
export const seedContentCalendar = createServerFn({ method: 'POST' })
  .middleware([requireSupabaseAuth])
  .inputValidator((input: { days?: number; postsPerDay?: number }) => input ?? {})
  .handler(async ({ data, context }) => {
    await assertAdmin(context)
    const { supabase, userId } = context as any
    const days = Math.min(Math.max(data.days ?? 30, 1), 60)
    const postsPerDay = Math.min(Math.max(data.postsPerDay ?? 3, 1), 6)

    const { data: accounts } = await supabase
      .from('social_accounts')
      .select('id,platform')
      .eq('user_id', userId)
    if (!accounts || accounts.length === 0) {
      return { created: 0, message: 'No social accounts connected yet.' }
    }

    const themes = [
      'Session Sweep setup on ES futures',
      '5-15 Gap identification tutorial',
      'Power of 3 breakdown with example chart',
      'Common trader mistake and how to avoid it',
      'Mindset / discipline reminder for consistency',
      'Behind the scenes of a Managed Trading week',
      'Client win recap (no dollar guarantees)',
    ]

    let created = 0
    const now = Date.now()
    for (let d = 0; d < days; d++) {
      for (let p = 0; p < postsPerDay; p++) {
        const acct = accounts[Math.floor(Math.random() * accounts.length)]
        const platform = acct.platform as Platform
        const theme = themes[Math.floor(Math.random() * themes.length)]
        try {
          const sys = buildSystemPrompt(platform, undefined)
          const body = await callAI(
            [
              { role: 'system', content: sys },
              { role: 'user', content: `Draft a ${platform} post about: ${theme}. Be concrete, no guarantees, no financial-advice claims.` },
            ],
            { maxTokens: 350, temperature: 0.85 },
          )
          const g = runGuardrails(platform, body)
          if (!g.ok) continue
          const scheduledFor = new Date(now + d * 86400000 + p * 4 * 3600000 + 9 * 3600000).toISOString()
          await supabase.from('scheduled_posts').insert({
            account_id: acct.id,
            user_id: userId,
            body: g.sanitized,
            platform_post_id: null,
            media_urls: [],
            source: 'ai-calendar',
            goal: theme,
            status: 'scheduled',
            scheduled_for: scheduledFor,
          })
          created++
        } catch (e) {
          console.error('seed post failed', e)
        }
      }
    }
    return { created, days, postsPerDay }
  })

/**
 * Preview the latest daily report.
 */
export const getLatestDailyReport = createServerFn({ method: 'GET' })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    await assertAdmin(context)
    const { supabase } = context as any
    const { data } = await supabase
      .from('daily_reports')
      .select('*')
      .order('report_date', { ascending: false })
      .limit(1)
      .maybeSingle()
    return { report: data }
  })

/**
 * Recent inbound replies from prospects/customers.
 */
export const listInboundReplies = createServerFn({ method: 'GET' })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    await assertAdmin(context)
    const { supabase } = context as any
    const { data } = await supabase
      .from('inbound_replies')
      .select('id,from_email,subject,intent,confidence,auto_reply_sent,created_at')
      .order('created_at', { ascending: false })
      .limit(50)
    return { replies: data ?? [] }
  })
