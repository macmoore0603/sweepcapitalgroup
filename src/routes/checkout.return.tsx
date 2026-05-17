import { createFileRoute, Link } from "@tanstack/react-router";

export const Route = createFileRoute("/checkout/return")({
  validateSearch: (search: Record<string, unknown>): { session_id?: string } => ({
    session_id: typeof search.session_id === "string" ? search.session_id : undefined,
  }),
  component: CheckoutReturn,
  head: () => ({
    meta: [{ title: "Payment complete — Lexus Nexus Capital" }],
  }),
});

function CheckoutReturn() {
  const { session_id } = Route.useSearch();
  return (
    <div className="min-h-screen flex items-center justify-center px-6">
      <div className="max-w-lg w-full flex flex-col gap-6 p-10 border border-accent bg-white/[0.03]">
        <span className="font-mono text-[11px] uppercase tracking-widest text-accent">
          {session_id ? "Payment received" : "No session"}
        </span>
        <h1 className="text-4xl font-extrabold tracking-tighter uppercase">
          {session_id ? "Welcome to the program." : "Nothing to confirm."}
        </h1>
        <p className="text-sm text-muted-foreground text-pretty">
          {session_id
            ? "Check your inbox for onboarding instructions. We'll reach out within 24 hours with next steps."
            : "We couldn't find a payment session. If you just paid, please check your email for a receipt."}
        </p>
        <Link
          to="/"
          className="self-start mt-2 px-6 py-3 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors"
        >
          Back to home
        </Link>
      </div>
    </div>
  );
}
