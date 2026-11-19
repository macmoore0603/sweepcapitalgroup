import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { Menu } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger, SheetClose } from "@/components/ui/sheet";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

import methodologyImg from "../assets/methodology.jpg";
import heroBg from "../assets/hero-bg.jpg";
import logoAsset from "../assets/scg-logo.png.asset.json";
const logo = logoAsset.url;
import macMoore from "../assets/mac-moore.png";
import { StripeEmbeddedCheckout } from "@/components/StripeEmbeddedCheckout";
import { PaymentTestModeBanner } from "@/components/PaymentTestModeBanner";
import { ExitIntentPlaybook } from "@/components/ExitIntentPlaybook";


const FAQS: { q: string; a: string }[] = [
  {
    q: "What exactly do I get with The Course ($1,000)?",
    a: "Lifetime access to the full Sweep Capital Group course: Session Sweep, the 5–15 Gap, and Power of 3 — taught step by step with live chart breakdowns and the exact rules we trade.",
  },
  {
    q: "Is this a one-time payment or a subscription?",
    a: "Both programs are a single one-time payment. No monthly fees, no recurring billing.",
  },
  {
    q: "Do I need experience to start?",
    a: "No. The curriculum starts from market structure basics and builds to the full Session Sweep model, so complete beginners and experienced traders both have a clear path.",
  },
  {
    q: "How much capital do I need?",
    a: "You can learn and practice on a demo or a small funded evaluation account. Most mentees start with a prop firm challenge rather than large personal capital.",
  },
  {
    q: "Are results guaranteed?",
    a: "No. Trading futures involves substantial risk of loss and past performance does not guarantee future results. We teach a process and a risk framework, not outcomes.",
  },
  {
    q: "How fast do I get access after paying?",
    a: "Immediately. Checkout sends a confirmation email with your access details and a link to book your onboarding call.",
  },
];

export const Route = createFileRoute("/")({
  component: Index,
  head: () => ({
    meta: [
      { title: "Sweep Capital Group — Futures Trading Mentorship in Atlanta" },
      {
        name: "description",
        content:
          "Learn the Session Sweep, 5–15 Gap and Power of 3 models. One-time payment futures education from Sweep Capital Group: The Course ($1,000) or Course + Coaching ($1,500).",
      },
      { property: "og:title", content: "Sweep Capital Group — Futures Trading Mentorship" },
      {
        property: "og:description",
        content:
          "Session Sweep, the 5–15 Gap and Power of 3 — taught step by step. One-time payment, no subscriptions.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    scripts: [
      {
        type: "application/ld+json",
        children: JSON.stringify({
          "@context": "https://schema.org",
          "@type": "FAQPage",
          mainEntity: FAQS.map((f) => ({
            "@type": "Question",
            name: f.q,
            acceptedAnswer: { "@type": "Answer", text: f.a },
          })),
        }),
      },
    ],
  }),
});

function RiskNote({ className = "" }: { className?: string }) {
  return (
    <p className={`text-xs text-muted-foreground text-pretty max-w-2xl ${className}`}>
      Risk disclaimer: Trading futures involves substantial risk of loss and is not suitable for every investor.
      This is education, not financial advice. Past performance does not guarantee future results.
    </p>
  );
}

function FAQSection() {
  return (
    <section id="faq" className="px-6 md:px-10 py-24 md:py-32 border-t border-border">
      <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-[1fr_2fr] gap-12 md:gap-20">
        <div className="flex flex-col gap-4">
          <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">FAQ</span>
          <h2 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase leading-[0.95]">
            Straight{" "}
            <span className="italic font-semibold text-accent" style={{ fontFamily: "var(--font-serif)" }}>
              Answers.
            </span>
          </h2>
        </div>
        <dl className="flex flex-col divide-y divide-border border-t border-border">
          {FAQS.map((f) => (
            <div key={f.q} className="py-6 flex flex-col gap-2">
              <dt className="font-mono text-[11px] uppercase tracking-widest text-foreground">{f.q}</dt>
              <dd className="text-sm text-muted-foreground leading-relaxed">{f.a}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}


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
    ref: pick("ref"),
    referrer: document.referrer || undefined,
    landing_page: window.location.href.slice(0, 2048),
  };
}

function PlaybookOptIn() {
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
          full_name: parsed.data.split("@")[0].slice(0, 100) || "Trader",
          email: parsed.data,
          tier: "Free Playbook",
          source: "playbook",
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
    <section className="px-6 md:px-10 py-20 border-t border-border bg-card/30">
      <div className="max-w-3xl mx-auto text-center space-y-6">
        <span className="font-mono text-[10px] uppercase tracking-widest text-accent">Free Download</span>
        <h2 className="text-3xl md:text-4xl font-extrabold tracking-tighter uppercase">
          The Session Sweep Playbook
        </h2>
        <p className="text-muted-foreground leading-relaxed">
          The exact framework we trade — Session Sweep, the 5–15 Gap, and Power of 3 — written out in
          full. No cost, no call required. Sent to your inbox in under a minute.
        </p>
        {done ? (
          <p className="font-mono text-xs uppercase tracking-widest text-accent">
            On its way — check your inbox.
          </p>
        ) : (
          <form onSubmit={submit} className="flex flex-col sm:flex-row gap-4 max-w-xl mx-auto pt-2">
            <input
              required
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
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
        <RiskNote />
      </div>
    </section>
  );
}


function Index() {
  const [checkoutPriceId, setCheckoutPriceId] = useState<string | null>(null);
  const [checkoutTitle, setCheckoutTitle] = useState<string>("");
  return (
    <div className="min-h-screen bg-background text-foreground font-sans selection:bg-accent selection:text-background">
      {/* Navigation */}
      <nav className="sticky top-0 z-50 flex items-center justify-between px-6 md:px-10 py-5 bg-background/80 backdrop-blur-md border-b border-border">
        <div className="flex items-center gap-3">
          <img src={logo} alt="Sweep Capital Group logo" width={32} height={32} className="h-8 w-8 object-contain" />
          <span className="font-extrabold tracking-tighter text-xl uppercase">Sweep</span>
          <span className="hidden sm:inline font-mono text-[10px] text-accent border border-accent/40 px-1.5 py-0.5">
            CAPITAL GROUP
          </span>
        </div>
        <div className="hidden md:flex items-center gap-8 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          <a href="#methodology" className="hover:text-foreground transition-colors">Methodology</a>
          <a href="#tiers" className="hover:text-foreground transition-colors">Tiers</a>
          <Link to="/about" className="hover:text-foreground transition-colors">About</Link>
          <Link to="/leadership" className="hover:text-foreground transition-colors">Leadership</Link>
          <Link to="/learn" className="hover:text-foreground transition-colors">Learn</Link>
          <Link to="/mentorship" className="hover:text-foreground transition-colors">Mentorship</Link>
          <a href="#contact" className="hover:text-foreground transition-colors">Contact</a>
        </div>
        <div className="flex items-center gap-3">
          <Link to="/mentorship" className="hidden sm:inline-block px-5 py-2.5 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors">
            See Programs
          </Link>
          <Sheet>
            <SheetTrigger
              aria-label="Open menu"
              className="md:hidden inline-flex items-center justify-center w-10 h-10 border border-border hover:bg-white/5 transition-colors"
            >
              <Menu className="w-5 h-5" />
            </SheetTrigger>
            <SheetContent side="right" className="bg-background border-border w-[280px] sm:w-[340px]">
              <SheetHeader>
                <SheetTitle className="font-extrabold tracking-tighter text-xl uppercase text-left">
                  Sweep
                </SheetTitle>
              </SheetHeader>
              <nav className="flex flex-col mt-8 font-mono text-xs uppercase tracking-widest">
                {[
                  { label: "Methodology", href: "#methodology", type: "hash" as const },
                  { label: "Tiers", href: "#tiers", type: "hash" as const },
                  { label: "Contact", href: "#contact", type: "hash" as const },
                ].map((item) => (
                  <SheetClose asChild key={item.label}>
                    <a
                      href={item.href}
                      className="py-4 border-b border-border text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {item.label}
                    </a>
                  </SheetClose>
                ))}
                <SheetClose asChild>
                  <Link
                    to="/about"
                    className="py-4 border-b border-border text-muted-foreground hover:text-foreground transition-colors"
                  >
                    About
                  </Link>
                </SheetClose>
                <SheetClose asChild>
                  <Link
                    to="/leadership"
                    className="py-4 border-b border-border text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Leadership
                  </Link>
                </SheetClose>
                <SheetClose asChild>
                  <Link
                    to="/learn"
                    className="py-4 border-b border-border text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Free Guides
                  </Link>
                </SheetClose>
                <SheetClose asChild>
                  <Link
                    to="/mentorship"
                    className="mt-8 px-5 py-4 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest text-center hover:bg-accent transition-colors"
                  >
                    See Programs
                  </Link>
                </SheetClose>
              </nav>
            </SheetContent>
          </Sheet>
        </div>
      </nav>

      {/* Hero */}
      <header className="relative px-6 md:px-10 pt-24 md:pt-32 pb-32 md:pb-40 overflow-hidden">
        <div
          aria-hidden
          className="absolute inset-0 -z-10 opacity-25 bg-cover bg-center grayscale"
          style={{ backgroundImage: `url(${heroBg})` }}
        />
        <div aria-hidden className="absolute inset-0 -z-10 bg-gradient-to-b from-background/60 via-background/80 to-background" />
        <div className="max-w-7xl mx-auto">
          <div className="flex flex-col gap-6 animate-reveal">
            <span className="font-mono text-accent text-[12px] uppercase tracking-[0.3em]">
              The Private Office of Trading
            </span>
            <h1 className="text-5xl sm:text-7xl md:text-[120px] leading-[0.85] font-extrabold tracking-tighter text-balance">
              SUCCESS IS{" "}
              <span className="italic font-semibold text-accent" style={{ fontFamily: "var(--font-serif)" }}>
                the only
              </span>{" "}
              EDGE.
            </h1>
            <p className="max-w-[54ch] text-base md:text-lg text-muted-foreground text-pretty mt-4">
              Strategies. Risk management. A repeatable process. Build skill. Review every session — through three
              repeatable institutional setups: the Session Sweep, the 5–15 Gap, and the Power of 3.
            </p>
            <div className="flex flex-wrap gap-4 mt-8">
              <Link to="/mentorship" className="px-7 md:px-8 py-4 bg-foreground text-background font-extrabold text-sm uppercase tracking-widest hover:bg-accent transition-colors">
                See the Programs
              </Link>
              <a href="#methodology" className="px-7 md:px-8 py-4 border border-border font-extrabold text-sm uppercase tracking-widest hover:bg-white/5 transition-colors">
                View Methodology
              </a>
            </div>
          </div>
        </div>
      </header>

      {/* How it works */}
      <section id="process" className="px-6 md:px-10 py-24 md:py-28 border-t border-border">
        <div className="max-w-7xl mx-auto">
          <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">Process</span>
          <h2 className="mt-4 text-4xl md:text-6xl font-extrabold tracking-tighter">
            THREE STEPS TO A WRITTEN TRADING PROCESS.
          </h2>
          <div className="grid md:grid-cols-3 gap-px bg-border mt-14 border border-border">
            {[
              {
                n: "01",
                title: "Choose a Program",
                body: "Pick The Course or Course + Coaching on the mentorship page. One-time payment, secure checkout.",
              },
              {
                n: "02",
                title: "Onboarding Call",
                body: "A 15-minute call to map the Session Sweep, 5–15 Gap, and Power of 3 onto the sessions and pairs you actually trade.",
              },
              {
                n: "03",
                title: "Trade the Framework",
                body: "One sweep, one gap, one direction per session — with trade reviews and risk limits. Coaching members get 1:1 walkthroughs during the coaching window we agree on.",
              },
            ].map((step) => (
              <div key={step.n} className="bg-background p-8 md:p-10 flex flex-col gap-4">
                <span className="font-mono text-[11px] text-accent tracking-widest">{step.n}</span>
                <h3 className="text-2xl font-extrabold tracking-tight uppercase">{step.title}</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">{step.body}</p>
              </div>
            ))}
          </div>
          <div className="mt-12">
            <Link
              to="/mentorship"
              className="inline-block px-8 py-4 bg-foreground text-background font-extrabold text-sm uppercase tracking-widest hover:bg-accent transition-colors"
            >
              See the Programs
            </Link>
          </div>
        </div>
      </section>

      {/* Tiers */}
      <section id="tiers" className="px-6 md:px-10 py-24 md:py-32">
        <div className="max-w-7xl mx-auto">
          <div className="flex flex-col md:flex-row md:justify-between md:items-end gap-6 mb-16 md:mb-20">
            <h2 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase">
              Program{" "}
              <span className="italic font-semibold text-accent capitalize" style={{ fontFamily: "var(--font-serif)" }}>
                Tiers
              </span>
            </h2>
            <p className="max-w-xs font-mono text-[11px] text-muted-foreground uppercase leading-relaxed">
              One-time payment. No subscriptions.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-border max-w-5xl mx-auto">
            {[
              {
                num: "01",
                tag: "Self-Paced",
                title: "The Course",
                price: "$1,000",
                priceId: "mentorship_course_onetime",
                desc: "The complete self-paced curriculum: Session Sweep, the 5–15 Gap, Power of 3, and the risk rules behind them.",
                features: ["Full video curriculum", "Lifetime updates", "Private student community"],
                cta: "Buy The Course",
                featured: false,
                available: true,
              },
              {
                num: "02",
                tag: "Most Popular",
                title: "Course + Coaching",
                price: "$1,500",
                priceId: "mentorship_course_coaching_onetime",
                desc: "Everything in The Course, plus 1:1 walkthroughs and trade reviews during the coaching window we agree on.",
                features: ["Everything in The Course", "1:1 step-by-step walkthroughs", "Trade reviews", "Direct messaging during your coaching window"],
                cta: "Buy Course + Coaching",
                featured: true,
                available: true,
              },
              {
                num: "03",
                tag: "Not Available",
                title: "Managed Trading",
                price: "$1,000",
                priceId: "mentorship_managed_onetime",
                desc: "Not currently available for purchase.",
                features: ["Not available for purchase"],
                cta: "Not available",
                featured: false,
                available: false,
              },
              {
                num: "04",
                tag: "Not Available",
                title: "All-Inclusive",
                price: "$2,000",
                priceId: "mentorship_all_inclusive_onetime",
                desc: "Not currently available for purchase.",
                features: ["Not available for purchase"],
                cta: "Not available",
                featured: false,
                available: false,
              },
            ].filter((tier) => tier.available).map((tier) => (
              <article
                key={tier.num}
                className={`bg-background p-10 md:p-12 flex flex-col gap-8 ${tier.featured ? "ring-1 ring-accent/40 relative" : ""}`}
              >
                <div className="flex justify-between items-start">
                  <span className="font-mono text-accent text-xs">{tier.num}</span>
                  <span
                    className={`px-2 py-1 text-[9px] uppercase tracking-widest font-mono ${
                      tier.featured ? "bg-accent text-background font-bold" : "border border-border"
                    }`}
                  >
                    {tier.tag}
                  </span>
                </div>
                <div className="flex flex-col gap-1">
                  <h3 className="text-2xl font-extrabold uppercase tracking-tight">{tier.title}</h3>
                  <span className="text-3xl font-extrabold tracking-tighter text-accent">{tier.price}</span>
                  <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">One-time payment</span>
                </div>
                <p className="text-muted-foreground text-sm leading-relaxed">{tier.desc}</p>
                <ul className="mt-auto flex flex-col gap-4 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
                  {tier.features.map((f) => (
                    <li key={f} className="flex items-center gap-2">
                      <span className="size-1 bg-accent rounded-full" /> {f}
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  disabled={!tier.available}
                  onClick={() => {
                    if (!tier.available) return;
                    setCheckoutTitle(tier.title);
                    setCheckoutPriceId(tier.priceId);
                  }}
                  className={`w-full py-4 text-center text-[11px] font-extrabold uppercase tracking-widest transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                    tier.featured ? "bg-foreground text-background hover:bg-accent" : "border border-border hover:bg-white/5"
                  }`}
                >
                  {tier.cta}
                </button>
              </article>
            ))}
          </div>
          <RiskNote className="mt-6" />
        </div>
      </section>

      <Dialog open={!!checkoutPriceId} onOpenChange={(o) => !o && setCheckoutPriceId(null)}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto p-0">
          <DialogHeader className="px-6 pt-6">
            <DialogTitle className="text-xl font-extrabold uppercase tracking-tight">
              Checkout — {checkoutTitle}
            </DialogTitle>
          </DialogHeader>
          <PaymentTestModeBanner />
          <div className="p-2">
            {checkoutPriceId && <StripeEmbeddedCheckout priceId={checkoutPriceId} referralCode={utmPayload().ref} />}
          </div>
        </DialogContent>
      </Dialog>


      {/* Methodology */}
      <section id="methodology" className="px-6 md:px-10 py-24 md:py-32 bg-white/[0.03]">
        <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-16 md:gap-24 items-center">
          <div className="order-2 lg:order-1">
            <img
              src={methodologyImg}
              alt="Macro view of precision mechanical movement"
              width={800}
              height={1000}
              loading="lazy"
              className="w-full aspect-[4/5] object-cover bg-black ring-1 ring-white/10 grayscale"
            />
          </div>
          <div className="order-1 lg:order-2 flex flex-col gap-10">
            <h2 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase leading-[0.9]">
              PRECISION <br />
              <span className="italic font-semibold text-accent capitalize" style={{ fontFamily: "var(--font-serif)" }}>
                Methodology
              </span>
            </h2>
            <div className="space-y-10 md:space-y-12">
              {[
                {
                  n: "01",
                  title: "Session Sweep",
                  desc: "We map prior session highs and lows, wait for liquidity to be taken, and enter on the reversal — trading where institutions are forced to fill, not where retail expects price to go.",
                },
                {
                  n: "02",
                  title: "5–15 Gap",
                  desc: "A precision entry model on the 5- and 15-minute timeframes. We isolate the displacement gap left behind by aggressive orderflow and execute on the retest with defined risk.",
                },
                {
                  n: "03",
                  title: "Power of 3",
                  desc: "Accumulation, manipulation, distribution. Every session follows the same three-phase footprint — once you can read it, entries become mechanical and exits become obvious.",
                },
              ].map((m) => (
                <div key={m.n} className="flex gap-6">
                  <span className="font-mono text-accent text-sm shrink-0">/ {m.n}</span>
                  <div className="space-y-2">
                    <h3 className="text-lg font-extrabold uppercase tracking-tight">{m.title}</h3>
                    <p className="text-muted-foreground text-sm leading-relaxed">{m.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Founder */}
      <section id="founder" className="px-6 md:px-10 py-24 md:py-32 border-t border-border bg-white/[0.02]">
        <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-[1fr_2fr] gap-12 md:gap-20 items-start">
          <div className="flex flex-col gap-4">
            <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">The Founder</span>
            <div className="aspect-[4/5] w-full bg-gradient-to-br from-accent/30 via-muted to-background border border-border overflow-hidden">
              <img
                src={macMoore}
                alt="Mac Moore — Founder of Sweep Capital Group"
                width={800}
                height={1000}
                loading="lazy"
                className="w-full h-full object-cover"
              />
            </div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              Johns Creek, Georgia
            </div>
          </div>
          <div className="flex flex-col gap-6">
            <h2 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase">
              Mac Moore,{" "}
              <span className="italic font-semibold text-accent" style={{ fontFamily: "var(--font-serif)" }}>
                Founder, Owner &amp; CEO
              </span>
            </h2>
            <p className="text-muted-foreground text-base md:text-lg leading-relaxed text-pretty">
              Three years behind the screens of institutional desks taught Mac one lesson worth repeating:
              the market does not reward intelligence — it rewards process. He founded Sweep Capital Group
              in Johns Creek to compress that lesson into a deliberate, repeatable framework for the
              traders he chooses to mentor.
            </p>
            <p className="text-muted-foreground text-base md:text-lg leading-relaxed text-pretty">
              His approach is unromantic: edge is built through statistical rigor, position sizing, and an
              unwavering process. Coaching members are briefed personally and held
              accountable to the same standards Mac runs his own book against.
            </p>
            <div className="grid grid-cols-3 gap-6 pt-4 border-t border-border mt-2">
              {[
                { k: "3 YRS", v: "Trading Desks" },
                { k: "3", v: "Core Setups" },
                { k: "1x", v: "One-Time Payment" },
              ].map((s) => (
                <div key={s.k} className="flex flex-col gap-1">
                  <span className="font-extrabold text-xl md:text-2xl tracking-tight text-accent">{s.k}</span>
                  <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">{s.v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Start */}
      <section id="start" className="px-6 md:px-10 py-24 md:py-32 border-t border-border">
        <div className="max-w-3xl mx-auto flex flex-col items-center text-center gap-8">
          <h2 className="text-5xl md:text-6xl font-extrabold tracking-tighter uppercase">
            Ready to{" "}
            <span className="italic font-semibold text-accent capitalize" style={{ fontFamily: "var(--font-serif)" }}>
              start?
            </span>
          </h2>
          <p className="text-muted-foreground text-base md:text-lg text-pretty">
            Choose The Course or Course + Coaching on the mentorship page. One-time payment, secure checkout,
            and next steps by email right after.
          </p>
          <Link
            to="/mentorship"
            className="px-8 py-4 bg-foreground text-background font-extrabold text-sm uppercase tracking-widest hover:bg-accent transition-colors"
          >
            See the Programs
          </Link>
          <RiskNote />
        </div>
      </section>

      <FAQSection />

      <PlaybookOptIn />

      <ExitIntentPlaybook />



      {/* Contact */}
      <section id="contact" className="px-6 md:px-10 py-20 md:py-28 border-t border-border bg-white/[0.02]">
        <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-[1fr_2fr] gap-12 md:gap-20">
          <div className="flex flex-col gap-4">
            <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">Contact</span>
            <h2 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase leading-[0.95]">
              Johns Creek,{" "}
              <span className="italic font-semibold text-accent" style={{ fontFamily: "var(--font-serif)" }}>
                Georgia.
              </span>
            </h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-10">
            <div className="flex flex-col gap-2">
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Headquarters</span>
              <span className="text-foreground font-semibold">Johns Creek, Georgia</span>
            </div>
            <div className="flex flex-col gap-2">
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Mailing Address</span>
              <address className="not-italic text-foreground leading-relaxed">
                Sweep Capital Group<br />
                11555 Medlock Bridge Rd<br />
                Johns Creek, GA 30097
              </address>
            </div>
            <div className="flex flex-col gap-2">
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Direct</span>
              <a href="tel:+14782978388" className="text-foreground font-semibold hover:text-accent transition-colors">
                (478) 297-8388
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="px-6 md:px-10 py-10 pb-24 md:pb-10 border-t border-border">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6 font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
          <div className="flex items-center gap-3">
            <img src={logo} alt="Sweep Capital Group logo" width={24} height={24} className="h-6 w-6 object-contain opacity-60" />
            <span>© 2026 Sweep Capital Group — Johns Creek, GA</span>
          </div>
          <div className="flex flex-wrap justify-center gap-6">
            <Link to="/playbook" className="hover:text-foreground transition-colors">Free Playbook</Link>
            <Link to="/learn" className="hover:text-foreground transition-colors">Learn</Link>
            <Link to="/refer" className="hover:text-foreground transition-colors">Refer &amp; Earn</Link>
            <Link to="/terms" className="hover:text-foreground transition-colors">Terms</Link>
            <Link to="/privacy" className="hover:text-foreground transition-colors">Privacy</Link>
          </div>
        </div>
      </footer>

      {/* Mobile sticky CTA */}
      <div className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t border-border bg-background/95 backdrop-blur px-4 py-3 flex items-center gap-3">
        <a
          href="#tiers"
          className="flex-1 text-center bg-accent text-accent-foreground font-mono text-[11px] uppercase tracking-widest py-3 rounded-sm font-bold"
        >
          View Tiers
        </a>
        <Link
          to="/mentorship"
          className="flex-1 text-center border border-border text-foreground font-mono text-[11px] uppercase tracking-widest py-3 rounded-sm"
        >
          Programs
        </Link>
      </div>
    </div>
  );
}
