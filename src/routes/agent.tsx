import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useServerFn } from "@tanstack/react-start";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";
import {
  listAccounts,
  upsertAccount,
  deleteAccount,
} from "@/lib/social/accounts.functions";
import {
  listPosts,
  upsertPost,
  deletePost,
  draftForPlatforms,
  autofillDay,
  quotaToday,
} from "@/lib/social/posts.functions";
import { getOAuthStartUrl } from "@/lib/social/oauth.functions";
import { PLATFORMS, PLATFORM_LABEL, MIN_POSTS_PER_DAY, type Platform } from "@/lib/social/types";

export const Route = createFileRoute("/agent")({
  head: () => ({
    meta: [
      { title: "Social Agent — Sweep Capital Group" },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: AgentPage,
});

function AgentPage() {
  const navigate = useNavigate();
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) => {
      if (!session) navigate({ to: "/login" });
      else setAuthed(true);
    });
    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) navigate({ to: "/login" });
      else setAuthed(true);
    });
    return () => sub.subscription.unsubscribe();
  }, [navigate]);

  useEffect(() => {
    const url = new URL(window.location.href);
    const oauth = url.searchParams.get("oauth");
    if (!oauth) return;
    if (oauth.endsWith("_connected")) {
      toast.success(`${oauth.replace("_connected", "")} account connected`);
    } else if (oauth.includes("_error:")) {
      const [plat, msg] = oauth.split("_error:");
      toast.error(`${plat}: ${msg}`);
    }
    url.searchParams.delete("oauth");
    window.history.replaceState({}, "", url.toString());
  }, []);

  if (!authed) return null;
  return <Dashboard />;
}

function Dashboard() {
  const qc = useQueryClient();
  const fetchAccounts = useServerFn(listAccounts);
  const fetchPosts = useServerFn(listPosts);
  const fetchQuota = useServerFn(quotaToday);

  const accountsQuery = useQuery({
    queryKey: ["social", "accounts"],
    queryFn: () => fetchAccounts(),
  });

  const quotaQuery = useQuery({
    queryKey: ["social", "quota"],
    queryFn: () => fetchQuota(),
    refetchInterval: 60_000,
  });

  const today = new Date();
  const weekEnd = new Date(today);
  weekEnd.setUTCDate(weekEnd.getUTCDate() + 7);

  const postsQuery = useQuery({
    queryKey: ["social", "posts"],
    queryFn: () =>
      fetchPosts({
        data: { fromISO: today.toISOString(), toISO: weekEnd.toISOString() },
      }),
  });

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border px-6 md:px-10 py-5 flex items-center justify-between">
        <Link to="/" className="font-extrabold tracking-tighter text-xl uppercase">
          Sweep · Social Agent
        </Link>
        <span className="font-mono text-[11px] text-muted-foreground uppercase tracking-[0.3em]">
          ≥{MIN_POSTS_PER_DAY} posts / day enforced
        </span>
      </header>

      <main className="px-6 md:px-10 py-10 space-y-12 max-w-6xl mx-auto">
        <QuotaPanel quota={quotaQuery.data?.accounts ?? []} loading={quotaQuery.isLoading} />
        <AccountsPanel
          accounts={accountsQuery.data?.accounts ?? []}
          loading={accountsQuery.isLoading}
          onChange={() => {
            qc.invalidateQueries({ queryKey: ["social"] });
          }}
        />
        <ComposerPanel
          accounts={accountsQuery.data?.accounts ?? []}
          onScheduled={() => qc.invalidateQueries({ queryKey: ["social"] })}
        />
        <QueuePanel
          posts={postsQuery.data?.posts ?? []}
          accounts={accountsQuery.data?.accounts ?? []}
          loading={postsQuery.isLoading}
          onChange={() => qc.invalidateQueries({ queryKey: ["social"] })}
        />
      </main>
    </div>
  );
}

type QuotaRow = {
  id: string;
  platform: string;
  handle: string;
  required: number;
  scheduled: number;
  meeting: boolean;
};

function QuotaPanel({ quota, loading }: { quota: QuotaRow[]; loading: boolean }) {
  const fillDay = useServerFn(autofillDay);
  const qc = useQueryClient();
  const fill = useMutation({
    mutationFn: (accountId: string) =>
      fillDay({
        data: { accountId, date: new Date().toISOString().slice(0, 10) },
      }),
    onSuccess: (r) => {
      toast.success(
        r.alreadyMet ? "Quota already met for today" : `Created ${r.created} scheduled slot(s)`,
      );
      qc.invalidateQueries({ queryKey: ["social"] });
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Autofill failed"),
  });

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">Today's quota</h2>
      {loading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {!loading && quota.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No active accounts yet. Add one below — every account auto-enforces ≥{MIN_POSTS_PER_DAY}{" "}
          posts per day.
        </p>
      )}
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {quota.map((q) => (
          <div
            key={q.id}
            className={`rounded-md border p-4 space-y-2 ${
              q.meeting ? "border-border" : "border-destructive"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                {q.platform}
              </span>
              <span className={`text-xs ${q.meeting ? "text-accent" : "text-destructive"}`}>
                {q.scheduled} / {q.required}
              </span>
            </div>
            <div className="text-sm font-medium truncate">@{q.handle}</div>
            {!q.meeting && (
              <button
                disabled={fill.isPending}
                onClick={() => fill.mutate(q.id)}
                className="text-xs underline text-foreground hover:opacity-80"
              >
                Autofill today
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

type AccountRow = {
  id: string;
  platform: string;
  handle: string;
  active: boolean;
  min_posts_per_day: number;
};

function AccountsPanel({
  accounts,
  loading,
  onChange,
}: {
  accounts: AccountRow[];
  loading: boolean;
  onChange: () => void;
}) {
  const save = useServerFn(upsertAccount);
  const remove = useServerFn(deleteAccount);
  const startOAuth = useServerFn(getOAuthStartUrl);
  const [platform, setPlatform] = useState<Platform>("instagram");
  const [handle, setHandle] = useState("");
  const [minPerDay, setMinPerDay] = useState(MIN_POSTS_PER_DAY);

  const connectIG = useMutation({
    mutationFn: () => startOAuth({ data: { platform: "instagram" } }),
    onSuccess: (r) => {
      window.location.href = r.url;
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "OAuth failed"),
  });

  const create = useMutation({
    mutationFn: () =>
      save({
        data: { platform, handle: handle.trim(), min_posts_per_day: minPerDay },
      }),
    onSuccess: () => {
      toast.success("Account added");
      setHandle("");
      onChange();
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Failed"),
  });

  const del = useMutation({
    mutationFn: (id: string) => remove({ data: { id } }),
    onSuccess: () => {
      toast.success("Account removed");
      onChange();
    },
  });

  return (
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">Connected accounts</h2>
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => connectIG.mutate()}
          disabled={connectIG.isPending}
          className="bg-foreground text-background px-4 py-2 rounded text-sm font-medium disabled:opacity-50"
        >
          {connectIG.isPending ? "Redirecting…" : "Connect Instagram via Meta"}
        </button>
        <span className="text-xs text-muted-foreground self-center">
          Other platforms light up once their API credentials are added.
        </span>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!handle.trim()) return;
          if (minPerDay < MIN_POSTS_PER_DAY) {
            toast.error(`Minimum is ${MIN_POSTS_PER_DAY} posts per day`);
            return;
          }
          create.mutate();
        }}
        className="grid grid-cols-1 md:grid-cols-[160px_1fr_120px_auto] gap-2 items-end"
      >
        <label className="space-y-1">
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            Platform
          </span>
          <select
            value={platform}
            onChange={(e) => setPlatform(e.target.value as Platform)}
            className="w-full bg-background border border-border rounded px-2 py-2 text-sm"
          >
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {PLATFORM_LABEL[p]}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            Handle
          </span>
          <input
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
            placeholder="sweepcapitalgroup"
            className="w-full bg-background border border-border rounded px-2 py-2 text-sm"
          />
        </label>
        <label className="space-y-1">
          <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
            Min/day
          </span>
          <input
            type="number"
            min={MIN_POSTS_PER_DAY}
            max={20}
            value={minPerDay}
            onChange={(e) => setMinPerDay(parseInt(e.target.value || "3", 10))}
            className="w-full bg-background border border-border rounded px-2 py-2 text-sm"
          />
        </label>
        <button
          type="submit"
          disabled={create.isPending}
          className="bg-primary text-primary-foreground px-4 py-2 rounded text-sm font-medium"
        >
          Add account
        </button>
      </form>

      {loading && <p className="text-sm text-muted-foreground">Loading…</p>}
      <ul className="divide-y divide-border border border-border rounded">
        {accounts.map((a) => (
          <li key={a.id} className="px-4 py-3 flex items-center justify-between text-sm">
            <span>
              <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground mr-2">
                {a.platform}
              </span>
              @{a.handle} · min {a.min_posts_per_day}/day
            </span>
            <button
              onClick={() => del.mutate(a.id)}
              className="text-xs text-destructive hover:underline"
            >
              Remove
            </button>
          </li>
        ))}
        {!loading && accounts.length === 0 && (
          <li className="px-4 py-6 text-sm text-muted-foreground text-center">
            No accounts yet.
          </li>
        )}
      </ul>
      <p className="text-xs text-muted-foreground">
        OAuth publishing turns on per platform once you add the platform's API credentials.
        Until then, drafts can still be generated and scheduled, and the scheduler will mark
        publish attempts as failed with a clear "credentials not configured" message.
      </p>
    </section>
  );
}

function ComposerPanel({
  accounts,
  onScheduled,
}: {
  accounts: AccountRow[];
  onScheduled: () => void;
}) {
  const draft = useServerFn(draftForPlatforms);
  const saveP = useServerFn(upsertPost);
  const [goal, setGoal] = useState("");
  const [selected, setSelected] = useState<Platform[]>(["instagram", "x", "linkedin"]);
  const [drafts, setDrafts] = useState<
    Array<{ platform: Platform; body: string; ok: boolean; violations: string[]; warnings: string[] }>
  >([]);
  const generate = useMutation({
    mutationFn: () => draft({ data: { goal, platforms: selected } }),
    onSuccess: (r) => setDrafts(r.drafts),
    onError: (e) => toast.error(e instanceof Error ? e.message : "Draft failed"),
  });

  const schedule = useMutation({
    mutationFn: async ({ platform, body }: { platform: Platform; body: string }) => {
      const acc = accounts.find((a) => a.platform === platform);
      if (!acc) throw new Error(`No connected ${platform} account`);
      const when = new Date();
      when.setMinutes(when.getMinutes() + 5);
      return saveP({
        data: {
          account_id: acc.id,
          body,
          scheduled_for: when.toISOString(),
          status: "scheduled",
        },
      });
    },
    onSuccess: () => {
      toast.success("Scheduled");
      onScheduled();
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : "Schedule failed"),
  });

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">Compose</h2>
      <textarea
        value={goal}
        onChange={(e) => setGoal(e.target.value)}
        placeholder="What's the post about? e.g. 'Lesson on risk discipline using a recent EUR/USD setup'"
        className="w-full min-h-[100px] bg-background border border-border rounded p-3 text-sm"
      />
      <div className="flex flex-wrap gap-2 items-center">
        {PLATFORMS.map((p) => {
          const on = selected.includes(p);
          return (
            <button
              key={p}
              type="button"
              onClick={() =>
                setSelected((s) => (on ? s.filter((x) => x !== p) : [...s, p]))
              }
              className={`px-3 py-1.5 rounded border text-xs font-mono uppercase tracking-widest ${
                on
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-background text-muted-foreground border-border"
              }`}
            >
              {PLATFORM_LABEL[p]}
            </button>
          );
        })}
        <button
          onClick={() => generate.mutate()}
          disabled={!goal.trim() || selected.length === 0 || generate.isPending}
          className="ml-auto bg-accent text-accent-foreground px-4 py-2 rounded text-sm font-medium disabled:opacity-50"
        >
          {generate.isPending ? "Drafting…" : "Generate drafts"}
        </button>
      </div>

      <div className="space-y-3">
        {drafts.map((d, i) => (
          <div key={i} className="border border-border rounded p-4 space-y-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
                {PLATFORM_LABEL[d.platform]}
              </span>
              {!d.ok && (
                <span className="text-xs text-destructive">
                  Guardrail violations: {d.violations.join("; ")}
                </span>
              )}
            </div>
            <textarea
              value={d.body}
              onChange={(e) =>
                setDrafts((ds) =>
                  ds.map((x, idx) => (idx === i ? { ...x, body: e.target.value } : x)),
                )
              }
              className="w-full min-h-[140px] bg-background border border-border rounded p-2 text-sm font-mono"
            />
            {d.warnings.length > 0 && (
              <p className="text-xs text-muted-foreground">{d.warnings.join("; ")}</p>
            )}
            <div className="flex justify-end">
              <button
                onClick={() => schedule.mutate({ platform: d.platform, body: d.body })}
                disabled={!d.ok || schedule.isPending}
                className="text-xs underline disabled:opacity-50"
              >
                Schedule for +5 min
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

type PostRow = {
  id: string;
  account_id: string;
  status: string;
  scheduled_for: string | null;
  body: string;
  error: string | null;
  platform_post_url: string | null;
};

function QueuePanel({
  posts,
  accounts,
  loading,
  onChange,
}: {
  posts: PostRow[];
  accounts: AccountRow[];
  loading: boolean;
  onChange: () => void;
}) {
  const del = useServerFn(deletePost);
  const remove = useMutation({
    mutationFn: (id: string) => del({ data: { id } }),
    onSuccess: onChange,
  });
  const acctById = Object.fromEntries(accounts.map((a) => [a.id, a]));

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">Queue (next 7 days)</h2>
      {loading && <p className="text-sm text-muted-foreground">Loading…</p>}
      <ul className="divide-y divide-border border border-border rounded">
        {posts.map((p) => {
          const acc = acctById[p.account_id];
          return (
            <li key={p.id} className="px-4 py-3 text-sm space-y-1">
              <div className="flex items-center justify-between">
                <span>
                  <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mr-2">
                    {acc?.platform ?? "?"} · {p.status}
                  </span>
                  {p.scheduled_for
                    ? new Date(p.scheduled_for).toLocaleString()
                    : "unscheduled"}
                </span>
                <button
                  onClick={() => remove.mutate(p.id)}
                  className="text-xs text-destructive hover:underline"
                >
                  Delete
                </button>
              </div>
              {p.body && <p className="text-xs text-muted-foreground line-clamp-2">{p.body}</p>}
              {p.error && <p className="text-xs text-destructive">{p.error}</p>}
            </li>
          );
        })}
        {!loading && posts.length === 0 && (
          <li className="px-4 py-6 text-sm text-muted-foreground text-center">
            No posts scheduled.
          </li>
        )}
      </ul>
    </section>
  );
}
