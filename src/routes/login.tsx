import { createFileRoute, useNavigate, Link } from "@tanstack/react-router";
import { useState } from "react";
import { toast } from "sonner";
import { supabase } from "@/integrations/supabase/client";

export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [
      { title: "Admin Sign In — Lexus Nexus Capital Group" },
      { name: "description", content: "Admin sign in for the Lexus Nexus lead management dashboard." },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: LoginPage,
});

function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password.length < 8) {
      toast.error("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    if (mode === "signup") {
      const { error } = await supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: `${window.location.origin}/admin` },
      });
      setBusy(false);
      if (error) {
        toast.error(error.message);
        return;
      }
      toast.success("Account created. Check your email to confirm, then sign in.");
      setMode("signin");
      return;
    }
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) {
      toast.error(error.message);
      return;
    }
    toast.success("Welcome back.");
    navigate({ to: "/admin" });
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col">
      <header className="px-6 md:px-10 py-6 border-b border-border">
        <Link to="/" className="font-extrabold tracking-tighter text-xl uppercase">
          Lexus Nexus
        </Link>
      </header>
      <main className="flex-1 grid place-items-center px-6 py-16">
        <div className="w-full max-w-md space-y-10">
          <div className="space-y-3">
            <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">Restricted Access</span>
            <h1 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase">
              {mode === "signin" ? "Sign In" : "Create Account"}
            </h1>
            <p className="text-sm text-muted-foreground">
              The first account created becomes the dashboard administrator.
            </p>
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
              />
            </div>
            <button
              type="submit"
              disabled={busy}
              className="w-full py-4 bg-foreground text-background font-extrabold uppercase tracking-[0.2em] hover:bg-accent transition-colors disabled:opacity-50"
            >
              {busy ? "Working…" : mode === "signin" ? "Sign In" : "Create Account"}
            </button>
          </form>
          <button
            onClick={() => setMode(mode === "signin" ? "signup" : "signin")}
            className="w-full font-mono text-[11px] uppercase tracking-widest text-muted-foreground hover:text-foreground"
          >
            {mode === "signin" ? "Need to create the admin account?" : "Have an account? Sign in"}
          </button>
        </div>
      </main>
    </div>
  );
}
