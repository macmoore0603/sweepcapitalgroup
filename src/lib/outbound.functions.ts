import { createServerFn } from '@tanstack/react-start'
import { requireSupabaseAuth } from '@/integrations/supabase/auth-middleware'

// Very tolerant CSV / paste parser: accepts CSV with headers (email,name,company,role)
// or a bare newline-separated list of emails. Extra columns are ignored.
function parseInput(raw: string): Array<{ email: string; name?: string; company?: string; role?: string }> {
  const out: Array<{ email: string; name?: string; company?: string; role?: string }> = []
  const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
  if (!lines.length) return out
  const first = lines[0].toLowerCase()
  const hasHeader = first.includes('email')
  let cols = ['email', 'name', 'company', 'role']
  let start = 0
  if (hasHeader) {
    cols = lines[0].split(/[,\t]/).map((c) => c.trim().toLowerCase())
    start = 1
  }
  const idx = {
    email: cols.indexOf('email'),
    name: cols.indexOf('name'),
    company: cols.indexOf('company'),
    role: cols.indexOf('role'),
  }
  for (let i = start; i < lines.length; i++) {
    const parts = lines[i].split(/[,\t]/).map((p) => p.trim().replace(/^"|"$/g, ''))
    const email = (idx.email >= 0 ? parts[idx.email] : parts[0])?.toLowerCase()
    if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) continue
    out.push({
      email,
      name: idx.name >= 0 ? parts[idx.name] : undefined,
      company: idx.company >= 0 ? parts[idx.company] : undefined,
      role: idx.role >= 0 ? parts[idx.role] : undefined,
    })
  }
  return out
}

export const uploadOutboundContacts = createServerFn({ method: 'POST' })
  .middleware([requireSupabaseAuth])
  .inputValidator((input: { csv: string }) => input)
  .handler(async ({ data, context }) => {
    const { supabase, userId } = context as any
    const { data: isAdmin } = await supabase.rpc('has_role', { _user_id: userId, _role: 'admin' })
    if (!isAdmin) throw new Error('Forbidden')
    const rows = parseInput(data.csv)
    if (!rows.length) return { inserted: 0, skipped: 0, total: 0 }

    // Skip already-suppressed
    const { data: suppressed } = await supabase.from('suppressed_emails').select('email')
    const skipSet = new Set((suppressed ?? []).map((r: any) => (r.email || '').toLowerCase()))
    const clean = rows.filter((r) => !skipSet.has(r.email))

    const payload = clean.map((r, i) => ({
      email: r.email,
      name: r.name || null,
      company: r.company || null,
      role: r.role || null,
      source: 'csv',
      added_by: userId,
      // Stagger initial sends across ~4h so we don't burst-send
      next_send_at: new Date(Date.now() + (i % 48) * 5 * 60 * 1000).toISOString(),
    }))

    const { error, count } = await supabase
      .from('outbound_contacts')
      .upsert(payload, { onConflict: 'email', ignoreDuplicates: true, count: 'exact' })
    if (error) throw new Error(error.message)
    return { inserted: count ?? 0, skipped: rows.length - clean.length, total: rows.length }
  })

export const getOutboundStats = createServerFn({ method: 'GET' })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    const { supabase } = context as any
    const { data: rows } = await supabase
      .from('outbound_contacts')
      .select('status,step')
    const stats = { queued: 0, contacted: 0, replied: 0, converted: 0, stopped: 0, total: 0 }
    for (const r of rows ?? []) {
      stats.total++
      const s = r.status as keyof typeof stats
      if (s in stats) (stats as any)[s]++
    }
    const { data: recent } = await supabase
      .from('outbound_contacts')
      .select('email,company,status,step,last_sent_at,last_error')
      .order('updated_at', { ascending: false })
      .limit(10)
    return { stats, recent: recent ?? [] }
  })
