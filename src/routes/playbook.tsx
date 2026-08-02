import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import logoAsset from "../assets/scg-logo.png.asset.json";
const logo = logoAsset.url;

export const Route = createFileRoute("/playbook")({
  component: PlaybookPage,
  head: () => ({
    meta: [
      { title: "Free Session Sweep Playbook | Sweep Capital Group" },
      {
        name: "description",
        content:
          "Get the free Session Sweep Playbook: the 5-15 Gap and Power of 3 framework for futures traders, written out in full. Sent to your inbox in under a minute.",
      },
      { property: "og:title", content: "Free Session Sweep Playbook | Sweep Capital Group" },
      {
        property: "og:description",
        content:
          "The exact framework we trade — Session Sweep, the 5-15 Gap, and Power of 3. Free, no call required.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: [{ rel: "canonical", href: "https://sweepcapitalgroup.com/playbook" }],
  }),
});

/** Attribution captured from the current URL so the agent can score channels. */
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
    referrer: document.referrer || undefined,
    landing_page: window.location.href.slice(0, 2048),
  };
}

const PARTS = [
  {
    n: "01",
    title: "Session Sweep",
    body: "Price runs the prior session's high or low to take liquidity, then rejects. That sweep is the only valid reason to be interested. No sweep, no trade.",
  },
  {
    n: "02",
    title: "The 5–15 Gap",
    body: "After the sweep, drop to the 5m and 15m. You want the inefficiency left behind by the displacement leg. Entry is the retrace into that gap — never the breakout.",
  },
  {
    n: "03",
    title: "Power of 3",
    body: "Accumulation → Manipulation → Distribution. The sweep is the manipulation. You trade the distribution leg only, so the stop sits above the wick and the target sits at opposing session liquidity.",
  },
];

function PlaybookPage() {
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = z.string().trim().email().max(255).safeParse(email);
    if (!parsed.success) {
      toast.error("Enter a valid email");
      return;
    }
    setSending(true);
    try {
      const res = await fetch("/api/public/lead-submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: parsed.data.split("@")[0]?.slice(0, 100) || "Trader",
          email: parsed.data,
          tier: "Free Playbook",
          source: "playbook-landing",
          ...utmPayload(),
        }),
      });
      const json = await res.json();
      if (!res.ok || !json?.success) throw new Error();
      setDone(true);
      toast.success("Sent. Check your inbox for the playbook.");
    } catch {
      toast.error("Something went wrong. Try again.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground font-sans selection:bg-accent selection:text-background">
      <nav className="flex items-center justify-between px-6 md:px-10 py-5 border-b border-border">
        <Link to="/" className="flex items-center gap-3">
          <img
            src={logo}
            alt="Sweep Capital Group logo"
            width={32}
            height={32}
            className="h-8 w-8 object-contain"
          />
          <span className="font-extrabold tracking-tighter text-xl uppercase">Sweep</span>
        </Link>
        <Link
          to="/mentorship"
          className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
        >
          Mentorship
        </Link>
      </nav>

      <main className="px-6 md:px-10 py-20 max-w-3xl mx-auto space-y-16">
        <header className="space-y-6">
          <span className="font-mono text-[10px] uppercase tracking-widest text-accent">
            Free Download
          </span>
          <h1 className="text-4xl md:text-6xl font-extrabold tracking-tighter uppercase leading-[0.95]">
            The Session Sweep Playbook
          </h1>
          <p className="text-lg text-muted-foreground leading-relaxed">
            We keep it simple: a session sweep and a 5–15 gap, confirmed by Power of 3. This is that
            entire framework, written out in full — free, no call required.
          </p>

          {done ? (
            <p className="font-mono text-xs uppercase tracking-widest text-accent">
              On its way — check your inbox.
            </p>
          ) : (
            <form onSubmit={submit} className="flex flex-col sm:flex-row gap-4 pt-2">
              <input
                required
                type="email"
                value={email}
                onChange={(ev) => setEmail(ev.target.value)}
                maxLength={255}
                placeholder="you@email.com"
                aria-label="Email address for the free playbook"
                className="flex-1 bg-transparent border-b border-border py-4 focus:outline-none focus:border-accent text-lg placeholder:text-muted-foreground/40"
              />
              <button
                type="submit"
                disabled={sending}
                className="px-8 py-4 bg-foreground text-background font-extrabold uppercase tracking-[0.2em] text-xs hover:bg-accent transition-colors duration-500 disabled:opacity-50"
              >
                {sending ? "Sending…" : "Send it"}
              </button>
            </form>
          )}
        </header>

        <section className="space-y-10">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            What's inside
          </h2>
          {PARTS.map((p) => (
            <article key={p.n} className="border-l-2 border-accent/50 pl-6 space-y-2">
              <span className="font-mono text-[10px] text-accent">{p.n}</span>
              <h3 className="text-2xl font-extrabold tracking-tighter uppercase">{p.title}</h3>
              <p className="text-muted-foreground leading-relaxed">{p.body}</p>
            </article>
          ))}
        </section>

        <section className="border-t border-border pt-10 space-y-4">
          <h2 className="text-2xl font-extrabold tracking-tighter uppercase">
            Want it walked through live?
          </h2>
          <p className="text-muted-foreground leading-relaxed">
            The playbook is the whole framework. The mentorship is us applying it to your chart,
            your sessions, and your risk — one time payment, no subscription.
          </p>
          <Link
            to="/mentorship"
            className="inline-block px-8 py-4 border border-border font-extrabold uppercase tracking-[0.2em] text-xs hover:border-accent hover:text-accent transition-colors duration-500"
          >
            See the tiers
          </Link>
        </section>

        <p className="text-xs text-muted-foreground/60 leading-relaxed">
          Educational content only. Trading involves substantial risk of loss and is not suitable
          for everyone.
        </p>
      </main>
    </div>
  );
}
