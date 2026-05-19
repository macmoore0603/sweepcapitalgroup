import { useEffect, useState } from "react";
import { useRouter } from "@tanstack/react-router";

export function HealthStatus() {
  const [health, setHealth] = useState<{ status: string } | null>(null);
  const router = useRouter();

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
  const isRouterHealthy = router.state.status !== "error";

  return (
    <div className="flex items-center gap-2 rounded-full border border-border bg-background px-3 py-1 text-[10px] font-mono uppercase tracking-widest text-muted-foreground">
      <span className="relative flex h-2 w-2">
        <span
          className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 ${healthy ? "bg-emerald-400" : "bg-rose-500"}`}
        />
        <span
          className={`relative inline-flex h-2 w-2 rounded-full ${healthy ? "bg-emerald-500" : "bg-rose-600"}`}
        />
      </span>
      <span>
        App {healthy ? "Healthy" : "Unhealthy"} · Router {isRouterHealthy ? "Healthy" : "Error"}
      </span>
    </div>
  );
}
