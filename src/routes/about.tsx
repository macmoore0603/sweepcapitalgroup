import { createFileRoute, Link } from "@tanstack/react-router";
import logo from "../assets/lnc-logo.png";

export const Route = createFileRoute("/about")({
  head: () => ({
    meta: [
      { title: "About — Momentum Capital Group" },
      {
        name: "description",
        content:
          "Momentum Capital Group is a private trading mentorship based in Atlanta, Georgia, owned and led by founder Mac Moore.",
      },
      { property: "og:title", content: "About — Momentum Capital Group" },
      {
        property: "og:description",
        content:
          "Based in Atlanta, Georgia. Founded and owned by Mac Moore. Institutional-grade discipline for serious capital allocators.",
      },
    ],
  }),
  component: AboutPage,
});

function AboutPage() {
  return (
    <div className="min-h-screen bg-background text-foreground font-sans">
      {/* Navigation */}
      <nav className="sticky top-0 z-50 flex items-center justify-between px-6 md:px-10 py-5 bg-background/80 backdrop-blur-md border-b border-border">
        <Link to="/" className="flex items-center gap-3">
          <img src={logo} alt="Momentum Capital Group logo" width={32} height={32} className="h-8 w-8 object-contain" />
          <span className="font-extrabold tracking-tighter text-xl uppercase">Momentum</span>
          <span className="hidden sm:inline font-mono text-[10px] text-accent border border-accent/40 px-1.5 py-0.5">
            CAPITAL GROUP
          </span>
        </Link>
        <div className="hidden md:flex items-center gap-8 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          <Link to="/" className="hover:text-foreground transition-colors">Home</Link>
          <Link to="/about" className="text-foreground">About</Link>
          <Link to="/mentorship" className="hover:text-foreground transition-colors">Mentorship</Link>
          <Link to="/" hash="apply" className="hover:text-foreground transition-colors">Apply</Link>
        </div>
        <Link to="/" hash="apply" className="px-5 py-2.5 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors">
          Request Access
        </Link>
      </nav>

      {/* Hero */}
      <header className="px-6 md:px-10 pt-20 md:pt-28 pb-16 md:pb-20 border-b border-border">
        <div className="max-w-5xl mx-auto flex flex-col gap-6">
          <span className="font-mono text-accent text-[12px] uppercase tracking-[0.3em]">About the Firm</span>
          <h1 className="text-5xl md:text-7xl font-extrabold tracking-tighter uppercase leading-[0.9]">
            A private office,{" "}
            <span className="italic font-semibold text-accent" style={{ fontFamily: "var(--font-serif)" }}>
              built in Atlanta.
            </span>
          </h1>
          <p className="max-w-[60ch] text-base md:text-lg text-muted-foreground text-pretty">
            Momentum Capital Group is a private trading mentorship and capital allocation practice
            headquartered in Atlanta, Georgia. We are founded, owned, and personally led by Mac Moore.
          </p>
        </div>
      </header>

      {/* Body */}
      <section className="px-6 md:px-10 py-20 md:py-28">
        <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-[1fr_2fr] gap-12 md:gap-20">
          <aside className="flex flex-col gap-6 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            <div className="flex flex-col gap-1">
              <span className="text-foreground">Headquarters</span>
              <span>Atlanta, Georgia</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-foreground">Founder, Owner &amp; CEO</span>
              <span>Mac Moore</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-foreground">Established</span>
              <span>MMXXIV</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-foreground">Capacity</span>
              <span>12 Mentees / Quarter</span>
            </div>
          </aside>

          <div className="flex flex-col gap-6">
            <h2 className="text-3xl md:text-4xl font-extrabold tracking-tighter uppercase">Who we are</h2>
            <p className="text-muted-foreground text-base md:text-lg leading-relaxed text-pretty">
              Momentum Capital Group operates out of Atlanta, Georgia as a deliberately small,
              relationship-driven trading practice. We are not a fund-of-funds, not a course, and not a
              signals service. We are a private office where serious capital allocators are mentored
              one cohort at a time.
            </p>

            <h2 className="text-3xl md:text-4xl font-extrabold tracking-tighter uppercase pt-6">The founder</h2>
            <p className="text-muted-foreground text-base md:text-lg leading-relaxed text-pretty">
              The firm was founded and is owned by <span className="text-foreground font-semibold">Mac Moore</span>.
              Three years behind institutional desks taught Mac one lesson worth repeating: the market does
              not reward intelligence — it rewards discipline. He built Momentum to compress that
              lesson into a deliberate, repeatable framework for the traders he chooses to mentor.
            </p>
            <p className="text-muted-foreground text-base md:text-lg leading-relaxed text-pretty">
              Every mentee is selected personally, briefed personally, and held personally accountable
              to the same standards Mac runs his own book against.
            </p>

            <div className="pt-8 flex flex-wrap gap-4">
              <Link
                to="/"
                hash="apply"
                className="px-7 py-4 bg-foreground text-background font-extrabold text-sm uppercase tracking-widest hover:bg-accent transition-colors"
              >
                Start Application
              </Link>
              <Link
                to="/"
                className="px-7 py-4 border border-border font-extrabold text-sm uppercase tracking-widest hover:bg-white/5 transition-colors"
              >
                Back to Home
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="px-6 md:px-10 py-10 border-t border-border">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6 font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
          <div className="flex items-center gap-3">
            <img src={logo} alt="Momentum Capital Group logo" width={24} height={24} className="h-6 w-6 object-contain opacity-60" />
            <span>© 2026 Momentum Capital Group — Atlanta, GA</span>
          </div>
          <span>Mac Moore — Founder, Owner &amp; CEO</span>
        </div>
      </footer>
    </div>
  );
}
