import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";
import type { Database } from "@/integrations/supabase/types";

type Lead = Database["public"]["Tables"]["leads"]["Row"];
type LeadStatus = Database["public"]["Enums"]["lead_status"];

const STATUSES: LeadStatus[] = ["new", "contacted", "qualified", "closed", "rejected"];

const STATUS_LABEL: Record<LeadStatus, string> = {
  new: "New",
  contacted: "Contacted",
  qualified: "Qualified",
  closed: "Closed",
  rejected: "Rejected",
};

export const Route = createFileRoute("/admin")({
  head: () => ({
    meta: [
      { title: "Lead Dashboard — Lexus Nexus Capital Group" },
      { name: "description", content: "Internal lead management dashboard." },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: AdminPage,
});

function AdminPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [authChecked, setAuthChecked] = useState(false);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
  const [statusFilter, setStatusFilter] = useState<LeadStatus | "all">("all");
  const [tierFilter, setTierFilter] = useState<string>("all");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [search, setSearch] = useState<string>("");

  // Auth + role check (client-side; RLS enforces server-side)
  useEffect(() => {
    let active = true;

    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) => {
      if (!active) return;
      if (!session) {
        navigate({ to: "/login" });
        return;
      }
      setUserEmail(session.user.email ?? null);
      void checkRole(session.user.id);
    });

    const checkRole = async (uid: string) => {
      const { data, error } = await supabase
        .from("user_roles")
        .select("role")
        .eq("user_id", uid)
        .eq("role", "admin")
        .maybeSingle();
      if (!active) return;
      if (error) {
        setIsAdmin(false);
      } else {
        setIsAdmin(!!data);
      }
      setAuthChecked(true);
    };

    void (async () => {
      const { data } = await supabase.auth.getSession();
      if (!active) return;
      if (!data.session) {
        navigate({ to: "/login" });
        return;
      }
      setUserEmail(data.session.user.email ?? null);
      await checkRole(data.session.user.id);
    })();

    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
  }, [navigate]);

  const leadsQuery = useQuery({
    queryKey: ["leads"],
    enabled: isAdmin === true,
    queryFn: async (): Promise<Lead[]> => {
      const { data, error } = await supabase
        .from("leads")
        .select("*")
        .order("created_at", { ascending: false });
      if (error) throw error;
      return data ?? [];
    },
  });

  const updateLead = useMutation({
    mutationFn: async (input: {
      id: string;
      patch: Partial<Pick<Lead, "status" | "notes" | "scheduled_at" | "confirmation_sent_at">>;
    }) => {
      const { error } = await supabase.from("leads").update(input.patch).eq("id", input.id);
      if (error) throw error;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const deleteLead = useMutation({
    mutationFn: async (id: string) => {
      const { error } = await supabase.from("leads").delete().eq("id", id);
      if (error) throw error;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["leads"] });
      toast.success("Lead deleted.");
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const leads = leadsQuery.data ?? [];

  const tiers = useMemo(() => {
    const set = new Set<string>();
    for (const l of leads) {
      const t = (l.capital_size ?? "").trim();
      if (t) set.add(t);
    }
    return Array.from(set).sort();
  }, [leads]);

  const filtered = useMemo(() => {
    const fromTs = dateFrom ? new Date(dateFrom + "T00:00:00").getTime() : null;
    const toTs = dateTo ? new Date(dateTo + "T23:59:59.999").getTime() : null;
    const q = search.trim().toLowerCase();
    return leads.filter((l) => {
      if (statusFilter !== "all" && l.status !== statusFilter) return false;
      if (tierFilter !== "all" && (l.capital_size ?? "") !== tierFilter) return false;
      const created = new Date(l.created_at).getTime();
      if (fromTs !== null && created < fromTs) return false;
      if (toTs !== null && created > toTs) return false;
      if (q) {
        const hay = `${l.full_name} ${l.email} ${l.notes ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [leads, statusFilter, tierFilter, dateFrom, dateTo, search]);

  const counts = useMemo(() => {
    const c: Record<LeadStatus, number> = { new: 0, contacted: 0, qualified: 0, closed: 0, rejected: 0 };
    for (const l of leads) c[l.status]++;
    return c;
  }, [leads]);

  const handleExportCsv = () => {
    if (filtered.length === 0) {
      toast.error("No leads to export.");
      return;
    }
    const headers = [
      "id", "created_at", "full_name", "email", "tier", "status",
      "scheduled_at", "confirmation_sent_at",
      "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
      "referrer", "landing_page", "notes",
    ];
    const esc = (v: unknown) => {
      if (v === null || v === undefined) return "";
      const s = String(v).replace(/\r?\n/g, " ").replace(/"/g, '""');
      return /[",]/.test(s) ? `"${s}"` : s;
    };
    const rows = filtered.map((l) => {
      const x = l as unknown as Record<string, unknown>;
      return [
        l.id, l.created_at, l.full_name, l.email, l.capital_size, l.status,
        l.scheduled_at, l.confirmation_sent_at,
        x.utm_source, x.utm_medium, x.utm_campaign, x.utm_term, x.utm_content,
        x.referrer, x.landing_page, l.notes,
      ].map(esc).join(",");
    });
    const csv = "\uFEFF" + [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `leads-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success(`Exported ${filtered.length} lead${filtered.length === 1 ? "" : "s"}.`);
  };

  const clearFilters = () => {
    setStatusFilter("all");
    setTierFilter("all");
    setDateFrom("");
    setDateTo("");
    setSearch("");
  };

  const hasActiveFilters =
    statusFilter !== "all" || tierFilter !== "all" || !!dateFrom || !!dateTo || !!search;

  const handleSignOut = async () => {
    await supabase.auth.signOut();
    navigate({ to: "/login" });
  };

  if (!authChecked) {
    return <FullScreenMessage>Loading…</FullScreenMessage>;
  }

  if (isAdmin === false) {
    return (
      <FullScreenMessage>
        <div className="space-y-4 text-center">
          <h1 className="text-2xl font-extrabold uppercase tracking-tighter">Access denied</h1>
          <p className="text-sm text-muted-foreground max-w-sm">
            Your account does not have administrator access. Contact the dashboard owner.
          </p>
          <button
            onClick={handleSignOut}
            className="font-mono text-[11px] uppercase tracking-widest text-accent hover:text-foreground"
          >
            Sign out
          </button>
        </div>
      </FullScreenMessage>
    );
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="px-6 md:px-10 py-5 border-b border-border flex items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Link to="/" className="font-extrabold tracking-tighter text-lg uppercase">
            Lexus Nexus
          </Link>
          <span className="font-mono text-[10px] text-accent border border-accent/40 px-1.5 py-0.5 uppercase tracking-widest">
            Lead Dashboard
          </span>
        </div>
        <div className="flex items-center gap-4">
          {userEmail && (
            <span className="hidden sm:inline font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
              {userEmail}
            </span>
          )}
          <button
            onClick={handleSignOut}
            className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground hover:text-foreground"
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="px-6 md:px-10 py-10 md:py-14 max-w-7xl mx-auto space-y-10">
        <div className="space-y-2">
          <h1 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase">Applications</h1>
          <p className="text-sm text-muted-foreground font-mono uppercase tracking-widest">
            {leads.length} total · review and update status
          </p>
        </div>

        {/* Stat tiles + filter */}
        <div className="grid grid-cols-2 md:grid-cols-6 gap-px bg-border">
          <FilterTile label="All" value={leads.length} active={statusFilter === "all"} onClick={() => setStatusFilter("all")} />
          {STATUSES.map((s) => (
            <FilterTile
              key={s}
              label={STATUS_LABEL[s]}
              value={counts[s]}
              active={statusFilter === s}
              onClick={() => setStatusFilter(s)}
            />
          ))}
        </div>

        {/* Filter toolbar */}
        <div className="border border-border bg-background p-4 md:p-5 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <label className="flex flex-col gap-1.5">
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Tier</span>
              <select
                value={tierFilter}
                onChange={(e) => setTierFilter(e.target.value)}
                className="bg-background border border-border px-3 py-2 text-sm focus:outline-none focus:border-accent"
              >
                <option value="all">All tiers</option>
                {tiers.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">From</span>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                max={dateTo || undefined}
                className="bg-background border border-border px-3 py-2 text-sm font-mono focus:outline-none focus:border-accent"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">To</span>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                min={dateFrom || undefined}
                className="bg-background border border-border px-3 py-2 text-sm font-mono focus:outline-none focus:border-accent"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Search</span>
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Name, email, notes…"
                className="bg-background border border-border px-3 py-2 text-sm focus:outline-none focus:border-accent"
              />
            </label>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
            <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
              Showing {filtered.length} of {leads.length}
              {hasActiveFilters ? " · filtered" : ""}
            </div>
            <div className="flex items-center gap-2">
              {hasActiveFilters && (
                <button
                  onClick={clearFilters}
                  className="font-mono text-[10px] uppercase tracking-widest px-3 py-2 border border-border hover:bg-white/5"
                >
                  Clear filters
                </button>
              )}
              <button
                onClick={handleExportCsv}
                disabled={filtered.length === 0}
                className="font-mono text-[10px] uppercase tracking-widest px-4 py-2 bg-foreground text-background hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Export CSV ({filtered.length})
              </button>
            </div>
          </div>
        </div>

        {leadsQuery.isLoading ? (
          <div className="py-16 text-center text-muted-foreground font-mono text-xs uppercase tracking-widest">
            Loading leads…
          </div>
        ) : filtered.length === 0 ? (
          <div className="py-16 text-center text-muted-foreground font-mono text-xs uppercase tracking-widest border border-border">
            No leads match the current filters.
          </div>
        ) : (
          <div className="space-y-px bg-border">
            {filtered.map((lead) => (
              <LeadRow
                key={lead.id}
                lead={lead}
                onStatusChange={(status) => updateLead.mutate({ id: lead.id, patch: { status } })}
                onNotesChange={(notes) => updateLead.mutate({ id: lead.id, patch: { notes } })}
                onScheduleChange={(scheduled_at) =>
                  updateLead.mutate({ id: lead.id, patch: { scheduled_at } })
                }
                onMarkConfirmed={() =>
                  updateLead.mutate({
                    id: lead.id,
                    patch: { confirmation_sent_at: new Date().toISOString() },
                  })
                }
                onDelete={() => {
                  if (confirm(`Delete lead from ${lead.full_name}?`)) {
                    deleteLead.mutate(lead.id);
                  }
                }}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function FilterTile({
  label,
  value,
  active,
  onClick,
}: {
  label: string;
  value: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`bg-background p-5 text-left transition-colors hover:bg-white/5 ${
        active ? "ring-1 ring-accent/60" : ""
      }`}
    >
      <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1">{label}</div>
      <div className={`text-2xl font-extrabold tracking-tight ${active ? "text-accent" : ""}`}>{value}</div>
    </button>
  );
}

type CallStatus = "not_booked" | "upcoming" | "today" | "past";

function getCallStatus(scheduledAt: string | null): CallStatus {
  if (!scheduledAt) return "not_booked";
  const s = new Date(scheduledAt);
  const now = new Date();
  if (s < now) return "past";
  if (s.toDateString() === now.toDateString()) return "today";
  return "upcoming";
}

const CALL_STATUS_META: Record<CallStatus, { label: string; className: string }> = {
  not_booked: { label: "Not booked", className: "text-muted-foreground border-border" },
  upcoming: { label: "Upcoming", className: "text-accent border-accent/40" },
  today: { label: "Today", className: "text-background bg-accent border-accent" },
  past: { label: "Past", className: "text-muted-foreground border-border/60 line-through" },
};

// Convert ISO timestamp to value usable by <input type="datetime-local"> in local time
function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function LeadRow({
  lead,
  onStatusChange,
  onNotesChange,
  onScheduleChange,
  onMarkConfirmed,
  onDelete,
}: {
  lead: Lead;
  onStatusChange: (status: LeadStatus) => void;
  onNotesChange: (notes: string) => void;
  onScheduleChange: (scheduled_at: string | null) => void;
  onMarkConfirmed: () => void;
  onDelete: () => void;
}) {
  const [notes, setNotes] = useState(lead.notes ?? "");
  const [expanded, setExpanded] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState(false);
  const [scheduleDraft, setScheduleDraft] = useState(isoToLocalInput(lead.scheduled_at));
  const created = new Date(lead.created_at);
  const callStatus = getCallStatus(lead.scheduled_at);
  const callMeta = CALL_STATUS_META[callStatus];
  const confirmationSent = lead.confirmation_sent_at
    ? new Date(lead.confirmation_sent_at)
    : null;

  const handleSaveSchedule = () => {
    if (!scheduleDraft) {
      onScheduleChange(null);
    } else {
      const d = new Date(scheduleDraft);
      if (isNaN(d.getTime())) {
        toast.error("Invalid date");
        return;
      }
      onScheduleChange(d.toISOString());
    }
    setEditingSchedule(false);
    toast.success("Call time updated.");
  };

  const handleSendConfirmation = () => {
    if (!lead.scheduled_at) {
      toast.error("No call time scheduled.");
      return;
    }
    const slot = new Date(lead.scheduled_at);
    const dateLine = slot.toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    });
    const timeLine = slot.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    const subject = `Your Lexus Nexus Capital intake call — ${dateLine}`;
    const body = [
      `${lead.full_name},`,
      "",
      `Confirming your introductory call with Lexus Nexus Capital Group.`,
      "",
      `Date:  ${dateLine}`,
      `Time:  ${timeLine} (${Intl.DateTimeFormat().resolvedOptions().timeZone})`,
      "",
      `A secure dial-in link will follow shortly. Reply to this email if you need to reschedule.`,
      "",
      `— Lexus Nexus Capital Group`,
    ].join("\n");
    window.location.href = `mailto:${encodeURIComponent(lead.email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    onMarkConfirmed();
    toast.success("Confirmation drafted and marked as sent.");
  };

  return (
    <div className="bg-background p-5 md:p-6">
      <div className="grid grid-cols-1 md:grid-cols-[1.5fr_1.5fr_1.4fr_auto] gap-4 items-start">
        <div>
          <div className="font-extrabold uppercase tracking-tight text-base">{lead.full_name}</div>
          <a href={`mailto:${lead.email}`} className="text-sm text-muted-foreground hover:text-foreground break-all">
            {lead.email}
          </a>
        </div>
        <div className="space-y-1">
          <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Capital</div>
          <div className="text-sm">{lead.capital_size || <span className="text-muted-foreground">—</span>}</div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground pt-2">Received</div>
          <div className="text-sm font-mono">
            {created.toLocaleDateString()} · {created.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </div>
        </div>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">Call</div>
            <span
              className={`font-mono text-[9px] uppercase tracking-widest px-1.5 py-0.5 border ${callMeta.className}`}
            >
              {callMeta.label}
            </span>
          </div>
          {editingSchedule ? (
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="datetime-local"
                value={scheduleDraft}
                onChange={(e) => setScheduleDraft(e.target.value)}
                className="bg-background border border-border px-2 py-1.5 text-sm font-mono focus:outline-none focus:border-accent"
              />
              <button
                onClick={handleSaveSchedule}
                className="font-mono text-[10px] uppercase tracking-widest px-2 py-1.5 bg-foreground text-background hover:bg-accent"
              >
                Save
              </button>
              <button
                onClick={() => {
                  setScheduleDraft(isoToLocalInput(lead.scheduled_at));
                  setEditingSchedule(false);
                }}
                className="font-mono text-[10px] uppercase tracking-widest px-2 py-1.5 border border-border hover:bg-white/5"
              >
                Cancel
              </button>
              {lead.scheduled_at && (
                <button
                  onClick={() => {
                    onScheduleChange(null);
                    setEditingSchedule(false);
                    toast.success("Call cleared.");
                  }}
                  className="font-mono text-[10px] uppercase tracking-widest px-2 py-1.5 text-destructive hover:bg-destructive/10"
                >
                  Clear
                </button>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2 flex-wrap">
              <div className="text-sm font-mono">
                {lead.scheduled_at ? (
                  <span className={callStatus === "past" ? "text-muted-foreground" : "text-foreground"}>
                    {new Date(lead.scheduled_at).toLocaleDateString()} ·{" "}
                    {new Date(lead.scheduled_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </div>
              <button
                onClick={() => setEditingSchedule(true)}
                className="font-mono text-[9px] uppercase tracking-widest text-accent hover:text-foreground"
              >
                Edit
              </button>
            </div>
          )}
          {confirmationSent && (
            <div className="font-mono text-[10px] text-muted-foreground">
              ✓ Confirmation sent {confirmationSent.toLocaleDateString()}
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 justify-end">
          <select
            value={lead.status}
            onChange={(e) => onStatusChange(e.target.value as LeadStatus)}
            className="bg-background border border-border px-3 py-2 font-mono text-[11px] uppercase tracking-widest focus:outline-none focus:border-accent"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
          <button
            onClick={handleSendConfirmation}
            disabled={!lead.scheduled_at}
            className="font-mono text-[10px] uppercase tracking-widest px-3 py-2 border border-accent/40 text-accent hover:bg-accent/10 disabled:opacity-40 disabled:cursor-not-allowed"
            title={lead.scheduled_at ? "Send booking confirmation" : "Schedule a call first"}
          >
            {confirmationSent ? "Resend Confirm" : "Send Confirm"}
          </button>
          <button
            onClick={() => setExpanded((v) => !v)}
            className="font-mono text-[10px] uppercase tracking-widest px-3 py-2 border border-border hover:bg-white/5"
          >
            {expanded ? "Close" : "Notes"}
          </button>
          <button
            onClick={onDelete}
            className="font-mono text-[10px] uppercase tracking-widest px-3 py-2 text-destructive hover:bg-destructive/10"
            aria-label="Delete lead"
          >
            Delete
          </button>
        </div>
      </div>
      {expanded && (
        <div className="mt-5 space-y-3">
          <label className="font-mono text-[10px] uppercase text-muted-foreground tracking-widest">Internal notes</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={2000}
            rows={4}
            className="w-full bg-background border border-border p-3 text-sm focus:outline-none focus:border-accent"
            placeholder="Call notes, qualification details, next steps…"
          />
          <div className="flex justify-end">
            <button
              onClick={() => {
                onNotesChange(notes);
                toast.success("Notes saved.");
              }}
              className="font-mono text-[10px] uppercase tracking-widest px-4 py-2 bg-foreground text-background hover:bg-accent"
            >
              Save notes
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function FullScreenMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-foreground grid place-items-center px-6">
      <div className="font-mono text-xs uppercase tracking-widest text-muted-foreground">{children}</div>
    </div>
  );
}
