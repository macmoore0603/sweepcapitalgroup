import { createFileRoute, Link } from "@tanstack/react-router";

export const Route = createFileRoute("/leadership")({
  head: () => ({
    meta: [
      { title: "Leadership — Lexus Nexus Capital Group" },
      {
        name: "description",
        content:
          "Meet the leadership of Lexus Nexus Capital Group: founder Mac Moore and partner Christopher Nguyen, leading a private trading practice from Atlanta, Georgia.",
      },
      { property: "og:title", content: "Leadership — Lexus Nexus Capital Group" },
      {
        property: "og:description",
        content:
          "Founder Mac Moore and partner Christopher Nguyen lead a private trading mentorship out of Atlanta, Georgia.",
      },
    ],
  }),
  component: LeadershipPage,
});

type Leader = {
  name: string;
  title: string;
  initials: string;
  location: string;
  bio: string[];
  stats: { k: string; v: string }[];
};

const LEADERS: Leader[] = [
  {
    name: "Mac Moore",
    title: "Founder, Owner & CEO",
    initials: "MM",
    location: "Atlanta, Georgia",
    bio: [
      "A decade behind institutional desks taught Mac one lesson worth repeating: the market does not reward intelligence — it rewards discipline. He founded Lexus Nexus Capital Group in Atlanta to compress that lesson into a deliberate, repeatable framework for the traders he chooses to mentor.",
      "Every mentee is selected personally, briefed personally, and held personally accountable to the same standards Mac runs his own book against.",
    ],
    stats: [
      { k: "10+ YRS", v: "Trading Desks" },
      { k: "$2.4M", v: "Allocated" },
      { k: "Atlanta", v: "Headquarters" },
    ],
  },
  {
    name: "Christopher Nguyen",
    title: "Co-Founder & Director of Asset Management",
    initials: "CN",
    location: "Atlanta, Georgia",
    bio: [
      "Christopher co-founded Lexus Nexus Capital Group alongside Mac Moore, leading strategy design, risk architecture, and mentee selection. His focus is the quantitative underwriting of every position — building the rails that keep the firm's discipline measurable rather than theoretical.",
      "He works directly with each cohort on execution review and post-trade analysis, translating data into the next quarter's playbook.",
    ],
    stats: [
      { k: "QUANT", v: "Risk & Strategy" },
      { k: "1:1", v: "Mentee Reviews" },
      { k: "ATL", v: "Based" },
    ],
  },
];

function LeadershipPage() {
  return (
    <div className="min-h-screen bg-background text-foreground font-sans">
      {/* Navigation */}
      <nav className="sticky top-0 z-50 flex items-center justify-between px-6 md:px-10 py-5 bg-background/80 backdrop-blur-md border-b border-border">
        <Link to="/" className="flex items-center gap-3">
          <span className="font-extrabold tracking-tighter text-xl uppercase">Lexus Nexus</span>
          <span className="hidden sm:inline font-mono text-[10px] text-accent border border-accent/40 px-1.5 py-0.5">
            CAPITAL GROUP
          </span>
        </Link>
        <div className="hidden md:flex items-center gap-8 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
          <Link to="/" className="hover:text-foreground transition-colors">Home</Link>
          <Link to="/about" className="hover:text-foreground transition-colors">About</Link>
          <Link to="/leadership" className="text-foreground">Leadership</Link>
          <Link to="/" hash="apply" className="hover:text-foreground transition-colors">Apply</Link>
        </div>
        <Link
          to="/"
          hash="apply"
          className="px-5 py-2.5 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors"
        >
          Request Access
        </Link>
      </nav>

      {/* Hero */}
      <header className="px-6 md:px-10 pt-20 md:pt-28 pb-16 md:pb-20 border-b border-border">
        <div className="max-w-5xl mx-auto flex flex-col gap-6">
          <span className="font-mono text-accent text-[12px] uppercase tracking-[0.3em]">Leadership</span>
          <h1 className="text-5xl md:text-7xl font-extrabold tracking-tighter uppercase leading-[0.9]">
            The desk{" "}
            <span className="italic font-semibold text-accent" style={{ fontFamily: "var(--font-serif)" }}>
              behind the protocol.
            </span>
          </h1>
          <p className="max-w-[60ch] text-base md:text-lg text-muted-foreground text-pretty">
            Lexus Nexus Capital Group is led by a deliberately small team out of Atlanta, Georgia. Every
            mentee works directly with the people listed below — not a sales floor, not a junior analyst.
          </p>
        </div>
      </header>

      {/* Leaders */}
      <section className="px-6 md:px-10 py-20 md:py-28">
        <div className="max-w-5xl mx-auto flex flex-col gap-24 md:gap-32">
          {LEADERS.map((leader, idx) => (
            <article
              key={leader.name}
              className={`grid grid-cols-1 md:grid-cols-[1fr_2fr] gap-12 md:gap-20 items-start ${
                idx % 2 === 1 ? "md:[&>*:first-child]:order-2" : ""
              }`}
            >
              <div className="flex flex-col gap-4">
                <div className="aspect-[4/5] w-full bg-gradient-to-br from-accent/30 via-muted to-background border border-border flex items-end p-5">
                  <span className="font-extrabold text-5xl tracking-tighter leading-none">
                    {leader.initials}
                  </span>
                </div>
                <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                  {leader.location}
                </div>
              </div>

              <div className="flex flex-col gap-6">
                <div className="flex flex-col gap-2">
                  <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">
                    {leader.title}
                  </span>
                  <h2 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase">
                    {leader.name}
                  </h2>
                </div>
                {leader.bio.map((p, i) => (
                  <p
                    key={i}
                    className="text-muted-foreground text-base md:text-lg leading-relaxed text-pretty"
                  >
                    {p}
                  </p>
                ))}
                <div className="grid grid-cols-3 gap-6 pt-4 border-t border-border mt-2">
                  {leader.stats.map((s) => (
                    <div key={s.k} className="flex flex-col gap-1">
                      <span className="font-extrabold text-xl md:text-2xl tracking-tight text-accent">
                        {s.k}
                      </span>
                      <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                        {s.v}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="px-6 md:px-10 py-20 md:py-24 border-t border-border bg-white/[0.02]">
        <div className="max-w-3xl mx-auto flex flex-col items-start gap-6">
          <h2 className="text-3xl md:text-4xl font-extrabold tracking-tighter uppercase">
            Work directly with the team.
          </h2>
          <p className="text-muted-foreground text-base md:text-lg leading-relaxed text-pretty">
            Twelve mentees per quarter. Selection is personal. If our framework fits the way you
            intend to allocate capital, request access below.
          </p>
          <div className="flex flex-wrap gap-4">
            <Link
              to="/"
              hash="apply"
              className="px-7 py-4 bg-foreground text-background font-extrabold text-sm uppercase tracking-widest hover:bg-accent transition-colors"
            >
              Start Application
            </Link>
            <Link
              to="/about"
              className="px-7 py-4 border border-border font-extrabold text-sm uppercase tracking-widest hover:bg-white/5 transition-colors"
            >
              About the Firm
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="px-6 md:px-10 py-10 border-t border-border">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6 font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
          <span>© 2026 Lexus Nexus Capital Group — Atlanta, GA</span>
          <span>Mac Moore — Founder, Owner &amp; CEO</span>
        </div>
      </footer>
    </div>
  );
}
