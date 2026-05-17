import { createFileRoute } from '@tanstack/react-router'
import { createClient } from '@supabase/supabase-js'
import { render } from '@react-email/components'
import { createElement } from 'react'
import { type StripeEnv, createStripeClient, verifyWebhook } from '@/lib/stripe.server'
import { TEMPLATES } from '@/lib/email-templates/registry'

const SITE_NAME = 'Lexus Nexus Capital Group'
const SENDER_DOMAIN = 'notify.lexusnexuscapital.com'
const FROM_DOMAIN = 'notify.lexusnexuscapital.com'

function generateToken(): string {
  const bytes = new Uint8Array(32)
  crypto.getRandomValues(bytes)
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('')
}

function formatAmount(amountCents: number | null | undefined, currency: string | null | undefined): string {
  if (amountCents == null) return ''
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: (currency ?? 'usd').toUpperCase(),
  }).format(amountCents / 100)
}

async function sendPurchaseConfirmation(session: any) {
  const email: string | undefined =
    session?.customer_details?.email || session?.customer_email || undefined
  if (!email) {
    console.log('Webhook: no customer email on session, skipping')
    return
  }

  const supabaseUrl = process.env.SUPABASE_URL
  const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY
  if (!supabaseUrl || !supabaseServiceKey) {
    console.error('Webhook: supabase env missing')
    return
  }
  const supabase: any = createClient(supabaseUrl, supabaseServiceKey)
  const normalizedEmail = email.toLowerCase()

  const { data: suppressed } = await supabase
    .from('suppressed_emails')
    .select('id')
    .eq('email', normalizedEmail)
    .maybeSingle()
  if (suppressed) return

  // Idempotency — skip if we've already enqueued for this session
  const { data: existingLog } = await supabase
    .from('email_send_log')
    .select('id')
    .eq('template_name', 'purchase-confirmation')
    .eq('recipient_email', email)
    .ilike('error_message', `%${session.id}%`)
    .maybeSingle()
  if (existingLog) return

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

  const template = TEMPLATES['purchase-confirmation']
  if (!template) return

  const lineItem = session?.line_items?.data?.[0]
  const productName: string | undefined = lineItem?.description ?? undefined
  const name: string | undefined = session?.customer_details?.name ?? undefined
  const amount = formatAmount(session?.amount_total, session?.currency)

  const data = { name, productName, amount, reference: session.id }
  const element = createElement(template.component, data)
  const html = await render(element)
  const plainText = await render(element, { plainText: true })
  const subject =
    typeof template.subject === 'function' ? template.subject(data) : template.subject

  const messageId = crypto.randomUUID()

  await supabase.from('email_send_log').insert({
    message_id: messageId,
    template_name: 'purchase-confirmation',
    recipient_email: email,
    status: 'pending',
    error_message: `stripe_session:${session.id}`,
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
      label: 'purchase-confirmation',
      idempotency_key: `purchase-${session.id}`,
      unsubscribe_token: unsubscribeToken,
      queued_at: new Date().toISOString(),
    },
  })

  if (enqueueError) {
    console.error('Webhook enqueue failed', enqueueError)
    await supabase.from('email_send_log').insert({
      message_id: messageId,
      template_name: 'purchase-confirmation',
      recipient_email: email,
      status: 'failed',
      error_message: `enqueue failed for ${session.id}`,
    })
  }
}

async function handleEvent(event: { type: string; data: { object: any } }, env: StripeEnv) {
  switch (event.type) {
    case 'checkout.session.completed':
    case 'checkout.session.async_payment_succeeded': {
      const session = event.data.object
      if (session.payment_status === 'paid' || session.payment_status === 'no_payment_required') {
        if (!session.line_items?.data?.length) {
          try {
            const stripe = createStripeClient(env)
            const full = await stripe.checkout.sessions.retrieve(session.id, {
              expand: ['line_items'],
            })
            await sendPurchaseConfirmation(full)
          } catch (e) {
            console.error('Failed to expand session', e)
            await sendPurchaseConfirmation(session)
          }
        } else {
          await sendPurchaseConfirmation(session)
        }
      }
      break
    }
    default:
      console.log('Unhandled webhook event:', event.type)
  }
}

export const Route = createFileRoute('/api/public/payments/webhook')({
  server: {
    handlers: {
      POST: async ({ request }) => {
        const rawEnv = new URL(request.url).searchParams.get('env')
        if (rawEnv !== 'sandbox' && rawEnv !== 'live') {
          console.error('Webhook received with invalid env:', rawEnv)
          return Response.json({ received: true, ignored: 'invalid env' })
        }
        const env: StripeEnv = rawEnv
        try {
          const event = await verifyWebhook(request, env)
          await handleEvent(event, env)
          return Response.json({ received: true })
        } catch (e) {
          console.error('Webhook error:', e)
          return new Response('Webhook error', { status: 400 })
        }
      },
    },
  },
})
