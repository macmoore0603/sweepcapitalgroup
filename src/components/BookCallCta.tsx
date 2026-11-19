import { Link } from "@tanstack/react-router";

/** "Not sure which program fits?" prompt linking to the free 15-min call page. */
export function BookCallCta({ className = "" }: { className?: string }) {
  return (
    <div
      className={`border border-border p-5 md:p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 ${className}`}
    >
      <div className="flex flex-col gap-1">
        <span className="font-mono text-[10px] uppercase tracking-widest text-accent">Not sure which fits?</span>
        <p className="text-sm text-foreground text-pretty">
          Book a free 15-minute call with Mac. No pressure. We just figure out which program, if any, fits
          where you are.
        </p>
      </div>
      <Link
        to="/call"
        className="shrink-0 text-center px-5 py-3 border border-accent text-accent font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent hover:text-background transition-colors"
      >
        Book a free 15-min call
      </Link>
    </div>
  );
}
