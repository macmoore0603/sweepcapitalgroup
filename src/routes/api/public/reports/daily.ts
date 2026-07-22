import { createFileRoute } from '@tanstack/react-router'
import { createClient } from '@supabase/supabase-js'
import { callAI } from '@/lib/ai.server'
import { enqueueTemplateEmail } from '@/lib/email/send.server'

/**
 * Daily agent report. Cron POSTs here at ~08:00 UTC.
 * Aggregates last 24h activity, generates AI summary, stores, emails admin.
 */
export const Route = createFileRoute('/api/public/reports/daily')({
  server: {
    handlers: {
      POST: async () => {
        const supabase = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!)
        const since = new Date(Date.now() - 24 * 3600 * 1000).toISOString()
        const today = new Date().toISOString().slice(0, 10)

        const [leadsQ, revQ, outQ, postsQ, repliesQ] = await Promise.all([
          supabase.from('leads').select('id,tier,status,created_at').gte('created_at', since),
          supabase.from('revenue_events').select('amount_cents,event_type,created_at').gte('created_at', since),
          supabase.from('outbound_contacts').select('status,step,last_sent_at').gte('last_sent_at', since),
          supabase.from('scheduled_posts').select('status,published_at').gte('created_at', since),
          supabase.from('inbound_replies').select('intent,created_at').gte('created_at', since),
        ])


        const leads = leadsQ.data ?? []
        const rev = revQ.data ?? []
        const out = outQ.data ?? []
        const posts = postsQ.data ?? []
        const replies = repliesQ.data ?? []

        const revenueCents = rev.reduce((s, r: any) => s + (r.amount_cents ?? 0), 0)
        const posted = posts.filter((p: any) => p.status === 'published').length
        const outSent = out.length
        const interested = replies.filter((r: any) => r.intent === 'interested').length
        const stops = replies.filter((r: any) => r.intent === 'stop').length

        const metrics = {
          new_leads: leads.length,
          revenue_usd: revenueCents / 100,
          outbound_sent: outSent,
          posts_published: posted,
          replies_total: replies.length,
          replies_interested: interested,
          replies_stopped: stops,
        }

        let summary = ''
        try {
          summary = await callAI(
            [
              {
                role: 'system',
                content:
                  'You write a crisp daily operations report for Sweep Capital Group\'s autonomous agent. 4-6 bullet points, no fluff. Include: what happened, what worked, what to fix, and 1 concrete next action.',
              },
              { role: 'user', content: `Last 24h metrics:\n${JSON.stringify(metrics, null, 2)}` },
            ],
            { maxTokens: 500, temperature: 0.5 },
          )
        } catch (e) {
          summary = `Auto-summary unavailable. Raw metrics: ${JSON.stringify(metrics)}`
        }

        await supabase.from('daily_reports').upsert(
          { report_date: today, summary, metrics },
          { onConflict: 'report_date' },
        )

        const adminEmail = (settingsQ.data as any)?.admin_email || 'macmoore@lexusnexuscapital.com'
        await enqueueTemplateEmail({
          templateName: 'ops-note',
          recipientEmail: adminEmail,
          data: {
            name: 'Mac',
            customMessage: `Daily Agent Report (${today})\n\n${summary}\n\nMetrics: ${JSON.stringify(metrics)}`,
          },
          idempotencyKey: `daily-report-${today}`,
          label: 'daily-agent-report',
        }).catch((e) => console.error('daily report email', e))

        return Response.json({ ok: true, metrics, summary })
      },
      GET: async () => Response.json({ ok: true }),
    },
  },
})
