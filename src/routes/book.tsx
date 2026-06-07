import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { CallScheduler, SchedulingConfirmation } from "@/components/booking";
import logo from "../assets/lnc-logo.png";

export const Route = createFileRoute("/book")({
  validateSearch: (search: Record<string, unknown>): { lead?: string; token?: string } => ({
    lead: typeof search.lead === "string" ? search.lead : undefined,
    token: typeof search.token === "string" ? search.token : undefined,
  }),
  component: BookPage,
  head: () => ({
    meta: [
      { title: "Schedule your onboarding call — Momentum Capital Group" },
      { name: "robots", content: "noindex,nofollow" },
    ],
  }),
});

function BookPage() {
  const { lead, token } = Route.useSearch();
  const [scheduledAt, setScheduledAt] = useState<Date | null>(null);
  const [rescheduling, setRescheduling] = useState(false);

  if (!lead || !token) {
    return (
      <Shell>
        <div className="space-y-4">
          <div className="font-mono text-[10px] uppercase tracking-widest text-destructive">
            Invalid link
          </div>
          <h1 className="text-3xl font-extrabold tracking-tighter uppercase">
            We couldn't find your booking.
          </h1>
          <p className="text-sm text-muted-foreground text-pretty">
            The link you used is missing or expired. Please use the link in your confirmation email,
            or submit the application again.
          </p>
          <Link
            to="/"
            className="inline-block mt-2 px-6 py-3 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors"
          >
            Back to home
          </Link>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      {scheduledAt && !rescheduling ? (
        <SchedulingConfirmation
          slot={scheduledAt}
          leadId={lead}
          bookingToken={token}
          onReschedule={() => setRescheduling(true)}
          onCancelled={() => setScheduledAt(null)}
        />
      ) : (
        <CallScheduler
          leadId={lead}
          bookingToken={token}
          mode={rescheduling ? "reschedule" : "initial"}
          currentSlot={scheduledAt}
          onScheduled={(slot) => {
            setScheduledAt(slot);
            setRescheduling(false);
          }}
          onBack={rescheduling ? () => setRescheduling(false) : undefined}
        />
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground font-sans">
      <nav className="flex items-center justify-between px-6 md:px-10 py-5 border-b border-border">
        <Link to="/" className="flex items-center gap-3">
          <img src={logo} alt="Momentum Capital Group" width={32} height={32} className="h-8 w-8 object-contain" />
          <span className="font-extrabold tracking-tighter text-xl uppercase">Momentum</span>
        </Link>
      </nav>
      <main className="max-w-2xl mx-auto px-6 md:px-10 py-16 md:py-24">{children}</main>
    </div>
  );
}
