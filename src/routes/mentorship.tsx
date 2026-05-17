import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { z } from "zod";
import { toast } from "sonner";

import logo from "../assets/lnc-logo.png";
import { StripeEmbeddedCheckout } from "@/components/StripeEmbeddedCheckout";
import { PaymentTestModeBanner } from "@/components/PaymentTestModeBanner";

export const Route = createFileRoute("/mentorship")({
  head: () => ({
    meta: [
      { title: "Mentorship — Lexus Nexus Capital Group" },
      {
        name: "description",
        content:
          "Four one-time mentorship options from Lexus Nexus Capital Group. Course, full step-by-step coaching, managed trading, or the complete package — the most affordable on the market.",
      },
      { property: "og:title", content: "Mentorship — Lexus Nexus Capital Group" },
      {
        property: "og:description",
        content:
          "One-time pricing. Four ways in. Course, coaching, managed trading, or all-inclusive.",
      },
    ],
  }),
  component: MentorshipPage,
});

type Tier = {
  id: string;
  name: string;
  price: string;
  priceId: string;
  tagline: string;
  features: string[];
  highlight?: boolean;
  badge?: string;
};

const TIERS: Tier[] = [
  {
    id: "course",
    name: "The Course",
    price: "$500",
    priceId: "mentorship_course_onetime",
    tagline: "Self-paced curriculum. One-time payment.",
    features: [
      "Full mentorship course access",
      "Lifetime updates",
      "Private student community",
      "One-time payment — no subscriptions",
    ],
  },
  {
    id: "course-coaching",
    name: "Course + Coaching",
    price: "$1,500",
    priceId: "mentorship_course_coaching_onetime",
    tagline: "Course plus step-by-step personal guidance.",
    features: [
      "Everything in The Course",
      "Step-by-step 1:1 walkthroughs",
      "Direct messaging access",
      "Setup reviews until you're profitable",
    ],
    highlight: true,
    badge: "Most Popular",
  },
  {
    id: "managed",
    name: "Managed Trading",
    price: "$500",
    priceId: "mentorship_managed_onetime",
    tagline: "I trade for you. Guaranteed $2k min in 3–4 weeks.",
    features: [
      "Hands-off — I trade your account",
      "Guaranteed $2,000 minimum return",
      "3–4 week target window",
      "Weekly performance updates",
    ],
    badge: "Guaranteed",
  },
  {
    id: "all-in",
    name: "All-Inclusive",
    price: "$2,000",
    priceId: "mentorship_all_inclusive_onetime",
    tagline: "Course + coaching + managed trading. Everything.",
    features: [
      "Full course access",
      "Step-by-step personal coaching",
      "Managed trading ($2k min guarantee)",
      "Highest priority direct access",
    ],
    badge: "Best Value",
  },
];

type FaqItem = { q: string; a: string };
type FaqGroup = { title: string; kicker: string; items: FaqItem[] };

const FAQ_GROUPS: FaqGroup[] = [
  {
    title: "Eligibility",
    kicker: "Who this is for",
    items: [
      {
        q: "Do I need prior trading experience?",
        a: "No. The Course assumes zero experience and builds from the ground up. Course + Coaching is ideal whether you're starting fresh or already trading and want a structured edge.",
      },
      {
        q: "Is there a minimum account size?",
        a: "For self-trading tiers, $500–$2,000 in starting capital is the practical floor. For Managed Trading, the minimum funded account is $2,500.",
      },
      {
        q: "Country requirements?",
        a: "Open to US residents 18+. International students can enroll in The Course; managed trading and direct coaching are US-only at this time.",
      },
      {
        q: "What broker do I need?",
        a: "We'll recommend a vetted broker on your kickoff call. If you already have one, we'll work with it where possible.",
      },
    ],
  },
  {
    title: "Refunds & Guarantees",
    kicker: "Where we stand",
    items: [
      {
        q: "Is there a refund window?",
        a: "The Course and Course + Coaching include a 7-day satisfaction window from the date of first login — full refund, no questions, if the material isn't for you.",
      },
      {
        q: "What does the Managed Trading guarantee cover?",
        a: "If your account does not reach a $2,000 minimum net profit within the 3–4 week target window, we continue trading at no additional cost until it does, or we refund the $500 setup fee. Full terms in your written agreement.",
      },
      {
        q: "Are returns guaranteed for self-trading tiers?",
        a: "No. Self-trading outcomes depend on your execution. We guarantee curriculum quality and coaching access, not market returns.",
      },
      {
        q: "Can I upgrade after I start?",
        a: "Yes. Any tier can be upgraded within 30 days and we credit 100% of what you've already paid toward the higher tier.",
      },
    ],
  },
];

const TIER_EXPECTATIONS: { id: string; name: string; timeline: string; steps: string[] }[] = [
  {
    id: "course",
    name: "The Course",
    timeline: "Self-paced · ~4 weeks",
    steps: [
      "Instant access to the full curriculum and student community",
      "Weekly study path with setups, journaling, and review templates",
      "Lifetime updates and new module drops",
      "Optional Q&A office hours inside the community",
    ],
  },
  {
    id: "course-coaching",
    name: "Course + Coaching",
    timeline: "6–8 weeks to first profit",
    steps: [
      "Kickoff call within 24 hours to map your starting point",
      "1:1 walkthroughs of every core setup until executed cleanly",
      "Direct messaging access for live trade reviews",
      "Coaching continues until you hit your first profitable week",
    ],
  },
  {
    id: "managed",
    name: "Managed Trading",
    timeline: "3–4 week target window",
    steps: [
      "Sign agreement and connect your funded account",
      "I trade your account hands-off with weekly performance reports",
      "$2,000 minimum target — continue at no cost or refund if missed",
      "Quarterly review on whether to continue managed or transition you to self-trading",
    ],
  },
  {
    id: "all-in",
    name: "All-Inclusive",
    timeline: "Full stack from day one",
    steps: [
      "Everything in Course + Coaching, with highest-priority direct access",
      "Managed Trading runs in parallel while you learn",
      "Side-by-side reviews of my trades vs. yours",
      "Continued support after the managed window closes",
    ],
  },
];

export default function MentorshipPage() {
  return (
    <div className="min-h-screen bg-background text-foreground font-sans">
      {/* Nav */}
      <nav className="sticky top-0 z-50 flex items-center justify-between px-6 md:px-10 py-5 bg-background/80 backdrop-blur-md border-b border-border">
        <Link to="/" className="flex items-center gap-3">
          <img src={logo} alt="Lexus Nexus Capital Group logo" width={32} height={32} className="h-8 w-8 object-contain" />
          <span className="font-extrabold tracking-tighter text-xl uppercase">Lexus Nexus</span>
          <span className="hidden sm:inline font-mono text-[10px] text-accent border border-accent/40 px-1.5 py-0.5">
            CAPITAL GROUP
          </span>
        </Link>
        <div className="hidden md:flex items-center gap-8 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          <Link to="/" className="hover:text-foreground transition-colors">Home</Link>
          <Link to="/about" className="hover:text-foreground transition-colors">About</Link>
          <Link to="/mentorship" className="text-foreground">Mentorship</Link>
          <a href="#faq" className="hover:text-foreground transition-colors">FAQ</a>
        </div>
        <a href="#lead" className="px-5 py-2.5 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors">
          Get Started
        </a>
      </nav>

      {/* Hero */}
      <header className="px-6 md:px-10 pt-20 md:pt-28 pb-12 md:pb-16 border-b border-border">
        <div className="max-w-5xl mx-auto flex flex-col gap-6">
          <span className="font-mono text-accent text-[12px] uppercase tracking-[0.3em]">Mentorship</span>
          <h1 className="text-5xl md:text-7xl font-extrabold tracking-tighter uppercase leading-[0.9]">
            Four ways in.{" "}
            <span className="italic font-semibold text-accent" style={{ fontFamily: "var(--font-serif)" }}>
              One-time payment.
            </span>
          </h1>
          <p className="max-w-[60ch] text-base md:text-lg text-muted-foreground text-pretty">
            No subscriptions. No upsells. Pick the path that fits where you are — the course, full
            coaching, managed trading, or the complete package. The most affordable mentorship on
            the market, by a wide margin.
          </p>
        </div>
      </header>

      {/* Tiers */}
      <section className="px-6 md:px-10 py-20 md:py-28">
        <div className="max-w-7xl mx-auto grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {TIERS.map((tier) => (
            <div
              key={tier.id}
              className={`relative flex flex-col gap-6 p-8 border ${tier.highlight ? "border-accent bg-white/[0.03]" : "border-border"} `}
            >
              {tier.badge && (
                <span className="absolute -top-3 left-6 font-mono text-[10px] uppercase tracking-widest bg-accent text-background px-2 py-1">
                  {tier.badge}
                </span>
              )}
              <div className="flex flex-col gap-2">
                <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">{tier.name}</span>
                <span className="text-5xl font-extrabold tracking-tighter">{tier.price}</span>
                <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">One-time</span>
              </div>
              <p className="text-sm text-foreground text-pretty">{tier.tagline}</p>
              <ul className="flex flex-col gap-3 text-sm text-muted-foreground">
                {tier.features.map((f) => (
                  <li key={f} className="flex gap-2">
                    <span className="text-accent">→</span>
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
              <a
                href={`#lead`}
                onClick={() => {
                  if (typeof window !== "undefined") {
                    window.sessionStorage.setItem("lnc_selected_tier", tier.name);
                    window.dispatchEvent(new Event("lnc:tier-selected"));
                  }
                }}
                className={`mt-auto text-center px-5 py-3 font-extrabold text-[11px] uppercase tracking-widest transition-colors ${
                  tier.highlight
                    ? "bg-accent text-background hover:bg-foreground hover:text-background"
                    : "bg-foreground text-background hover:bg-accent"
                }`}
              >
                Choose {tier.name}
              </a>
            </div>
          ))}
        </div>
        <p className="max-w-5xl mx-auto mt-10 font-mono text-[11px] uppercase tracking-widest text-muted-foreground text-center">
          All options are a single one-time payment — the most affordable mentorship on the market.
        </p>
      </section>

      {/* FAQ */}
      <section id="faq" className="px-6 md:px-10 py-24 md:py-32 border-t border-border">
        <div className="max-w-5xl mx-auto flex flex-col gap-12">
          <div className="flex flex-col gap-4">
            <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">FAQ</span>
            <h2 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase leading-[0.95]">
              Eligibility, refunds,{" "}
              <span className="italic font-semibold text-accent" style={{ fontFamily: "var(--font-serif)" }}>
                and what to expect.
              </span>
            </h2>
            <p className="max-w-[60ch] text-muted-foreground text-base md:text-lg text-pretty">
              Straight answers before you commit. If something isn't covered here, drop it in the
              notes field above and we'll address it on the kickoff call.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-border">
            {FAQ_GROUPS.map((group) => (
              <div key={group.title} className="bg-background p-8 flex flex-col gap-5">
                <div className="flex items-baseline justify-between gap-4 border-b border-border pb-3">
                  <h3 className="font-extrabold uppercase tracking-tight text-lg">{group.title}</h3>
                  <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                    {group.kicker}
                  </span>
                </div>
                <dl className="flex flex-col gap-5">
                  {group.items.map((item) => (
                    <div key={item.q} className="flex flex-col gap-1.5">
                      <dt className="font-mono text-[11px] uppercase tracking-widest text-accent">
                        {item.q}
                      </dt>
                      <dd className="text-sm text-muted-foreground text-pretty">{item.a}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>

          {/* What to expect — per tier */}
          <div className="flex flex-col gap-6">
            <h3 className="text-2xl md:text-3xl font-extrabold tracking-tighter uppercase">
              What to expect — by tier
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-px bg-border">
              {TIER_EXPECTATIONS.map((te) => (
                <div key={te.id} className="bg-background p-6 flex flex-col gap-4">
                  <div className="flex flex-col gap-1">
                    <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                      {te.name}
                    </span>
                    <span className="font-mono text-[10px] uppercase tracking-widest text-accent">
                      {te.timeline}
                    </span>
                  </div>
                  <ul className="flex flex-col gap-2.5 text-sm text-muted-foreground">
                    {te.steps.map((s, i) => (
                      <li key={s} className="flex gap-2">
                        <span className="font-mono text-[10px] text-accent pt-1">0{i + 1}</span>
                        <span>{s}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>

          {/* Disclaimer */}
          <div className="border border-accent/40 bg-white/[0.02] p-6 md:p-8 flex flex-col gap-3">
            <span className="font-mono text-[10px] uppercase tracking-widest text-accent">
              Risk Disclaimer
            </span>
            <p className="text-sm text-muted-foreground text-pretty">
              Trading involves substantial risk of loss and is not suitable for every investor.
              Nothing on this page is financial, legal, or tax advice. Past performance and example
              results do not guarantee future returns. Any "guaranteed" language in the Managed
              Trading tier refers to a contractual minimum performance commitment that will be
              detailed in a written agreement before any capital is deployed — by enrolling, you
              acknowledge you've read and understood the terms in that agreement.
            </p>
          </div>
        </div>
      </section>

      {/* Lead capture */}
      <section id="lead" className="px-6 md:px-10 py-24 md:py-32 border-t border-border bg-white/[0.02]">
        <div className="max-w-5xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-16 lg:gap-24">
          <div className="flex flex-col gap-6">
            <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">Get More Leads</span>
            <h2 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase leading-[0.95]">
              Tell us about you.{" "}
              <span className="italic font-semibold text-accent" style={{ fontFamily: "var(--font-serif)" }}>
                We'll reach out.
              </span>
            </h2>
            <p className="text-muted-foreground text-base md:text-lg text-pretty">
              Drop your details and the option that fits. We follow up personally within 24 hours
              with next steps, payment, and a kickoff call.
            </p>
            <div className="pt-4 flex flex-col gap-2 font-mono text-[10px] text-muted-foreground tracking-widest">
              <span>ATLANTA, GEORGIA</span>
              <span>MAC MOORE — FOUNDER &amp; OWNER</span>
              <span>RESPONSE WITHIN 24 HOURS</span>
            </div>
          </div>
          <LeadForm />
        </div>
      </section>

      {/* Footer */}
      <footer className="px-6 md:px-10 py-10 border-t border-border">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6 font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
          <div className="flex items-center gap-3">
            <img src={logo} alt="Lexus Nexus Capital Group logo" width={24} height={24} className="h-6 w-6 object-contain opacity-60" />
            <span>© 2026 Lexus Nexus Capital Group — Atlanta, GA</span>
          </div>
          <span>Mac Moore — Founder, Owner &amp; CEO</span>
        </div>
      </footer>
    </div>
  );
}

const leadSchema = z.object({
  full_name: z.string().min(2, "Please enter your full name").max(120),
  email: z.string().email("Please enter a valid email"),
  tier: z.string().min(1, "Please choose an option").max(120),
  notes: z.string().max(2000).optional(),
});

function LeadForm() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [tier, setTier] = useState(TIERS[1].name);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [checkoutEmail, setCheckoutEmail] = useState<string | null>(null);
  const selectedTier = TIERS.find((t) => t.name === tier) ?? TIERS[0];

  if (typeof window !== "undefined") {
    if (!(window as unknown as { __lncTierWired?: boolean }).__lncTierWired) {
      (window as unknown as { __lncTierWired?: boolean }).__lncTierWired = true;
      window.addEventListener("lnc:tier-selected", () => {
        const saved = window.sessionStorage.getItem("lnc_selected_tier");
        if (saved) setTier(saved);
      });
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = leadSchema.safeParse({ full_name: fullName, email, tier, notes: notes || undefined });
    if (!parsed.success) {
      toast.error(parsed.error.issues[0]?.message ?? "Please check your inputs");
      return;
    }
    setSubmitting(true);

    // Capture attribution: prefer first-touch UTMs stored in sessionStorage,
    // fall back to current URL. Always send current page + referrer.
    let attribution: Record<string, string | undefined> = {};
    if (typeof window !== "undefined") {
      try {
        const url = new URL(window.location.href);
        const stored = window.sessionStorage.getItem("lnc_attribution");
        const firstTouch = stored ? (JSON.parse(stored) as Record<string, string>) : {};
        const get = (k: string) => firstTouch[k] || url.searchParams.get(k) || undefined;
        attribution = {
          utm_source: get("utm_source"),
          utm_medium: get("utm_medium"),
          utm_campaign: get("utm_campaign"),
          utm_term: get("utm_term"),
          utm_content: get("utm_content"),
          referrer: firstTouch.referrer || document.referrer || undefined,
          landing_page: firstTouch.landing_page || window.location.href,
        };
      } catch {
        // ignore attribution capture errors
      }
    }

    const res = await fetch("/api/public/lead-submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        full_name: parsed.data.full_name,
        email: parsed.data.email,
        tier: parsed.data.tier,
        notes: parsed.data.notes,
        ...attribution,
      }),
    });
    setSubmitting(false);
    if (!res.ok) {
      toast.error("Submission failed. Please try again.");
      return;
    }
    toast.success("Got it — check your inbox for next steps.");
    setSubmitted(true);
    setFullName("");
    setEmail("");
    setNotes("");
  };

  if (submitted) {
    return (
      <div className="flex flex-col gap-4 p-8 border border-accent bg-white/[0.03]">
        <span className="font-mono text-[11px] uppercase tracking-widest text-accent">Received</span>
        <h3 className="text-2xl font-extrabold tracking-tighter uppercase">You're on the list.</h3>
        <p className="text-muted-foreground text-sm">
          We'll be in touch within 24 hours with next steps and payment details.
        </p>
        <button
          onClick={() => setSubmitted(false)}
          className="self-start mt-2 font-mono text-[11px] uppercase tracking-widest text-foreground hover:text-accent"
        >
          Submit another →
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5 p-8 border border-border bg-background">
      <label className="flex flex-col gap-2">
        <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Full Name</span>
        <input
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          required
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
          className="bg-transparent border-b border-border focus:border-accent outline-none py-2 text-foreground"
        />
      </label>
      <label className="flex flex-col gap-2">
        <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Selected Option</span>
        <select
          value={tier}
          onChange={(e) => setTier(e.target.value)}
          className="bg-background border border-border focus:border-accent outline-none py-2 px-3 text-foreground"
        >
          {TIERS.map((t) => (
            <option key={t.id} value={t.name}>
              {t.name} — {t.price}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-2">
        <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Notes (optional)</span>
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
        {submitting ? "Submitting…" : "Request Access"}
      </button>
    </form>
  );
}
