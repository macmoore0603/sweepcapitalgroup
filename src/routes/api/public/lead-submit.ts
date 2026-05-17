import { createFileRoute } from '@tanstack/react-router'
import { createClient } from '@supabase/supabase-js'
import { render } from '@react-email/components'
import { createElement } from 'react'
import { z } from 'zod'
import { TEMPLATES } from '@/lib/email-templates/registry'

const SITE_NAME = 'Lexus Nexus Capital Group'
const SENDER_DOMAIN = 'notify.lexusnexuscapital.com'
const FROM_DOMAIN = 'notify.lexusnexuscapital.com'

const optionalStr = (max: number) =>
  z.string().trim().max(max).optional().transform((v) => (v && v.length > 0 ? v : undefined))

const submitSchema = z.object({
  full_name: z.string().trim().min(2).max(120),
  email: z.string().trim().email().max(255),
  tier: z.string().trim().min(1).max(120),
  notes: z.string().trim().max(2000).optional(),
  utm_source: optionalStr(255),
  utm_medium: optionalStr(255),
  utm_campaign: optionalStr(255),
  utm_term: optionalStr(255),
  utm_content: optionalStr(255),
  referrer: optionalStr(2048),
  landing_page: optionalStr(2048),
})

function generateToken(): string {
  const bytes = new Uint8Array(32)
  crypto.getRandomValues(bytes)
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('')
}

export const Route = createFileRoute('/api/public/lead-submit')({
  server: {
    handlers: {
      POST: async ({ request }) => {
        const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
        const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY
        if (!supabaseUrl || !supabaseServiceKey) {
          return Response.json({ error: 'Server configuration error' }, { status: 500 })
        }

        let body: unknown
        try {
          body = await request.json()
        } catch {
          return Response.json({ error: 'Invalid JSON' }, { status: 400 })
        }
        const parsed = submitSchema.safeParse(body)
        if (!parsed.success) {
          return Response.json(
            { error: parsed.error.issues[0]?.message ?? 'Invalid input' },
            { status: 400 },
          )
        }
        const {
          full_name, email, tier, notes,
          utm_source, utm_medium, utm_campaign, utm_term, utm_content,
          referrer, landing_page,
        } = parsed.data
        const normalizedEmail = email.toLowerCase()

        const supabase: any = createClient(supabaseUrl, supabaseServiceKey)

        // 1. Insert the lead and capture id + booking token
        const { data: insertedLead, error: insertError } = await supabase
          .from('leads')
          .insert({
            full_name,
            email,
            capital_size: tier,
            notes: notes ?? null,
            utm_source: utm_source ?? null,
            utm_medium: utm_medium ?? null,
            utm_campaign: utm_campaign ?? null,
            utm_term: utm_term ?? null,
            utm_content: utm_content ?? null,
            referrer: referrer ?? null,
            landing_page: landing_page ?? null,
          })
          .select('id, booking_token')
          .single()
        if (insertError || !insertedLead) {
          console.error('Lead insert failed', { error: insertError })
          return Response.json({ error: 'Submission failed' }, { status: 500 })
        }

        // Derive an absolute booking URL from the incoming request origin.
        const requestUrl = new URL(request.url)
        const origin = `${requestUrl.protocol}//${requestUrl.host}`
        const bookingUrl = `${origin}/book?lead=${encodeURIComponent(insertedLead.id)}&token=${encodeURIComponent(insertedLead.booking_token)}`

        // 2. Check suppression — silently skip email if suppressed (still success for the form)
        const { data: suppressed } = await supabase
          .from('suppressed_emails')
          .select('id')
          .eq('email', normalizedEmail)
          .maybeSingle()

        if (suppressed) {
          return Response.json({ success: true, email_sent: false })
        }

        // 3. Get or create unsubscribe token
        let unsubscribeToken: string
        const { data: existing } = await supabase
          .from('email_unsubscribe_tokens')
          .select('token, used_at')
          .eq('email', normalizedEmail)
          .maybeSingle()

        if (existing && !existing.used_at) {
          unsubscribeToken = existing.token
        } else {
          unsubscribeToken = generateToken()
          await supabase
            .from('email_unsubscribe_tokens')
            .upsert(
              { token: unsubscribeToken, email: normalizedEmail },
              { onConflict: 'email', ignoreDuplicates: true },
            )
          const { data: stored } = await supabase
            .from('email_unsubscribe_tokens')
            .select('token')
            .eq('email', normalizedEmail)
            .maybeSingle()
          if (stored?.token) unsubscribeToken = stored.token
        }

        // 4. Render template
        const template = TEMPLATES['lead-confirmation']
        if (!template) {
          return Response.json({ success: true, email_sent: false })
        }
        const data = { name: full_name, tier, bookingUrl }
        const element = createElement(template.component, data)
        const html = await render(element)
        const plainText = await render(element, { plainText: true })
        const subject =
          typeof template.subject === 'function' ? template.subject(data) : template.subject

        const messageId = crypto.randomUUID()

        // 5. Log pending + enqueue
        await supabase.from('email_send_log').insert({
          message_id: messageId,
          template_name: 'lead-confirmation',
          recipient_email: email,
          status: 'pending',
        })

        const { error: enqueueError } = await supabase.rpc('enqueue_email', {
          queue_name: 'transactional_emails',
          payload: {
            message_id: messageId,
            to: email,
            from: `${SITE_NAME} <noreply@${FROM_DOMAIN}>`,
            sender_domain: SENDER_DOMAIN,
            subject,
            html,
            text: plainText,
            purpose: 'transactional',
            label: 'lead-confirmation',
            idempotency_key: `lead-${messageId}`,
            unsubscribe_token: unsubscribeToken,
            queued_at: new Date().toISOString(),
          },
        })

        if (enqueueError) {
          console.error('Enqueue failed', { error: enqueueError })
          await supabase.from('email_send_log').insert({
            message_id: messageId,
            template_name: 'lead-confirmation',
            recipient_email: email,
            status: 'failed',
            error_message: 'Failed to enqueue email',
          })
          return Response.json({ success: true, email_sent: false })
        }

        return Response.json({ success: true, email_sent: true })
      },
    },
  },
})
