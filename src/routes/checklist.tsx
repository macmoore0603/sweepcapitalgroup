import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { LearnNav, LEARN_RISK_DISCLAIMER } from "@/components/LearnArticle";

const TITLE = "Free Prop Firm Evaluation Checklist (Printable) | Sweep Capital Group";
const DESCRIPTION =
  "A free, printable pre-session checklist for futures prop firm evaluations: drawdown math, position sizing, news, setup rules, and when to stop. Education, not advice.";
const URL = "https://sweepcapitalgroup.com/checklist";

export const Route = createFileRoute("/checklist")({
  head: () => ({
    meta: [
      { title: TITLE },
      { name: "description", content: DESCRIPTION },
      { property: "og:title", content: TITLE },
      { property: "og:description", content: DESCRIPTION },
      { property: "og:url", content: URL },
    ],
    links: [{ rel: "canonical", href: URL }],
  }),
  component: ChecklistPage,
});

const CHECKLIST: { group: string; items: string[] }[] = [
  {
    group: "Before you buy an evaluation",
    items: [
      "I've read the firm's current rulebook for this exact account size.",
      "I know whether the drawdown is static, intraday trailing, or end-of-day trailing.",
      "I know whether hitting the daily loss limit fails the account or just pauses it.",
      "I know the consistency rule, minimum days, and news/flat-by-close rules.",
      "I can afford to lose the full fee (and any resets) without it affecting my bills.",
      "I've practiced my setup on a simulator with a journal for at least 30 trades.",
    ],
  },
  {
    group: "Before every session",
    items: [
      "My account fails today at $______ (written down, in dollars).",
      "My remaining cushion is $______. My max risk per trade is $______.",
      "My personal daily stop is $______, well inside the firm's limit.",
      "I checked the economic calendar (8:30 / 10:00 / 2:00 ET releases).",
      "I marked the prior-day high/low and overnight high/low.",
      "My trading window today is ______ to ______ ET.",
      "My setup's entry condition and invalidation are written down.",
    ],
  },
  {
    group: "During the session",
    items: [
      "Stop and size are set before entry, every trade.",
      "Under intraday trailing: I know where I'll take partials or move my stop.",
      "Two losing trades = done for the day.",
      "Daily goal hit = done for the day.",
      "No new trade within 5 minutes of a loss.",
    ],
  },
  {
    group: "After the session",
    items: [
      "Every trade is logged: setup, risk, result after fees, R-multiple, screenshot.",
      "I marked whether each trade followed the plan, and named any broken rule.",
      "I recalculated my floor and cushion for tomorrow.",
      "I wrote one thing to do differently next session.",
    ],
  },
];

function checklistText() {
  const lines = ["SWEEP CAPITAL GROUP: PROP FIRM EVALUATION CHECKLIST", ""];
  for (const g of CHECKLIST) {
    lines.push(g.group.toUpperCase());
    for (const i of g.items) lines.push(`[ ] ${i}`);
    lines.push("");
  }
  lines.push(LEARN_RISK_DISCLAIMER);
  lines.push("", "More free guides: https://sweepcapitalgroup.com/learn");
  return lines.join("\n");
}

function utmPayload() {
  if (typeof window === "undefined") return {};
  const p = new URLSearchParams(window.location.search);
  const pick = (k: string) => p.get(k) ?? undefined;
  return {
    utm_source: pick("utm_source"),
    utm_medium: pick("utm_medium"),
    utm_campaign: pick("utm_campaign"),
    utm_term: pick("utm_term"),
    utm_content: pick("utm_content"),
    ref: pick("ref"),
    referrer: document.referrer || undefined,
    landing_page: window.location.href.slice(0, 2048),
  };
}

function ChecklistPage() {
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [unlocked, setUnlocked] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = z.string().trim().email().max(255).safeParse(email);
    if (!parsed.success) {
      toast.error("Enter a valid email");
      return;
    }
    setSending(true);
    try {
      const res = await fetch("/api/public/lead-submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: parsed.data.split("@")[0].slice(0, 100) || "Trader",
          email: parsed.data,
          tier: "Prop Firm Checklist",
          source: "checklist",
          ...utmPayload(),
        }),
      });
      const json = await res.json();
      if (!res.ok || !json?.success) throw new Error();
      setUnlocked(true);
    } catch {
      toast.error("Something went wrong. Try again.");
    } finally {
      setSending(false);
    }
  };

  const download = () => {
    const blob = new Blob([checklistText()], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = window.URL.createObjectURL(blob);
    a.download = "sweep-prop-firm-evaluation-checklist.txt";
    a.click();
  };

  return (
    <div className="min-h-screen bg-background text-foreground font-sans">
      <div className="print:hidden">
        <LearnNav />
      </div>
      <main className="px-6 md:px-10 py-16 md:py-20">
        <div className="max-w-3xl mx-auto flex flex-col gap-8">
          <div className="flex flex-col gap-4">
            <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em] print:hidden">Free download</span>
            <h1 className="text-4xl md:text-6xl font-extrabold tracking-tighter uppercase leading-[0.95]">
              Prop Firm Evaluation Checklist
            </h1>
            <p className="text-muted-foreground text-pretty print:hidden">
              The one-page routine we'd want every newer trader to run before, during, and after each evaluation
              session: drawdown math, sizing, news, and when to stop. Printable. Free.
            </p>
          </div>

          {!unlocked ? (
            <form onSubmit={submit} className="flex flex-col sm:flex-row gap-4 border border-border p-6">
              <input
                required
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                maxLength={255}
                placeholder="you@email.com"
                aria-label="Email address for the free checklist"
                className="flex-1 bg-transparent border-b border-border py-3 focus:outline-none focus:border-accent text-lg placeholder:text-muted-foreground/40"
              />
              <button
                type="submit"
                disabled={sending}
                className="px-8 py-4 bg-foreground text-background font-extrabold uppercase tracking-[0.2em] text-xs hover:bg-accent transition-colors disabled:opacity-50"
              >
                {sending ? "Unlocking…" : "Get the checklist"}
              </button>
            </form>
          ) : (
            <>
              <div className="flex flex-wrap gap-3 print:hidden">
                <button
                  type="button"
                  onClick={() => window.print()}
                  className="px-5 py-3 bg-foreground text-background font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent transition-colors"
                >
                  Print / Save as PDF
                </button>
                <button
                  type="button"
                  onClick={download}
                  className="px-5 py-3 border border-border font-extrabold text-[11px] uppercase tracking-widest hover:border-accent transition-colors"
                >
                  Download (.txt)
                </button>
              </div>
              <div className="flex flex-col gap-8">
                {CHECKLIST.map((g) => (
                  <section key={g.group} className="flex flex-col gap-3">
                    <h2 className="text-xl font-extrabold uppercase tracking-tight">{g.group}</h2>
                    <ul className="flex flex-col gap-2">
                      {g.items.map((i) => (
                        <li key={i} className="flex gap-3 text-sm leading-relaxed">
                          <span className="mt-1 size-3.5 shrink-0 border border-foreground/60" aria-hidden />
                          <span>{i}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
            </>
          )}

          <div className="flex flex-col gap-3 border-t border-border pt-8 print:hidden">
            <p className="text-sm text-muted-foreground">
              Want the reasoning behind each line? Read{" "}
              <a href="/learn/pass-futures-prop-firm-evaluation" className="text-accent underline">
                how to pass a prop firm evaluation
              </a>{" "}
              and{" "}
              <a href="/learn/trailing-drawdown-explained" className="text-accent underline">
                trailing drawdown explained
              </a>
              .
            </p>
            <div className="flex flex-wrap gap-3">
              <Link
                to="/mentorship"
                className="px-5 py-3 border border-accent text-accent font-extrabold text-[11px] uppercase tracking-widest hover:bg-accent hover:text-background transition-colors"
              >
                See the Programs
              </Link>
              <Link
                to="/call"
                className="px-5 py-3 border border-border font-extrabold text-[11px] uppercase tracking-widest hover:border-accent transition-colors"
              >
                Book a free 15-min call
              </Link>
            </div>
          </div>
          <p className="text-xs text-muted-foreground text-pretty">{LEARN_RISK_DISCLAIMER}</p>
        </div>
      </main>
    </div>
  );
}
