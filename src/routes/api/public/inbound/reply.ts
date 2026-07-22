import { createFileRoute } from '@tanstack/react-router'
import { createClient } from '@supabase/supabase-js'
import { callAI } from '@/lib/ai.server'
import { enqueueTemplateEmail } from '@/lib/email/send.server'

/**
 * Inbound reply webhook. Configure your inbound email provider (Postmark inbound,
 * SES inbound → SNS → HTTPS, Cloudflare Email Routing → Worker, etc.) to POST
 * JSON here: { from, subject, body, raw? }.
 *
 * Optional HMAC verification: set INBOUND_WEBHOOK_SECRET; the provider must
 * send X-Inbound-Signature = hex(hmac_sha256(secret, rawBody)).
 */
export const Route = createFileRoute('/api/public/inbound/reply')({
  server: {
    handlers: {
      POST: async ({ request }) => {
        const raw = await request.text()

        const secret = process.env.INBOUND_WEBHOOK_SECRET
        if (secret) {
          const sig = request.headers.get('x-inbound-signature') ?? ''
          const { createHmac, timingSafeEqual } = await import('crypto')
          const expected = createHmac('sha256', secret).update(raw).digest('hex')
          const a = Buffer.from(sig)
          const b = Buffer.from(expected)
          if (a.length !== b.length || !timingSafeEqual(a, b)) {
            return new Response('invalid signature', { status: 401 })
          }
        }

        let payload: any
        try { payload = JSON.parse(raw) } catch { return new Response('bad json', { status: 400 }) }

        const from = String(payload.from ?? payload.From ?? payload.sender ?? '').toLowerCase().trim()
        const subject = String(payload.subject ?? payload.Subject ?? '').slice(0, 500)
        const body = String(payload.body ?? payload.text ?? payload.Body ?? payload['text-plain'] ?? '').slice(0, 5000)
        if (!from || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(from.replace(/.*<|>.*/g, ''))) {
          return new Response('missing from', { status: 400 })
        }
        const fromEmail = from.replace(/.*<|>.*/g, '').trim()

        const supabase = createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_SERVICE_ROLE_KEY!)

        // AI classify
        let intent = 'other'
        let confidence = 0
        let autoReply = ''
        try {
          const out = await callAI(
            [
              {
                role: 'system',
                content:
                  'Classify a reply to a cold outreach email from Sweep Capital Group (futures trading mentorship). Output ONLY JSON: {"intent": "interested" | "objection" | "stop" | "other", "confidence": 0..1, "reply": "<optional short polite reply, or empty>"}. If they ask to stop/unsubscribe/remove — intent=stop. If they show interest or ask about pricing/tiers/booking — intent=interested with a short friendly reply pointing to https://sweepcapitalgroup.com/#pricing. If they push back on cost/legitimacy — intent=objection with a short empathetic reply. Otherwise other.',
              },
              { role: 'user', content: `Subject: ${subject}\n\n${body}` },
            ],
            { maxTokens: 300, temperature: 0.3 },
          )
          const j = out.match(/\{[\s\S]*\}/)?.[0]
          if (j) {
            const p = JSON.parse(j)
            intent = String(p.intent ?? 'other')
            confidence = Number(p.confidence ?? 0)
            autoReply = String(p.reply ?? '')
          }
        } catch (e) {
          console.error('classify error', e)
        }

        // Look up related contact
        const { data: contact } = await supabase
          .from('outbound_contacts').select('id').eq('email', fromEmail).maybeSingle()

        // React based on intent
        let sent = false
        if (intent === 'stop') {
          await supabase.from('suppressed_emails').upsert({ email: fromEmail }, { onConflict: 'email' })
          if (contact) await supabase.from('outbound_contacts').update({ status: 'stopped' }).eq('id', contact.id)
        } else if (intent === 'interested' || intent === 'objection') {
          if (contact) await supabase.from('outbound_contacts').update({ status: 'replied' }).eq('id', contact.id)
          if (autoReply && autoReply.length > 10) {
            // Fire-and-forget reply using transactional pipeline
            const templateName = 'lead-confirmation' // reuse an existing template shell
            const r = await enqueueTemplateEmail({
              templateName,
              recipientEmail: fromEmail,
              data: { name: 'there', customMessage: autoReply },
              idempotencyKey: `auto-reply-${fromEmail}-${Date.now()}`,
              label: 'inbound-auto-reply',
            }).catch(() => ({}))
            sent = (r as any).queued === true
          }
        }

        await supabase.from('inbound_replies').insert({
          from_email: fromEmail,
          subject,
          body,
          intent,
          confidence,
          auto_reply_sent: sent,
          related_contact_id: contact?.id ?? null,
          raw: payload,
        })

        return Response.json({ ok: true, intent, sent })
      },
      GET: async () => Response.json({ ok: true, hint: 'POST inbound emails here' }),
    },
  },
})
