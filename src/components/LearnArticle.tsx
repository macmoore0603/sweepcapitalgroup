import { Link } from "@tanstack/react-router";
import logoAsset from "../assets/scg-logo.png.asset.json";
import { LEARN_ARTICLES, LEARN_BASE_URL, type LearnArticle as Article } from "@/lib/learn-articles";

const logo = logoAsset.url;

export const LEARN_RISK_DISCLAIMER =
  "Risk disclaimer: Trading futures involves substantial risk of loss and is not suitable for every investor. You can lose more than your initial deposit. This article is general education, not financial advice or a recommendation to buy or sell any contract. Past performance, real or hypothetical, does not guarantee future results.";

/** Builds the TanStack head() payload for a learn article: title, meta, canonical, Article JSON-LD. */
export function learnHead(article: Article) {
  const url = `${LEARN_BASE_URL}/learn/${article.slug}`;
  return {
    meta: [
      { title: article.metaTitle },
      { name: "description", content: article.metaDescription },
      { property: "og:title", content: article.metaTitle },
      { property: "og:description", content: article.metaDescription },
      { property: "og:type", content: "article" },
      { property: "og:url", content: url },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "twitter:title", content: article.metaTitle },
      { name: "twitter:description", content: article.metaDescription },
    ],
    links: [{ rel: "canonical", href: url }],
    scripts: [
      {
        type: "application/ld+json",
        children: JSON.stringify({
          "@context": "https://schema.org",
          "@type": "Article",
          headline: article.title,
          description: article.metaDescription,
          datePublished: article.published,
          dateModified: article.published,
          author: { "@type": "Person", name: "Mac Moore" },
          publisher: {
            "@type": "Organization",
            name: "Sweep Capital Group",
            logo: { "@type": "ImageObject", url: `${LEARN_BASE_URL}/og-card.jpg` },
          },
          mainEntityOfPage: url,
        }),
      },
      ...(article.faq.length
        ? [
            {
              type: "application/ld+json",
              children: JSON.stringify({
                "@context": "https://schema.org",
                "@type": "FAQPage",
                mainEntity: article.faq.map((f) => ({
                  "@type": "Question",
                  name: f.q,
                  acceptedAnswer: { "@type": "Answer", text: f.a },
                })),
              }),
            },
          ]
        : []),
    ],
  };
}

export function LearnNav() {
  return (
    <nav className="sticky top-0 z-50 flex items-center justify-between px-6 md:px-10 py-5 bg-background/80 backdrop-blur-md border-b border-border">
      <Link to="/" className="flex items-center gap-3">
        <img src={logo} alt="Sweep Capital Group logo" width={32} height={32} className="h-8 w-8 object-contain" />
        <span className="font-extrabold tracking-tighter text-xl uppercase">Sweep</span>
        <span className="hidden sm:inline font-mono text-[10px] text-accent border border-accent/40 px-1.5 py-0.5">
          CAPITAL GROUP
        </span>
      </Link>
      <div className="hidden md:flex items-center gap-8 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
        <Link to="/" className="hover:text-foreground transition-colors">Home</Link>
        <Link to="/learn" className="hover:text-foreground transition-colors">Learn</Link>
        <Link to="/playbook" className="hover:text-foreground transition-colors">Free Playbook</Link>
        <Link to="/mentorship" className="hover:text-foreground transition-colors">Mentorship</Link>
      </div>
      <Link
        to="/mentorship"
        className="px-5 py-2.5 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors"
      >
        See the Programs
      </Link>
    </nav>
  );
}

function ProgramsCta() {
  return (
    <aside className="my-12 border border-accent/40 p-6 md:p-8 flex flex-col gap-4">
      <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">Want the full framework?</span>
      <p className="text-foreground text-lg font-semibold">
        The Course ($1,000) and Course + Coaching ($1,500) teach Session Sweep, the 5-15 Gap, and Power of 3 as a
        written, reviewable process. One-time payment, no subscription.
      </p>
      <div className="flex flex-wrap gap-3">
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
      <p className="text-xs text-muted-foreground">No income or results are promised. Education, not advice.</p>
    </aside>
  );
}

export function LearnArticlePage({ article }: { article: Article }) {
  const related = LEARN_ARTICLES.filter((a) => a.slug !== article.slug);
  const ctaAfter = Math.min(1, article.sections.length - 1);
  return (
    <div className="min-h-screen bg-background text-foreground font-sans">
      <LearnNav />
      <article className="px-6 md:px-10 pt-16 md:pt-24 pb-20">
        <div className="max-w-3xl mx-auto">
          <Link to="/learn" className="font-mono text-accent text-[11px] uppercase tracking-[0.3em] hover:underline">
            ← Learn · {article.kicker}
          </Link>
          <h1 className="mt-4 text-4xl md:text-6xl font-extrabold tracking-tighter leading-[0.95]">{article.title}</h1>
          <p className="mt-6 text-lg text-muted-foreground text-pretty">{article.intro}</p>
          <p className="mt-4 font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            By Mac Moore · Sweep Capital Group · {article.readMinutes} min read
          </p>

          {article.sections.map((s, i) => (
            <section key={s.h2} className="mt-12">
              <h2 className="text-2xl md:text-3xl font-extrabold tracking-tight">{s.h2}</h2>
              {s.paragraphs.map((p, j) => (
                <p key={j} className="mt-4 text-base md:text-lg text-muted-foreground text-pretty leading-relaxed">
                  {p}
                </p>
              ))}
              {s.bullets && (
                <ul className="mt-4 flex flex-col gap-2 list-disc pl-6 text-base md:text-lg text-muted-foreground">
                  {s.bullets.map((b, j) => (
                    <li key={j}>{b}</li>
                  ))}
                </ul>
              )}
              {i === ctaAfter && <ProgramsCta />}
            </section>
          ))}

          {article.faq.length > 0 && (
            <section className="mt-16">
              <h2 className="text-2xl md:text-3xl font-extrabold tracking-tight">Frequently asked questions</h2>
              <div className="mt-6 flex flex-col gap-6">
                {article.faq.map((f) => (
                  <div key={f.q}>
                    <h3 className="text-lg font-semibold text-foreground">{f.q}</h3>
                    <p className="mt-2 text-muted-foreground text-pretty leading-relaxed">{f.a}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          <ProgramsCta />

          <section className="mt-12 border-t border-border pt-8">
            <h2 className="font-mono text-[11px] uppercase tracking-[0.3em] text-accent">Keep reading</h2>
            <ul className="mt-4 flex flex-col gap-3">
              {related.map((r) => (
                <li key={r.slug}>
                  <a href={`/learn/${r.slug}`} className="text-foreground font-semibold hover:text-accent transition-colors">
                    {r.title}
                  </a>
                </li>
              ))}
            </ul>
          </section>

          <p className="mt-12 text-xs text-muted-foreground text-pretty">{LEARN_RISK_DISCLAIMER}</p>
        </div>
      </article>
    </div>
  );
}
