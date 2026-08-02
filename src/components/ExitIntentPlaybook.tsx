import { useEffect, useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const SEEN_KEY = "scg_playbook_exit_seen";

/** Attribution captured from the current URL so the agent can score channels. */
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
    referrer: document.referrer || undefined,
    landing_page: window.location.href.slice(0, 2048),
  };
}

/**
 * Last-chance capture: fires on desktop exit intent (cursor leaves the viewport
 * top) or, on touch devices, after 40s of engaged scrolling. Shown at most once
 * per browser.
 */
export function ExitIntentPlaybook() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (localStorage.getItem(SEEN_KEY)) return;

    let fired = false;
    const fire = () => {
      if (fired) return;
      fired = true;
      localStorage.setItem(SEEN_KEY, "1");
      setOpen(true);
      cleanup();
    };

    const onMouseOut = (e: MouseEvent) => {
      if (e.clientY <= 0 && !e.relatedTarget) fire();
    };

    const timer = window.setTimeout(() => {
      const scrolled =
        window.scrollY / Math.max(1, document.body.scrollHeight - window.innerHeight);
      if (scrolled > 0.25) fire();
    }, 40000);

    const cleanup = () => {
      document.removeEventListener("mouseout", onMouseOut);
      window.clearTimeout(timer);
    };

    document.addEventListener("mouseout", onMouseOut);
    return cleanup;
  }, []);

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
          full_name: parsed.data.split("@")[0]?.slice(0, 100) || "Trader",
          email: parsed.data,
          tier: "Free Playbook",
          source: "playbook-exit",
          ...utmPayload(),
        }),
      });
      const json = await res.json();
      if (!res.ok || !json?.success) throw new Error();
      setDone(true);
      toast.success("Sent. Check your inbox for the playbook.");
    } catch {
      toast.error("Something went wrong. Try again.");
    } finally {
      setSending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-md border-border bg-background">
        <DialogHeader>
          <DialogTitle className="text-2xl font-extrabold uppercase tracking-tighter">
            Before you go
          </DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Take the Session Sweep Playbook with you — the 5–15 Gap and Power of 3 framework, written
          out in full. Free, no call required.
        </p>
        {done ? (
          <p className="font-mono text-xs uppercase tracking-widest text-accent pt-2">
            On its way — check your inbox.
          </p>
        ) : (
          <form onSubmit={submit} className="space-y-4 pt-2">
            <input
              required
              type="email"
              value={email}
              onChange={(ev) => setEmail(ev.target.value)}
              maxLength={255}
              placeholder="you@email.com"
              aria-label="Email address for the free playbook"
              className="w-full bg-transparent border-b border-border py-3 focus:outline-none focus:border-accent placeholder:text-muted-foreground/40"
            />
            <button
              type="submit"
              disabled={sending}
              className="w-full px-8 py-4 bg-foreground text-background font-extrabold uppercase tracking-[0.2em] text-xs hover:bg-accent transition-colors duration-500 disabled:opacity-50"
            >
              {sending ? "Sending…" : "Send me the playbook"}
            </button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
