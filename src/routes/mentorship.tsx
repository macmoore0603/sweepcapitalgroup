import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { z } from "zod";
import { toast } from "sonner";

import logo from "../assets/lnc-logo.png";

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
    const res = await fetch("/api/public/lead-submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        full_name: parsed.data.full_name,
        email: parsed.data.email,
        tier: parsed.data.tier,
        notes: parsed.data.notes,
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
