import { useEffect, useState } from "react";
import type { HealthStatus as HealthStatusData } from "@/lib/health";

export function HealthStatus() {
  const [health, setHealth] = useState<Partial<HealthStatusData> & { status: string } | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const res = await fetch("/api/health", { cache: "no-store" });
        const data = await res.json();
        if (!cancelled) setHealth(data);
      } catch {
        if (!cancelled) setHealth({ status: "unhealthy" });
      }
    }
    check();
    const id = setInterval(check, 30000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const healthy = health?.status === "healthy";

  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1 text-[10px] font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground"
      >
        <span className="relative flex h-2 w-2">
          <span
            className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 ${healthy ? "bg-emerald-400" : "bg-rose-500"}`}
          />
          <span
            className={`relative inline-flex h-2 w-2 rounded-full ${healthy ? "bg-emerald-500" : "bg-rose-600"}`}
          />
        </span>
        <span>
          App {healthy ? "Healthy" : "Unhealthy"}
          {health?.version ? ` · v${health.version}` : ""}
          {health?.commitShort ? ` · ${health.commitShort}` : ""}
        </span>
      </button>
      {open && health?.status === "healthy" && (
        <div className="rounded-md border border-border bg-background px-3 py-2 text-[10px] font-mono text-muted-foreground space-y-0.5 min-w-[220px]">
          <div>version: <span className="text-foreground">{health.version}</span></div>
          <div>commit: <span className="text-foreground">{health.commitShort}</span></div>
          <div>env: <span className="text-foreground">{health.environment}</span></div>
          <div>built: <span className="text-foreground">{health.buildTime}</span></div>
        </div>
      )}
    </div>
  );
}
