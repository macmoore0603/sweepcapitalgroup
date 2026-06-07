import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { getCheckoutSessionStatus } from "@/lib/checkout.functions";
import { getStripeEnvironment } from "@/lib/stripe";

type Status = Awaited<ReturnType<typeof getCheckoutSessionStatus>>;

export const Route = createFileRoute("/checkout/return")({
  validateSearch: (search: Record<string, unknown>): { session_id?: string } => ({
    session_id: typeof search.session_id === "string" ? search.session_id : undefined,
  }),
  component: CheckoutReturn,
  head: () => ({
    meta: [{ title: "Order status — Momentum Trading" }],
  }),
});

function CheckoutReturn() {
  const { session_id } = Route.useSearch();
  const fetchStatus = useServerFn(getCheckoutSessionStatus);
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "missing" }
    | { kind: "error"; message: string }
    | { kind: "ready"; data: Status }
  >(session_id ? { kind: "loading" } : { kind: "missing" });
  const [polls, setPolls] = useState(0);

  useEffect(() => {
    if (!session_id) return;
    let cancelled = false;
    fetchStatus({ data: { sessionId: session_id, environment: getStripeEnvironment() } })
      .then((data) => {
        if (cancelled) return;
        setState({ kind: "ready", data });
      })
      .catch((err) => {
        if (cancelled) return;
        setState({ kind: "error", message: err?.message ?? "Could not load order status." });
      });
    return () => {
      cancelled = true;
    };
  }, [session_id, polls, fetchStatus]);

  // Auto-refresh while pending (max ~30s)
  useEffect(() => {
    if (state.kind !== "ready" || state.data.outcome !== "pending" || polls >= 10) return;
    const t = setTimeout(() => setPolls((p) => p + 1), 3000);
    return () => clearTimeout(t);
  }, [state, polls]);

  return (
    <div className="min-h-screen flex items-center justify-center px-6 py-16">
      <div className="max-w-lg w-full">{renderBody(state, session_id, () => setPolls((p) => p + 1))}</div>
    </div>
  );
}

function renderBody(
  state:
    | { kind: "loading" }
    | { kind: "missing" }
    | { kind: "error"; message: string }
    | { kind: "ready"; data: Status },
  sessionId: string | undefined,
  refresh: () => void,
) {
  if (state.kind === "missing") {
    return (
      <Panel
        eyebrow="No session"
        title="Nothing to confirm."
        body="We couldn't find a payment session. If you just paid, please check your email for a receipt."
      >
        <HomeLink />
      </Panel>
    );
  }

  if (state.kind === "loading") {
    return (
      <Panel eyebrow="Checking with Stripe…" title="Confirming your order." body="One moment while we verify your payment status." />
    );
  }

  if (state.kind === "error") {
    return (
      <Panel eyebrow="Error" title="We hit a snag." body={state.message}>
        <button
          onClick={refresh}
          className="self-start mt-2 px-6 py-3 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors"
        >
          Try again
        </button>
      </Panel>
    );
  }

  const { data } = state;
  const meta = (
    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm border-t border-accent/40 pt-4 mt-2">
      {data.productName && (
        <>
          <dt className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground self-center">Item</dt>
          <dd>{data.productName}</dd>
        </>
      )}
      {data.amountTotal > 0 && (
        <>
          <dt className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground self-center">Amount</dt>
          <dd>
            {data.currency} {data.amountTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </dd>
        </>
      )}
      {data.customerEmail && (
        <>
          <dt className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground self-center">Email</dt>
          <dd>{data.customerEmail}</dd>
        </>
      )}
      {sessionId && (
        <>
          <dt className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground self-center">Reference</dt>
          <dd className="font-mono text-xs break-all">{sessionId}</dd>
        </>
      )}
    </dl>
  );

  if (data.outcome === "success") {
    return (
      <Panel
        eyebrow="Payment received"
        title="Welcome to the program."
        body="Check your inbox for onboarding instructions. We'll reach out within 24 hours with next steps."
        tone="success"
      >
        {meta}
        <HomeLink />
      </Panel>
    );
  }

  if (data.outcome === "pending") {
    return (
      <Panel
        eyebrow="Payment processing"
        title="Hang tight — we're confirming."
        body="Your bank is still processing the payment. This page will refresh automatically. You can safely close this window — we'll email you once it clears."
        tone="pending"
      >
        {meta}
        <div className="flex gap-3 mt-2">
          <button
            onClick={refresh}
            className="px-6 py-3 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors"
          >
            Refresh now
          </button>
          <Link
            to="/"
            className="px-6 py-3 border border-accent text-foreground font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent/10 transition-colors"
          >
            Back to home
          </Link>
        </div>
      </Panel>
    );
  }

  return (
    <Panel
      eyebrow="Payment failed"
      title="Your payment didn't go through."
      body={data.errorMessage ?? "The payment was declined or canceled. No charge was made. You can try again with a different card."}
      tone="failed"
    >
      {meta}
      <div className="flex gap-3 mt-2">
        <Link
          to="/mentorship"
          className="px-6 py-3 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors"
        >
          Try again
        </Link>
        <Link
          to="/"
          className="px-6 py-3 border border-accent text-foreground font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent/10 transition-colors"
        >
          Back to home
        </Link>
      </div>
    </Panel>
  );
}

function Panel({
  eyebrow,
  title,
  body,
  tone = "neutral",
  children,
}: {
  eyebrow: string;
  title: string;
  body: string;
  tone?: "neutral" | "success" | "pending" | "failed";
  children?: React.ReactNode;
}) {
  const toneClass =
    tone === "success"
      ? "border-emerald-500/60"
      : tone === "pending"
        ? "border-amber-500/60"
        : tone === "failed"
          ? "border-red-500/60"
          : "border-accent";
  const eyebrowClass =
    tone === "success"
      ? "text-emerald-400"
      : tone === "pending"
        ? "text-amber-400"
        : tone === "failed"
          ? "text-red-400"
          : "text-accent";
  return (
    <div className={`flex flex-col gap-6 p-10 border ${toneClass} bg-white/[0.03]`}>
      <span className={`font-mono text-[11px] uppercase tracking-widest ${eyebrowClass}`}>{eyebrow}</span>
      <h1 className="text-4xl font-extrabold tracking-tighter uppercase">{title}</h1>
      <p className="text-sm text-muted-foreground text-pretty">{body}</p>
      {children}
    </div>
  );
}

function HomeLink() {
  return (
    <Link
      to="/"
      className="self-start mt-2 px-6 py-3 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors"
    >
      Back to home
    </Link>
  );
}
