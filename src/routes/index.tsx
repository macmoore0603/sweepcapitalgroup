import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { Menu } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger, SheetClose } from "@/components/ui/sheet";
import { supabase } from "@/integrations/supabase/client";
import methodologyImg from "../assets/methodology.jpg";
import heroBg from "../assets/hero-bg.jpg";
import logo from "../assets/lnc-logo.png";

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
          <img src={logo} alt="Lexus Nexus Capital Group logo" width={32} height={32} className="h-8 w-8 object-contain" />
          <span className="font-extrabold tracking-tighter text-xl uppercase">Lexus Nexus</span>
          <span className="hidden sm:inline font-mono text-[10px] text-accent border border-accent/40 px-1.5 py-0.5">
            CAPITAL GROUP
          </span>
        </div>
        <div className="hidden md:flex items-center gap-8 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          <a href="#methodology" className="hover:text-foreground transition-colors">Methodology</a>
          <a href="#performance" className="hover:text-foreground transition-colors">Performance</a>
          <a href="#tiers" className="hover:text-foreground transition-colors">Tiers</a>
          <Link to="/about" className="hover:text-foreground transition-colors">About</Link>
          <Link to="/leadership" className="hover:text-foreground transition-colors">Leadership</Link>
          <a href="#apply" className="hover:text-foreground transition-colors">Apply</a>
          <a href="#contact" className="hover:text-foreground transition-colors">Contact</a>
        </div>
        <div className="flex items-center gap-3">
          <a href="#apply" className="hidden sm:inline-block px-5 py-2.5 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors">
            Request Access
          </a>
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
                  Lexus Nexus
                </SheetTitle>
              </SheetHeader>
              <nav className="flex flex-col mt-8 font-mono text-xs uppercase tracking-widest">
                {[
                  { label: "Methodology", href: "#methodology", type: "hash" as const },
                  { label: "Performance", href: "#performance", type: "hash" as const },
                  { label: "Tiers", href: "#tiers", type: "hash" as const },
                  { label: "Apply", href: "#apply", type: "hash" as const },
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
                  <a
                    href="#apply"
                    className="mt-8 px-5 py-4 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest text-center hover:bg-accent transition-colors"
                  >
                    Request Access
                  </a>
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
            { label: "Assets Managed", value: "$2.4M" },
            { label: "Avg. Trade Return", value: "4.2x" },
            { label: "Avg. Monthly Return", value: "5.6", suffix: "%" },
            { label: "Risk / Reward Ratio", value: "1:2.8" },
            { label: "Sharpe Ratio", value: "2.14" },
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

      {/* Founder */}
      <section id="founder" className="px-6 md:px-10 py-24 md:py-32 border-t border-border bg-white/[0.02]">
        <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-[1fr_2fr] gap-12 md:gap-20 items-start">
          <div className="flex flex-col gap-4">
            <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">The Founder</span>
            <div className="aspect-[4/5] w-full bg-gradient-to-br from-accent/30 via-muted to-background border border-border flex items-end p-5">
              <span className="font-extrabold text-5xl tracking-tighter leading-none">MM</span>
            </div>
            <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              Atlanta, Georgia
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
              A decade behind the screens of institutional desks taught Mac one lesson worth repeating:
              the market does not reward intelligence — it rewards success. He founded Lexus Nexus Capital
              Group in Atlanta to compress that lesson into a deliberate, repeatable framework for the
              traders he chooses to mentor.
            </p>
            <p className="text-muted-foreground text-base md:text-lg leading-relaxed text-pretty">
              His approach is unromantic: edge is built through statistical rigor, position sizing, and an
              unwavering process. Each mentee is selected personally, briefed personally, and held personally
              accountable to the same standards Mac runs his own book against.
            </p>
            <div className="grid grid-cols-3 gap-6 pt-4 border-t border-border mt-2">
              {[
                { k: "10+ YRS", v: "Trading Desks" },
                { k: "$2.4M", v: "Allocated" },
                { k: "12 / QTR", v: "Selected Mentees" },
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
                <span>ATLANTA, GEORGIA</span>
                <span>MAC MOORE — FOUNDER &amp; OWNER</span>
                <span>EST. MMXXIV — LEXUS NEXUS</span>
              </div>
            </div>
            <ApplicationForm />
          </div>
        </div>
      </section>

      {/* Contact */}
      <section id="contact" className="px-6 md:px-10 py-20 md:py-28 border-t border-border bg-white/[0.02]">
        <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-[1fr_2fr] gap-12 md:gap-20">
          <div className="flex flex-col gap-4">
            <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">Contact</span>
            <h2 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase leading-[0.95]">
              Atlanta,{" "}
              <span className="italic font-semibold text-accent" style={{ fontFamily: "var(--font-serif)" }}>
                Georgia.
              </span>
            </h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-10">
            <div className="flex flex-col gap-2">
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Headquarters</span>
              <span className="text-foreground font-semibold">Atlanta, Georgia</span>
            </div>
            <div className="flex flex-col gap-2">
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Mailing Address</span>
              <address className="not-italic text-foreground leading-relaxed">
                Lexus Nexus Capital Group<br />
                1131 Oaklake Terrace<br />
                Watkinsville, GA 30677
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
      <footer className="px-6 md:px-10 py-10 border-t border-border">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6 font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
          <div className="flex items-center gap-3">
            <img src={logo} alt="Lexus Nexus Capital Group logo" width={24} height={24} className="h-6 w-6 object-contain opacity-60" />
            <span>© 2026 Lexus Nexus Capital Group — Atlanta, GA</span>
          </div>
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
  const [leadId, setLeadId] = useState<string | null>(null);
  const [bookingToken, setBookingToken] = useState<string | null>(null);
  const [scheduledAt, setScheduledAt] = useState<Date | null>(null);

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
    const { data, error } = await supabase
      .from("leads")
      .insert({
        full_name: parsed.data.full_name,
        email: parsed.data.email,
        capital_size: parsed.data.capital_size ?? null,
      })
      .select("id, booking_token")
      .single();
    setSubmitting(false);
    if (error || !data) {
      toast.error("Submission failed. Please try again.");
      return;
    }
    toast.success("Application received. Please book your introductory call.");
    setLeadId(data.id);
    setBookingToken(data.booking_token);
  };

  const [rescheduling, setRescheduling] = useState(false);

  if (leadId && bookingToken && scheduledAt && !rescheduling) {
    return (
      <SchedulingConfirmation
        slot={scheduledAt}
        leadId={leadId}
        bookingToken={bookingToken}
        onReschedule={() => setRescheduling(true)}
        onCancelled={() => setScheduledAt(null)}
      />
    );
  }

  if (leadId && bookingToken) {
    return (
      <CallScheduler
        leadId={leadId}
        bookingToken={bookingToken}
        mode={rescheduling ? "reschedule" : "initial"}
        currentSlot={scheduledAt}
        onScheduled={(slot) => {
          setScheduledAt(slot);
          setRescheduling(false);
        }}
        onBack={rescheduling ? () => setRescheduling(false) : undefined}
      />
    );
  }

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

function generateSlots(): Date[] {
  const slots: Date[] = [];
  const now = new Date();
  let day = new Date(now);
  day.setHours(0, 0, 0, 0);
  day.setDate(day.getDate() + 1);
  const hours = [10, 11, 13, 14, 15, 16];
  let added = 0;
  while (added < 5) {
    const dow = day.getDay();
    if (dow !== 0 && dow !== 6) {
      for (const h of hours) {
        const slot = new Date(day);
        slot.setHours(h, 0, 0, 0);
        if (slot > now) slots.push(slot);
      }
      added++;
    }
    day.setDate(day.getDate() + 1);
  }
  return slots;
}

function CallScheduler({
  leadId,
  bookingToken,
  mode = "initial",
  currentSlot,
  onScheduled,
  onBack,
}: {
  leadId: string;
  bookingToken: string;
  mode?: "initial" | "reschedule";
  currentSlot?: Date | null;
  onScheduled: (slot: Date) => void;
  onBack?: () => void;
}) {
  const slots = generateSlots();
  const days = Array.from(
    slots.reduce((acc, s) => {
      const key = s.toDateString();
      if (!acc.has(key)) acc.set(key, []);
      acc.get(key)!.push(s);
      return acc;
    }, new Map<string, Date[]>()).entries()
  );
  const [selectedDay, setSelectedDay] = useState(days[0]?.[0] ?? "");
  const [booking, setBooking] = useState<string | null>(null);

  const isReschedule = mode === "reschedule";

  const handleBook = async (slot: Date) => {
    setBooking(slot.toISOString());
    const rpcName = isReschedule ? "reschedule_lead_call" : "schedule_lead_call";
    const { data, error } = await supabase.rpc(rpcName, {
      _lead_id: leadId,
      _token: bookingToken,
      _slot: slot.toISOString(),
    });
    setBooking(null);
    if (error || !data) {
      toast.error(
        isReschedule
          ? "Could not reschedule. The call may have already passed."
          : "Could not book that slot. Try another time.",
      );
      return;
    }
    toast.success(isReschedule ? "Call rescheduled." : "Call confirmed. Calendar invite incoming.");
    onScheduled(slot);
  };

  const daySlots = days.find(([k]) => k === selectedDay)?.[1] ?? [];

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <div className="font-mono text-[10px] uppercase text-muted-foreground tracking-widest">
          {isReschedule ? "Reschedule Call" : "Step 02 — Book Introductory Call"}
        </div>
        <h3 className="text-2xl md:text-3xl font-extrabold tracking-tight uppercase">
          {isReschedule ? "Pick a new window" : "Select a 30-minute window"}
        </h3>
        {isReschedule && currentSlot && (
          <p className="font-mono text-[11px] text-muted-foreground tracking-wider">
            Current:{" "}
            <span className="text-accent">
              {currentSlot.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}{" "}
              · {currentSlot.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
            </span>
          </p>
        )}
        {!isReschedule && (
          <p className="font-mono text-[11px] text-muted-foreground tracking-wider">
            Times shown in your local timezone. Recorded & encrypted.
          </p>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        {days.map(([key]) => {
          const d = new Date(key);
          const active = key === selectedDay;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setSelectedDay(key)}
              className={`p-3 border text-left transition-colors ${
                active
                  ? "border-accent bg-accent/10 text-foreground"
                  : "border-border text-muted-foreground hover:border-foreground/50"
              }`}
            >
              <div className="font-mono text-[9px] uppercase tracking-widest">
                {d.toLocaleDateString(undefined, { weekday: "short" })}
              </div>
              <div className="text-lg font-extrabold mt-1">
                {d.toLocaleDateString(undefined, { day: "2-digit" })}
              </div>
              <div className="font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
                {d.toLocaleDateString(undefined, { month: "short" })}
              </div>
            </button>
          );
        })}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {daySlots.map((slot) => {
          const iso = slot.toISOString();
          const isBooking = booking === iso;
          return (
            <button
              key={iso}
              type="button"
              disabled={booking !== null}
              onClick={() => handleBook(slot)}
              className="py-3 border border-border font-mono text-xs uppercase tracking-widest hover:border-accent hover:text-accent transition-colors disabled:opacity-40"
            >
              {isBooking
                ? "Booking…"
                : slot.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
            </button>
          );
        })}
      </div>

      {onBack && (
        <button
          type="button"
          onClick={onBack}
          className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
        >
          ← Keep current time
        </button>
      )}
    </div>
  );
}

function SchedulingConfirmation({
  slot,
  leadId,
  bookingToken,
  onReschedule,
  onCancelled,
}: {
  slot: Date;
  leadId: string;
  bookingToken: string;
  onReschedule: () => void;
  onCancelled: () => void;
}) {
  const [cancelling, setCancelling] = useState(false);

  const handleCancel = async () => {
    if (!confirm("Cancel your scheduled call? You'll need to pick a new time.")) return;
    setCancelling(true);
    const { data, error } = await supabase.rpc("reschedule_lead_call", {
      _lead_id: leadId,
      _token: bookingToken,
      _slot: null as unknown as string,
    });
    setCancelling(false);
    if (error || !data) {
      toast.error("Could not cancel. The call may have already passed.");
      return;
    }
    toast.success("Call cancelled.");
    onCancelled();
  };

  return (
    <div className="space-y-6 border border-accent/40 p-8 bg-accent/5">
      <div className="font-mono text-[10px] uppercase text-accent tracking-widest">
        ✓ Confirmed
      </div>
      <h3 className="text-3xl md:text-4xl font-extrabold tracking-tight uppercase">
        You're on the desk
      </h3>
      <div className="space-y-1 font-mono text-sm">
        <div className="text-muted-foreground text-[10px] uppercase tracking-widest">Call scheduled for</div>
        <div className="text-foreground text-lg">
          {slot.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
        </div>
        <div className="text-accent text-lg">
          {slot.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
        </div>
      </div>
      <p className="font-mono text-[11px] text-muted-foreground tracking-wider leading-relaxed">
        A calendar invitation with secure dial-in credentials will be dispatched to your inbox shortly.
      </p>
      <div className="flex flex-col sm:flex-row gap-3 pt-2 border-t border-accent/20">
        <button
          type="button"
          onClick={onReschedule}
          disabled={cancelling}
          className="flex-1 py-3 border border-border font-mono text-[11px] uppercase tracking-widest hover:border-accent hover:text-accent transition-colors disabled:opacity-40"
        >
          Reschedule
        </button>
        <button
          type="button"
          onClick={handleCancel}
          disabled={cancelling}
          className="flex-1 py-3 border border-destructive/40 font-mono text-[11px] uppercase tracking-widest text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-40"
        >
          {cancelling ? "Cancelling…" : "Cancel Call"}
        </button>
      </div>
    </div>
  );
}
