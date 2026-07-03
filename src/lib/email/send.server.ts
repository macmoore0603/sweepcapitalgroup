import { createClient } from '@supabase/supabase-js'
import { render } from '@react-email/components'
import { createElement } from 'react'
import { TEMPLATES } from '@/lib/email-templates/registry'

const SITE_NAME = 'Sweep Capital Group'
const SENDER_DOMAIN = 'notify.sweepcapitalgroup.com'
const FROM_DOMAIN = 'notify.sweepcapitalgroup.com'

function generateToken(): string {
  const bytes = new Uint8Array(32)
  crypto.getRandomValues(bytes)
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('')
}

export function serverSupabase() {
  const url = process.env.SUPABASE_URL
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY
  if (!url || !key) throw new Error('Supabase env missing')
  return createClient(url, key)
}

export async function enqueueTemplateEmail(opts: {
  templateName: string
  recipientEmail: string
  data: Record<string, any>
  idempotencyKey: string
  label?: string
}) {
  const template = TEMPLATES[opts.templateName]
  if (!template) throw new Error(`Unknown template ${opts.templateName}`)
  const supabase: any = serverSupabase()
  const email = opts.recipientEmail.toLowerCase()

  const { data: suppressed } = await supabase
    .from('suppressed_emails').select('id').eq('email', email).maybeSingle()
  if (suppressed) return { skipped: 'suppressed' as const }

  const { data: dup } = await supabase
    .from('email_send_log').select('id')
    .eq('template_name', opts.templateName)
    .eq('recipient_email', opts.recipientEmail)
    .ilike('error_message', `%${opts.idempotencyKey}%`)
    .maybeSingle()
  if (dup) return { skipped: 'duplicate' as const }

  let unsubscribeToken: string
  const { data: existing } = await supabase
    .from('email_unsubscribe_tokens').select('token, used_at').eq('email', email).maybeSingle()
  if (existing && !existing.used_at) unsubscribeToken = existing.token
  else {
    unsubscribeToken = generateToken()
    await supabase.from('email_unsubscribe_tokens')
      .upsert({ token: unsubscribeToken, email }, { onConflict: 'email', ignoreDuplicates: true })
    const { data: stored } = await supabase
      .from('email_unsubscribe_tokens').select('token').eq('email', email).maybeSingle()
    if (stored?.token) unsubscribeToken = stored.token
  }

  const element = createElement(template.component, opts.data)
  const html = await render(element)
  const text = await render(element, { plainText: true })
  const subject = typeof template.subject === 'function' ? template.subject(opts.data) : template.subject
  const messageId = crypto.randomUUID()

  await supabase.from('email_send_log').insert({
    message_id: messageId,
    template_name: opts.templateName,
    recipient_email: opts.recipientEmail,
    status: 'pending',
    error_message: `key:${opts.idempotencyKey}`,
  })

  const { error } = await supabase.rpc('enqueue_email', {
    queue_name: 'transactional_emails',
    payload: {
      message_id: messageId,
      to: opts.recipientEmail,
      from: `${SITE_NAME} <noreply@${FROM_DOMAIN}>`,
      sender_domain: SENDER_DOMAIN,
      subject, html, text,
      purpose: 'transactional',
      label: opts.label ?? opts.templateName,
      idempotency_key: opts.idempotencyKey,
      unsubscribe_token: unsubscribeToken,
      queued_at: new Date().toISOString(),
    },
  })
  if (error) return { error: error.message }
  return { queued: true as const }
}
