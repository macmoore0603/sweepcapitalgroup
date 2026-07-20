import { createClient } from "@supabase/supabase-js";
import { defineTool, type ToolContext } from "@lovable.dev/mcp-js";
import { z } from "zod";

function supabaseForUser(ctx: ToolContext) {
  return createClient(process.env.SUPABASE_URL!, process.env.SUPABASE_PUBLISHABLE_KEY!, {
    global: { headers: { Authorization: `Bearer ${ctx.getToken()}` } },
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

export default defineTool({
  name: "revenue_summary",
  title: "Revenue summary",
  description: "Return month-to-date revenue and target progress from revenue_events + revenue_settings.",
  inputSchema: {},
  annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  handler: async (_input, ctx) => {
    if (!ctx.isAuthenticated()) return { content: [{ type: "text", text: "Not authenticated" }], isError: true };
    const supabase = supabaseForUser(ctx);
    const monthStart = new Date();
    monthStart.setUTCDate(1);
    monthStart.setUTCHours(0, 0, 0, 0);

    const [events, settings] = await Promise.all([
      supabase
        .from("revenue_events")
        .select("amount_cents,created_at,event_type")
        .gte("created_at", monthStart.toISOString()),
      supabase.from("revenue_settings").select("monthly_target_cents").limit(1).maybeSingle(),
    ]);
    if (events.error) return { content: [{ type: "text", text: events.error.message }], isError: true };

    const mtdCents = (events.data ?? []).reduce((sum, r: any) => sum + (r.amount_cents ?? 0), 0);
    const targetCents = settings.data?.monthly_target_cents ?? 5_000_000;
    const summary = {
      month_to_date_usd: mtdCents / 100,
      target_usd: targetCents / 100,
      progress_pct: targetCents ? Math.round((mtdCents / targetCents) * 100) : 0,
      event_count: events.data?.length ?? 0,
    };
    return {
      content: [{ type: "text", text: JSON.stringify(summary, null, 2) }],
      structuredContent: summary,
    };
  },
});
