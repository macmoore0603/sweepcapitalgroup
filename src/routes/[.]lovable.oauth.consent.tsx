import { createFileRoute, redirect } from "@tanstack/react-router";
import { useState } from "react";
import { supabase } from "@/integrations/supabase/client";

type OAuthClient = { name?: string; client_uri?: string; redirect_uris?: string[] };
type OAuthDetails = {
  client?: OAuthClient;
  scope?: string;
  redirect_url?: string;
  redirect_to?: string;
} | null;

// Beta helper — types may not be exposed on @supabase/supabase-js yet.
const authOauth = (supabase.auth as unknown as {
  oauth: {
    getAuthorizationDetails: (id: string) => Promise<{ data: OAuthDetails; error: { message: string } | null }>;
    approveAuthorization: (id: string) => Promise<{ data: OAuthDetails; error: { message: string } | null }>;
    denyAuthorization: (id: string) => Promise<{ data: OAuthDetails; error: { message: string } | null }>;
  };
}).oauth;

export const Route = createFileRoute("/.lovable/oauth/consent")({
  ssr: false,
  validateSearch: (s: Record<string, unknown>) => ({
    authorization_id: typeof s.authorization_id === "string" ? s.authorization_id : "",
  }),
  beforeLoad: async ({ search, location }) => {
    if (!search.authorization_id) throw new Error("Missing authorization_id");
    const { data } = await supabase.auth.getSession();
    if (!data.session) {
      const next = location.pathname + location.searchStr;
      throw redirect({ to: "/login", search: { next } });
    }
  },
  loader: async ({ location }) => {
    const authorizationId = new URLSearchParams(location.search).get("authorization_id")!;
    const { data, error } = await authOauth.getAuthorizationDetails(authorizationId);
    if (error) throw new Error(error.message);
    const immediate = data?.redirect_url ?? data?.redirect_to;
    if (immediate && !data?.client) throw redirect({ href: immediate });
    return data;
  },
  component: Consent,
  errorComponent: ({ error }) => (
    <main className="min-h-screen grid place-items-center p-8 bg-background text-foreground">
      <div className="max-w-md space-y-2">
        <h1 className="text-2xl font-extrabold uppercase tracking-tight">Authorization error</h1>
        <p className="text-muted-foreground text-sm">{String((error as Error)?.message ?? error)}</p>
      </div>
    </main>
  ),
});

function Consent() {
  const details = Route.useLoaderData() as OAuthDetails;
  const { authorization_id } = Route.useSearch();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(approve: boolean) {
    setBusy(true);
    setError(null);
    const { data, error } = approve
      ? await authOauth.approveAuthorization(authorization_id)
      : await authOauth.denyAuthorization(authorization_id);
    if (error) {
      setBusy(false);
      setError(error.message);
      return;
    }
    const target = data?.redirect_url ?? data?.redirect_to;
    if (!target) {
      setBusy(false);
      setError("No redirect returned by the authorization server.");
      return;
    }
    window.location.href = target;
  }

  const clientName = details?.client?.name ?? "an app";

  return (
    <main className="min-h-screen grid place-items-center p-8 bg-background text-foreground">
      <div className="w-full max-w-md space-y-8 border border-border p-8">
        <div className="space-y-2">
          <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">Authorize</span>
          <h1 className="text-3xl font-extrabold uppercase tracking-tight">
            Connect {clientName} to Sweep Capital
          </h1>
          <p className="text-muted-foreground text-sm">
            {clientName} will be able to call this app's enabled tools while you are signed in.
            This does not bypass RLS or backend policies.
          </p>
        </div>
        {details?.scope && (
          <p className="font-mono text-[11px] text-muted-foreground uppercase tracking-widest">
            Scopes: {details.scope}
          </p>
        )}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <div className="flex gap-3">
          <button
            disabled={busy}
            onClick={() => decide(true)}
            className="flex-1 py-3 bg-foreground text-background font-extrabold uppercase tracking-[0.2em] hover:bg-accent transition-colors disabled:opacity-50"
          >
            {busy ? "Working…" : "Approve"}
          </button>
          <button
            disabled={busy}
            onClick={() => decide(false)}
            className="flex-1 py-3 border border-border font-extrabold uppercase tracking-[0.2em] hover:bg-muted transition-colors disabled:opacity-50"
          >
            Deny
          </button>
        </div>
      </div>
    </main>
  );
}
