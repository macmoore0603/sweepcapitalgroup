import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { getReferralStats } from "@/lib/referral.functions";
import logoAsset from "../assets/scg-logo.png.asset.json";
const logo = logoAsset.url;

export const Route = createFileRoute("/refer")({
  component: ReferPage,
  head: () => ({
    meta: [
      { title: "Refer a Trader | Sweep Capital Group" },
      {
        name: "description",
        content:
          "Share the Session Sweep framework with your circle. Look up your personal referral link and track clicks and conversions from your Sweep Capital Group account email.",
      },
      { property: "og:title", content: "Refer a Trader | Sweep Capital Group" },
      {
        property: "og:description",
        content:
          "Get your personal referral link and track clicks, sales, and credit from traders you send our way.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: [{ rel: "canonical", href: "https://sweepcapitalgroup.com/refer" }],
  }),
});

type Stats = Awaited<ReturnType<typeof getReferralStats>>;

const STEPS = [
  {
    n: "01",
    title: "Get your link",
    body: "Enter the email you used to apply or download the playbook. We hand back a link that is unique to you.",
  },
  {
    n: "02",
    title: "Send it to one trader",
    body: "Group chat, DM, or your story. The people who trade the same sweep and 5–15 gap as you sharpen your own reviews.",
  },
  {
    n: "03",
    title: "Get credit when they join",
    body: "Every click and enrollment is attributed to your link automatically. We email you the moment one converts.",
  },
];

function ReferPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setStats(null);
    try {
      const res = await getReferralStats({ data: { email } });
      setStats(res);
      if (!res.found) toast.error("No account found for that email yet.");
    } catch {
      toast.error("Couldn't look that up. Check the email and try again.");
    } finally {
      setLoading(false);
    }
  };

  const copy = async (link: string) => {
    try {
      await navigator.clipboard.writeText(link);
      toast.success("Link copied");
    } catch {
      toast.error("Copy failed — select the link manually");
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground font-sans selection:bg-accent selection:text-background">
      <nav className="flex items-center justify-between px-6 md:px-10 py-5 border-b border-border">
        <Link to="/" className="flex items-center gap-3">
          <img
            src={logo}
            alt="Sweep Capital Group logo"
            width={32}
            height={32}
            className="h-8 w-8 object-contain"
          />
          <span className="font-extrabold tracking-tighter text-xl uppercase">Sweep</span>
        </Link>
        <Link
          to="/mentorship"
          className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
        >
          Mentorship
        </Link>
      </nav>

      <main className="px-6 md:px-10 py-20 max-w-3xl mx-auto space-y-16">
        <header className="space-y-6">
          <span className="font-mono text-[10px] uppercase tracking-widest text-accent">
            Referral Program
          </span>
          <h1 className="text-4xl md:text-6xl font-extrabold tracking-tighter uppercase leading-[0.95]">
            Refer a trader
          </h1>
          <p className="text-lg text-muted-foreground leading-relaxed">
            Every trader you bring in runs the same framework you do — session sweep, the 5–15 gap,
            and Power of 3. Pull up your personal link and see exactly what it's done.
          </p>

          <form onSubmit={submit} className="flex flex-col sm:flex-row gap-4 pt-2">
            <input
              required
              type="email"
              value={email}
              onChange={(ev) => setEmail(ev.target.value)}
              maxLength={255}
              placeholder="you@email.com"
              aria-label="Email address used on your Sweep Capital Group account"
              className="flex-1 bg-transparent border-b border-border py-4 focus:outline-none focus:border-accent text-lg placeholder:text-muted-foreground/40"
            />
            <button
              type="submit"
              disabled={loading}
              className="px-8 py-4 bg-foreground text-background font-extrabold uppercase tracking-[0.2em] text-xs hover:bg-accent transition-colors duration-500 disabled:opacity-50"
            >
              {loading ? "Looking…" : "Get my link"}
            </button>
          </form>
        </header>

        {stats?.found ? (
          <section className="border border-accent/40 bg-accent/5 p-6 md:p-8 space-y-6">
            <div className="space-y-2">
              <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                Your link
              </h2>
              <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                <code className="text-accent break-all text-sm">{stats.link}</code>
                <button
                  type="button"
                  onClick={() => copy(stats.link)}
                  className="shrink-0 px-5 py-2 border border-border font-extrabold uppercase tracking-[0.2em] text-[10px] hover:border-accent hover:text-accent transition-colors"
                >
                  Copy
                </button>
              </div>
            </div>
            <dl className="grid grid-cols-3 gap-4 border-t border-border pt-6">
              {[
                { label: "Clicks", value: String(stats.clicks) },
                { label: "Enrollments", value: String(stats.sales) },
                {
                  label: "Referred volume",
                  value: `$${stats.revenue.toLocaleString("en-US", { maximumFractionDigits: 0 })}`,
                },
              ].map((s) => (
                <div key={s.label} className="space-y-1">
                  <dd className="text-2xl md:text-3xl font-extrabold tracking-tighter">{s.value}</dd>
                  <dt className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
                    {s.label}
                  </dt>
                </div>
              ))}
            </dl>
          </section>
        ) : null}

        {stats && !stats.found ? (
          <section className="border-t border-border pt-8 space-y-4">
            <p className="text-muted-foreground leading-relaxed">
              We don't have that email yet. Grab the free playbook and your referral link is created
              automatically.
            </p>
            <Link
              to="/playbook"
              className="inline-block px-8 py-4 border border-border font-extrabold uppercase tracking-[0.2em] text-xs hover:border-accent hover:text-accent transition-colors duration-500"
            >
              Get the free playbook
            </Link>
          </section>
        ) : null}

        <section className="space-y-10">
          <h2 className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            How it works
          </h2>
          {STEPS.map((s) => (
            <article key={s.n} className="border-l-2 border-accent/50 pl-6 space-y-2">
              <span className="font-mono text-[10px] text-accent">{s.n}</span>
              <h3 className="text-2xl font-extrabold tracking-tighter uppercase">{s.title}</h3>
              <p className="text-muted-foreground leading-relaxed">{s.body}</p>
            </article>
          ))}
        </section>

        <p className="text-xs text-muted-foreground/60 leading-relaxed">
          Educational content only. Trading involves substantial risk of loss and is not suitable
          for everyone.
        </p>
      </main>
    </div>
  );
}
