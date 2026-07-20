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
  name: "outbound_stats",
  title: "Outbound stats",
  description: "Return counts of outbound cold-email contacts by status and step.",
  inputSchema: {},
  annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  handler: async (_input, ctx) => {
    if (!ctx.isAuthenticated()) return { content: [{ type: "text", text: "Not authenticated" }], isError: true };
    const { data, error } = await supabaseForUser(ctx)
      .from("outbound_contacts")
      .select("status,step");
    if (error) return { content: [{ type: "text", text: error.message }], isError: true };
    const stats: Record<string, number> = { queued: 0, contacted: 0, replied: 0, converted: 0, stopped: 0, total: 0 };
    for (const r of data ?? []) {
      stats.total++;
      const s = (r as any).status as string;
      if (s in stats) stats[s]++;
    }
    return {
      content: [{ type: "text", text: JSON.stringify(stats, null, 2) }],
      structuredContent: stats,
    };
  },
});
