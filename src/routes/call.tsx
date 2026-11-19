import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import logoAsset from "../assets/scg-logo.png.asset.json";
const logo = logoAsset.url;

export const Route = createFileRoute("/call")({
  head: () => ({
    meta: [
      { title: "Book a Free 15-Minute Call | Sweep Capital Group" },
      {
        name: "description",
        content:
          "Book a free 15-minute call with Mac Moore to see whether The Course or Course + Coaching fits where you are as a futures trader. Education, not advice.",
      },
      { property: "og:title", content: "Book a Free 15-Minute Call | Sweep Capital Group" },
      {
        property: "og:description",
        content: "A free 15-minute call to see which Sweep Capital Group program, if any, fits you.",
      },
    ],
    links: [{ rel: "canonical", href: "https://sweepcapitalgroup.com/call" }],
  }),
  component: CallPage,
});

const schema = z.object({
  full_name: z.string().trim().min(2, "Please enter your name").max(120),
  email: z.string().trim().email("Please enter a valid email").max(255),
  notes: z.string().trim().max(2000).optional(),
});

function utmPayload() {
  if (typeof window === "undefined") return {};
  const p = new URLSearchParams(window.location.search);
  const pick = (k: string) => p.get(k) ?? undefined;
  return {
    utm_source: pick("utm_source"),
    utm_medium: pick("utm_medium"),
    utm_campaign: pick("utm_campaign"),
    utm_term: pick("utm_term"),
    utm_content: pick("utm_content"),
    ref: pick("ref"),
    referrer: document.referrer || undefined,
    landing_page: window.location.href.slice(0, 2048),
  };
}

function CallPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = schema.safeParse({ full_name: fullName, email, notes: notes || undefined });
    if (!parsed.success) {
      toast.error(parsed.error.issues[0]?.message ?? "Check the form");
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch("/api/public/lead-submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...parsed.data,
          tier: "Free 15-min call",
          source: "call",
          ...utmPayload(),
        }),
      });
      const json = await res.json();
      if (!res.ok || !json?.success || !json?.lead_id || !json?.booking_token) throw new Error();
      window.location.href = `/book?lead=${encodeURIComponent(json.lead_id)}&token=${encodeURIComponent(json.booking_token)}`;
    } catch {
      toast.error("Something went wrong. Try again.");
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground font-sans">
      <nav className="flex items-center justify-between px-6 md:px-10 py-5 border-b border-border">
        <Link to="/" className="flex items-center gap-3">
          <img src={logo} alt="Sweep Capital Group logo" width={32} height={32} className="h-8 w-8 object-contain" />
          <span className="font-extrabold tracking-tighter text-xl uppercase">Sweep</span>
        </Link>
        <Link to="/mentorship" className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground hover:text-foreground">
          See the Programs
        </Link>
      </nav>
      <main className="max-w-xl mx-auto px-6 md:px-10 py-16 md:py-24 flex flex-col gap-8">
        <div className="flex flex-col gap-4">
          <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">Free call</span>
          <h1 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase leading-[0.95]">
            Book a free 15-minute call.
          </h1>
          <p className="text-muted-foreground text-pretty">
            Tell us who you are, then pick a time on the next screen. We'll talk about where you are with futures and
            whether The Course or Course + Coaching makes sense. No results are promised, and there's no obligation.
          </p>
        </div>
        <form onSubmit={submit} className="flex flex-col gap-5">
          <label className="flex flex-col gap-2">
            <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Full name</span>
            <input
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
              autoComplete="name"
              className="bg-transparent border-b border-border focus:border-accent outline-none py-2 text-foreground"
            />
          </label>
          <label className="flex flex-col gap-2">
            <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className="bg-transparent border-b border-border focus:border-accent outline-none py-2 text-foreground"
            />
          </label>
          <label className="flex flex-col gap-2">
            <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              What do you want to cover? (optional)
            </span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              className="bg-transparent border border-border focus:border-accent outline-none p-2 text-foreground"
            />
          </label>
          <button
            type="submit"
            disabled={submitting}
            className="mt-2 px-6 py-4 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors disabled:opacity-50"
          >
            {submitting ? "One moment…" : "Pick a time"}
          </button>
        </form>
        <p className="text-xs text-muted-foreground text-pretty">
          Risk disclaimer: Trading futures involves substantial risk of loss and is not suitable for every investor.
          This is education, not financial advice.
        </p>
      </main>
    </div>
  );
}
