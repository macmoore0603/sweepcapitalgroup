import { createFileRoute, Link } from "@tanstack/react-router";
import { LearnNav, LEARN_RISK_DISCLAIMER } from "@/components/LearnArticle";
import { LEARN_ARTICLES, LEARN_BASE_URL } from "@/lib/learn-articles";

const TITLE = "Learn Futures Trading: Free Guides | Sweep Capital Group";
const DESCRIPTION =
  "Free, plain-English futures trading guides: prop firm evaluations, trailing drawdown, micro futures, the best time to trade NQ, journaling, and risk management. Education, not advice.";

export const Route = createFileRoute("/learn/")({
  head: () => ({
    meta: [
      { title: TITLE },
      { name: "description", content: DESCRIPTION },
      { property: "og:title", content: TITLE },
      { property: "og:description", content: DESCRIPTION },
      { property: "og:url", content: `${LEARN_BASE_URL}/learn` },
    ],
    links: [{ rel: "canonical", href: `${LEARN_BASE_URL}/learn` }],
  }),
  component: LearnIndexPage,
});

function LearnIndexPage() {
  return (
    <div className="min-h-screen bg-background text-foreground font-sans">
      <LearnNav />
      <header className="px-6 md:px-10 pt-16 md:pt-24 pb-12 border-b border-border">
        <div className="max-w-4xl mx-auto flex flex-col gap-6">
          <span className="font-mono text-accent text-[12px] uppercase tracking-[0.3em]">Learn</span>
          <h1 className="text-5xl md:text-7xl font-extrabold tracking-tighter uppercase leading-[0.9]">
            Futures trading,{" "}
            <span className="italic font-semibold text-accent" style={{ fontFamily: "var(--font-serif)" }}>
              risk first.
            </span>
          </h1>
          <p className="max-w-[60ch] text-base md:text-lg text-muted-foreground text-pretty">
            Free guides for newer futures traders. No signals and no profit promises: just the rules, the math, and a
            process you can write down and review.
          </p>
        </div>
      </header>
      <section className="px-6 md:px-10 py-16">
        <a
          href="/checklist"
          className="max-w-4xl mx-auto mb-10 border border-accent/50 p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:border-accent transition-colors"
        >
          <div className="flex flex-col gap-1">
            <span className="font-mono text-accent text-[10px] uppercase tracking-[0.3em]">Free download</span>
            <span className="text-lg font-extrabold tracking-tight">Prop Firm Evaluation Checklist (printable)</span>
            <span className="text-sm text-muted-foreground">Drawdown math, sizing, news, and when to stop, on one page.</span>
          </div>
          <span className="font-mono text-[11px] uppercase tracking-widest text-accent shrink-0">Get it →</span>
        </a>
        <div className="max-w-4xl mx-auto grid gap-6 md:grid-cols-2">
          {LEARN_ARTICLES.map((a) => (
            <a
              key={a.slug}
              href={`/learn/${a.slug}`}
              className="border border-border p-6 flex flex-col gap-3 hover:border-accent transition-colors"
            >
              <span className="font-mono text-accent text-[10px] uppercase tracking-[0.3em]">{a.kicker}</span>
              <h2 className="text-xl font-extrabold tracking-tight">{a.title}</h2>
              <p className="text-sm text-muted-foreground text-pretty">{a.metaDescription}</p>
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                {a.readMinutes} min read
              </span>
            </a>
          ))}
        </div>
        <div className="max-w-4xl mx-auto mt-12 flex flex-wrap gap-3">
          <Link
            to="/mentorship"
            className="px-5 py-3 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors"
          >
            See the Programs
          </Link>
          <Link
            to="/playbook"
            className="px-5 py-3 border border-border font-extrabold text-[11px] uppercase tracking-widest hover:border-accent transition-colors"
          >
            Get the Free Playbook
          </Link>
        </div>
        <p className="max-w-4xl mx-auto mt-12 text-xs text-muted-foreground text-pretty">{LEARN_RISK_DISCLAIMER}</p>
      </section>
    </div>
  );
}
