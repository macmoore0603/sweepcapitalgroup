import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { supabase } from "@/integrations/supabase/client";
import methodologyImg from "../assets/methodology.jpg";
import heroBg from "../assets/hero-bg.jpg";

export const Route = createFileRoute("/")({
  component: Index,
});

const leadSchema = z.object({
  full_name: z.string().trim().min(2, "Name is required").max(100),
  email: z.string().trim().email("Invalid email").max(255),
  capital_size: z.string().trim().max(100).optional(),
});

function Index() {
  return (
    <div className="min-h-screen bg-background text-foreground font-sans selection:bg-accent selection:text-background">
      {/* Navigation */}
      <nav className="sticky top-0 z-50 flex items-center justify-between px-6 md:px-10 py-5 bg-background/80 backdrop-blur-md border-b border-border">
        <div className="flex items-center gap-3">
          <span className="font-extrabold tracking-tighter text-xl uppercase">Lexus Nexus</span>
          <span className="hidden sm:inline font-mono text-[10px] text-accent border border-accent/40 px-1.5 py-0.5">
            CAPITAL GROUP
          </span>
        </div>
        <div className="hidden md:flex items-center gap-8 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          <a href="#methodology" className="hover:text-foreground transition-colors">Methodology</a>
          <a href="#performance" className="hover:text-foreground transition-colors">Performance</a>
          <a href="#tiers" className="hover:text-foreground transition-colors">Tiers</a>
          <a href="#apply" className="hover:text-foreground transition-colors">Apply</a>
        </div>
        <a href="#apply" className="px-5 py-2.5 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors">
          Request Access
        </a>
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
              DISCIPLINE IS{" "}
              <span className="italic font-semibold text-accent" style={{ fontFamily: "var(--font-serif)" }}>
                the only
              </span>{" "}
              EDGE.
            </h1>
            <p className="max-w-[54ch] text-base md:text-lg text-muted-foreground text-pretty mt-4">
              An institutional-grade mentorship for serious capital allocators. We do not promise wealth; we provide
              the mathematical framework and psychological rigor required to extract it from the market.
            </p>
            <div className="flex flex-wrap gap-4 mt-8">
              <a href="#apply" className="px-7 md:px-8 py-4 bg-foreground text-background font-extrabold text-sm uppercase tracking-widest hover:bg-accent transition-colors">
                Start Application
              </a>
              <a href="#methodology" className="px-7 md:px-8 py-4 border border-border font-extrabold text-sm uppercase tracking-widest hover:bg-white/5 transition-colors">
                View Methodology
              </a>
            </div>
          </div>
        </div>
      </header>

      {/* Performance Matrix */}
      <section id="performance" className="px-6 md:px-10 py-20 md:py-24 border-t border-border bg-white/[0.02]">
        <div className="max-w-7xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-10 md:gap-12">
          {[
            { label: "Audited Win Rate", value: "68.4", suffix: "%" },
            { label: "Avg. Profit Factor", value: "2.42" },
            { label: "Max Drawdown", value: "4.1%", accent: true },
            { label: "Assets Managed", value: "$14M+" },
          ].map((stat) => (
            <div key={stat.label} className="flex flex-col gap-2">
              <span className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest">{stat.label}</span>
              <span className={`text-3xl md:text-4xl font-extrabold tracking-tight ${stat.accent ? "text-accent" : ""}`}>
                {stat.value}
                {stat.suffix && <span className="text-accent">{stat.suffix}</span>}
              </span>
            </div>
          ))}
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
              Selection is based on capital size, experience, and commitment to the Lexus Nexus protocol.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-px bg-border">
            {[
              {
                num: "01",
                tag: "Entry Pool",
                title: "Foundation",
                desc: "Eight weeks of intensive technical training focusing on high-probability order flow and risk mitigation.",
                features: ["Live Stream Access", "Technical Playbook", "Bi-weekly Review"],
                cta: "Apply for Q3",
                featured: false,
              },
              {
                num: "02",
                tag: "Institutional",
                title: "Elite Syndicate",
                desc: "Direct mentorship under senior partners. Real-time trade co-execution and institutional liquidity access.",
                features: ["Daily Live Trading", "Psychological Coaching", "1-on-1 Strategy Tuning"],
                cta: "Limited Availability",
                featured: true,
              },
              {
                num: "03",
                tag: "Hedge Access",
                title: "Capital Alpha",
                desc: "Proprietary desk funding. Full firm backing for traders managing $1M+ portfolios. Revenue share model.",
                features: ["Firm Funding ($250k+)", "Advanced Quant Tools", "Desk-to-Trader Pipeline"],
                cta: "Inquire",
                featured: false,
              },
            ].map((tier) => (
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
                <h3 className="text-2xl font-extrabold uppercase tracking-tight">{tier.title}</h3>
                <p className="text-muted-foreground text-sm leading-relaxed">{tier.desc}</p>
                <ul className="mt-auto flex flex-col gap-4 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
                  {tier.features.map((f) => (
                    <li key={f} className="flex items-center gap-2">
                      <span className="size-1 bg-accent rounded-full" /> {f}
                    </li>
                  ))}
                </ul>
                <a
                  href="#apply"
                  className={`w-full py-4 text-center text-[11px] font-extrabold uppercase tracking-widest transition-colors ${
                    tier.featured ? "bg-foreground text-background" : "border border-border hover:bg-white/5"
                  }`}
                >
                  {tier.cta}
                </a>
              </article>
            ))}
          </div>
        </div>
      </section>

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
                  title: "Liquidity Hunting",
                  desc: "Trading against the herd. We identify institutional traps and position ourselves alongside primary liquidity providers.",
                },
                {
                  n: "02",
                  title: "Volatility Arbitrage",
                  desc: "Harnessing delta-neutral strategies to capitalize on market inefficiencies during high-impact news cycles.",
                },
                {
                  n: "03",
                  title: "Stoic Execution",
                  desc: "Removing the biological error. Our traders operate on a rule-based framework that eliminates emotional variance.",
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

      {/* Apply */}
      <section id="apply" className="px-6 md:px-10 py-24 md:py-32 border-t border-border">
        <div className="max-w-7xl mx-auto">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 lg:gap-32">
            <div className="flex flex-col gap-8">
              <h2 className="text-5xl md:text-6xl font-extrabold tracking-tighter uppercase">
                Secure <br />
                <span className="italic font-semibold text-accent capitalize" style={{ fontFamily: "var(--font-serif)" }}>
                  Your Seat
                </span>
              </h2>
              <p className="text-muted-foreground text-sm font-mono uppercase leading-relaxed tracking-wider">
                Lexus Nexus Capital Group accepts a maximum of twelve mentees per quarter. This ensures the integrity
                of our instruction and the quality of our network.
              </p>
              <div className="pt-8 flex flex-col gap-3 font-mono text-[10px] text-muted-foreground tracking-widest">
                <span>GENEVA / LONDON / SINGAPORE</span>
                <span>EST. MMXXIV — LEXUS NEXUS</span>
              </div>
            </div>
            <ApplicationForm />
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="px-6 md:px-10 py-10 border-t border-border">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6 font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
          <span>© 2026 Lexus Nexus Capital Group — All rights reserved.</span>
          <div className="flex gap-6">
            <a href="#" className="hover:text-foreground">Risk Disclosure</a>
            <a href="#" className="hover:text-foreground">Terms</a>
            <a href="#" className="hover:text-foreground">Privacy</a>
          </div>
        </div>
      </footer>
    </div>
  );
}

function ApplicationForm() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [capitalSize, setCapitalSize] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = leadSchema.safeParse({
      full_name: fullName,
      email,
      capital_size: capitalSize || undefined,
    });
    if (!parsed.success) {
      toast.error(parsed.error.issues[0]?.message ?? "Please check your inputs");
      return;
    }
    setSubmitting(true);
    const { error } = await supabase.from("leads").insert({
      full_name: parsed.data.full_name,
      email: parsed.data.email,
      capital_size: parsed.data.capital_size ?? null,
    });
    setSubmitting(false);
    if (error) {
      toast.error("Submission failed. Please try again.");
      return;
    }
    toast.success("Application received. Our intake team will reach out within 48 hours.");
    setFullName("");
    setEmail("");
    setCapitalSize("");
  };

  return (
    <form className="space-y-8" onSubmit={handleSubmit}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-8">
        <div className="space-y-2">
          <label className="font-mono text-[10px] uppercase text-muted-foreground tracking-widest">Full Name</label>
          <input
            required
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            maxLength={100}
            className="w-full bg-transparent border-b border-border py-4 focus:outline-none focus:border-accent text-lg placeholder:text-muted-foreground/40"
            placeholder="ALEXANDER VAUGHN"
          />
        </div>
        <div className="space-y-2">
          <label className="font-mono text-[10px] uppercase text-muted-foreground tracking-widest">Capital Size</label>
          <input
            type="text"
            value={capitalSize}
            onChange={(e) => setCapitalSize(e.target.value)}
            maxLength={100}
            className="w-full bg-transparent border-b border-border py-4 focus:outline-none focus:border-accent text-lg placeholder:text-muted-foreground/40"
            placeholder="$100K — $500K"
          />
        </div>
      </div>
      <div className="space-y-2">
        <label className="font-mono text-[10px] uppercase text-muted-foreground tracking-widest">Email Address</label>
        <input
          required
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          maxLength={255}
          className="w-full bg-transparent border-b border-border py-4 focus:outline-none focus:border-accent text-lg placeholder:text-muted-foreground/40"
          placeholder="CLIENT@PROTOCOL.COM"
        />
      </div>
      <button
        type="submit"
        disabled={submitting}
        className="w-full py-5 md:py-6 bg-foreground text-background font-extrabold uppercase tracking-[0.2em] hover:bg-accent transition-colors duration-500 disabled:opacity-50"
      >
        {submitting ? "Submitting…" : "Submit Application for Review"}
      </button>
    </form>
  );
}
            </form>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="px-6 md:px-10 py-10 border-t border-border">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6 font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
          <span>© 2026 Lexus Nexus Capital Group — All rights reserved.</span>
          <div className="flex gap-6">
            <a href="#" className="hover:text-foreground">Risk Disclosure</a>
            <a href="#" className="hover:text-foreground">Terms</a>
            <a href="#" className="hover:text-foreground">Privacy</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
