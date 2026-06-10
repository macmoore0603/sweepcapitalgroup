import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { Menu } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger, SheetClose } from "@/components/ui/sheet";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { supabase } from "@/integrations/supabase/client";
import methodologyImg from "../assets/methodology.jpg";
import heroBg from "../assets/hero-bg.jpg";
import logo from "../assets/lnc-logo.png";
import macMoore from "../assets/mac-moore.png";
import { CallScheduler, SchedulingConfirmation } from "@/components/booking";
import { StripeEmbeddedCheckout } from "@/components/StripeEmbeddedCheckout";
import { PaymentTestModeBanner } from "@/components/PaymentTestModeBanner";

export const Route = createFileRoute("/")({
  component: Index,
});

const leadSchema = z.object({
  full_name: z.string().trim().min(2, "Name is required").max(100),
  email: z.string().trim().email("Invalid email").max(255),
  capital_size: z.string().trim().max(100).optional(),
});

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
          <a href="#performance" className="hover:text-foreground transition-colors">Performance</a>
          <a href="#tiers" className="hover:text-foreground transition-colors">Tiers</a>
          <Link to="/about" className="hover:text-foreground transition-colors">About</Link>
          <Link to="/leadership" className="hover:text-foreground transition-colors">Leadership</Link>
          <Link to="/mentorship" className="hover:text-foreground transition-colors">Mentorship</Link>
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
                  Sweep
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
              Strategies. Risk Management. Real Results. Build skill. Trade smart. Create freedom — through three
              repeatable institutional setups: the Session Sweep, the 5–15 Gap, and the Power of 3.
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
              All one-time payment. The most affordable mentorship on the market.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-px bg-border">
            {[
              {
                num: "01",
                tag: "Self-Paced",
                title: "The Edge",
                price: "$500",
                priceId: "mentorship_course_onetime",
                desc: "My complete trading system in one self-paced course — the exact framework, setups, and risk rules I use to stay profitable.",
                features: ["Full video curriculum", "Lifetime updates", "Private student community"],
                cta: "Get The Edge",
                featured: false,
              },
              {
                num: "02",
                tag: "Most Popular",
                title: "The Apprenticeship",
                price: "$1,500",
                priceId: "mentorship_course_coaching_onetime",
                desc: "The Edge plus personal 1-on-1 coaching — I walk you through every setup, review your trades, and stay with you until you're consistently profitable.",
                features: ["Everything in The Edge", "1:1 step-by-step walkthroughs", "Direct messaging access", "Coaching until profitable"],
                cta: "Start Apprenticeship",
                featured: true,
              },
              {
                num: "03",
                tag: "Done-For-You",
                title: "Managed Trading",
                price: "$500",
                priceId: "mentorship_managed_onetime",
                desc: "Your account is personally managed and traded on your behalf. Guaranteed $2,000 minimum profit in a 3–4 week window — or your money back, no questions asked.",
                features: ["We trade your account for you", "Guaranteed $2k minimum profit", "3–4 week performance window", "Weekly transparent updates", "Money-back guarantee"],
                cta: "Start Managed Trading",
                featured: false,
              },
              {
                num: "04",
                tag: "Best Value",
                title: "The Full Send",
                price: "$2,000",
                priceId: "mentorship_all_inclusive_onetime",
                desc: "Everything in one package — The Edge course, 1-on-1 apprenticeship, and managed trading with the $2k guarantee. The fastest path from beginner to profitable.",
                features: ["Full Edge course access", "1:1 mentorship until profitable", "Managed trading ($2k guarantee)", "Highest-priority support"],
                cta: "Go Full Send",
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
                  onClick={() => {
                    setCheckoutTitle(tier.title);
                    setCheckoutPriceId(tier.priceId);
                  }}
                  className={`w-full py-4 text-center text-[11px] font-extrabold uppercase tracking-widest transition-colors ${
                    tier.featured ? "bg-foreground text-background hover:bg-accent" : "border border-border hover:bg-white/5"
                  }`}
                >
                  {tier.cta}
                </button>
              </article>
            ))}
          </div>
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
            {checkoutPriceId && <StripeEmbeddedCheckout priceId={checkoutPriceId} />}
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
              Three years behind the screens of institutional desks taught Mac one lesson worth repeating:
              the market does not reward intelligence — it rewards success. He founded Sweep Capital Group
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
                { k: "3 YRS", v: "Trading Desks" },
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
                Sweep Capital Group accepts a maximum of twelve mentees per quarter. This ensures the integrity
                of our instruction and the quality of our network.
              </p>
              <div className="pt-8 flex flex-col gap-3 font-mono text-[10px] text-muted-foreground tracking-widest">
                <span>ATLANTA, GEORGIA</span>
                <span>MAC MOORE — FOUNDER &amp; OWNER</span>
                <span>EST. MMXXIV — MOMENTUM</span>
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
                Sweep Capital Group<br />
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
            <img src={logo} alt="Sweep Capital Group logo" width={24} height={24} className="h-6 w-6 object-contain opacity-60" />
            <span>© 2026 Sweep Capital Group — Atlanta, GA</span>
          </div>
          <div className="flex gap-6">
            <Link to="/terms" className="hover:text-foreground transition-colors">Terms</Link>
            <Link to="/privacy" className="hover:text-foreground transition-colors">Privacy</Link>
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

