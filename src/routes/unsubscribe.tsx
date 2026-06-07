import { createFileRoute } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

export const Route = createFileRoute('/unsubscribe')({
  component: UnsubscribePage,
  head: () => ({ meta: [{ title: 'Unsubscribe — Momentum Trading' }] }),
})

type State =
  | { kind: 'loading' }
  | { kind: 'ready' }
  | { kind: 'already' }
  | { kind: 'invalid' }
  | { kind: 'submitting' }
  | { kind: 'done' }
  | { kind: 'error'; message: string }

function UnsubscribePage() {
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [token, setToken] = useState<string | null>(null)

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get('token')
    if (!t) {
      setState({ kind: 'invalid' })
      return
    }
    setToken(t)
    fetch(`/email/unsubscribe?token=${encodeURIComponent(t)}`)
      .then(async (r) => {
        const body = await r.json().catch(() => ({}))
        if (!r.ok) return setState({ kind: 'invalid' })
        if (body.valid) return setState({ kind: 'ready' })
        if (body.reason === 'already_unsubscribed') return setState({ kind: 'already' })
        setState({ kind: 'invalid' })
      })
      .catch(() => setState({ kind: 'invalid' }))
  }, [])

  const confirm = async () => {
    if (!token) return
    setState({ kind: 'submitting' })
    try {
      const r = await fetch('/email/unsubscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
      })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) return setState({ kind: 'error', message: body.error ?? 'Something went wrong' })
      if (body.success) return setState({ kind: 'done' })
      if (body.reason === 'already_unsubscribed') return setState({ kind: 'already' })
      setState({ kind: 'error', message: 'Unable to process unsubscribe' })
    } catch {
      setState({ kind: 'error', message: 'Network error' })
    }
  }

  return (
    <main className="min-h-screen bg-background text-foreground flex items-center justify-center px-6">
      <div className="max-w-md w-full border border-border p-10 bg-white/[0.02]">
        <span className="font-mono text-[11px] uppercase tracking-widest text-accent">
          Email preferences
        </span>
        <h1 className="text-3xl font-extrabold tracking-tighter mt-3 mb-4 uppercase">
          Unsubscribe
        </h1>

        {state.kind === 'loading' && (
          <p className="text-sm text-muted-foreground">Verifying your link…</p>
        )}

        {state.kind === 'ready' && (
          <>
            <p className="text-sm text-muted-foreground mb-6">
              Click below to confirm you want to stop receiving emails from
              Momentum Trading.
            </p>
            <button
              onClick={confirm}
              className="w-full bg-accent text-accent-foreground py-3 font-mono text-[11px] uppercase tracking-widest hover:opacity-90 transition"
            >
              Confirm unsubscribe
            </button>
          </>
        )}

        {state.kind === 'submitting' && (
          <p className="text-sm text-muted-foreground">Processing…</p>
        )}

        {state.kind === 'done' && (
          <p className="text-sm">
            You're unsubscribed. You won't receive any more emails from us.
          </p>
        )}

        {state.kind === 'already' && (
          <p className="text-sm">You've already unsubscribed. No further action needed.</p>
        )}

        {state.kind === 'invalid' && (
          <p className="text-sm text-muted-foreground">
            This unsubscribe link is invalid or has expired.
          </p>
        )}

        {state.kind === 'error' && (
          <p className="text-sm text-destructive">{state.message}</p>
        )}
      </div>
    </main>
  )
}
