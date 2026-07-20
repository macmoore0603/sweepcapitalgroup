import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";

export const Route = createFileRoute("/login")({
  validateSearch: (s: Record<string, unknown>) => ({
    next: typeof s.next === "string" ? s.next : "",
  }),
  head: () => ({
    meta: [
      { title: "Admin Sign In — Sweep Capital Group" },
      { name: "description", content: "Admin sign in for the Sweep lead management dashboard." },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: LoginPage,
});

function isSafeRelative(next: string) {
  return next.startsWith("/") && !next.startsWith("//");
}

function LoginPage() {
  const navigate = useNavigate();
  const { next } = Route.useSearch();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password.length < 8) {
      toast.error("Invalid credentials.");
      return;
    }
    setBusy(true);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) {
      toast.error("Invalid credentials.");
      return;
    }
    toast.success("Welcome back.");
    if (next && isSafeRelative(next)) {
      window.location.href = next;
      return;
    }
    navigate({ to: "/admin" });
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      <header className="px-6 md:px-10 py-6 border-b border-border">
        <Link to="/" className="font-extrabold tracking-tighter text-xl uppercase">
          Sweep
        </Link>
      </header>
      <main className="flex-1 grid place-items-center px-6 py-16">
        <div className="w-full max-w-md space-y-10">
          <div className="space-y-3">
            <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">Restricted Access</span>
            <h1 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase">
              Sign In
            </h1>
          </div>
          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="space-y-2">
              <label className="font-mono text-[10px] uppercase text-muted-foreground tracking-widest">Email</label>
              <input
                required
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                maxLength={255}
                className="w-full bg-transparent border-b border-border py-3 focus:outline-none focus:border-accent text-base"
                placeholder="you@firm.com"
                autoComplete="email"
              />
            </div>
            <div className="space-y-2">
              <label className="font-mono text-[10px] uppercase text-muted-foreground tracking-widest">Password</label>
              <input
                required
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={8}
                maxLength={128}
                className="w-full bg-transparent border-b border-border py-3 focus:outline-none focus:border-accent text-base"
                placeholder="••••••••"
                autoComplete="current-password"
              />
            </div>
            <button
              type="submit"
              disabled={busy}
              className="w-full py-4 bg-foreground text-background font-extrabold uppercase tracking-[0.2em] hover:bg-accent transition-colors disabled:opacity-50"
            >
              {busy ? "Working…" : "Sign In"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}
