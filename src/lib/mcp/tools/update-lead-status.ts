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
  name: "update_lead_status",
  title: "Update lead status",
  description: "Update the status of a lead by id (e.g. 'new', 'contacted', 'won', 'lost').",
  inputSchema: {
    id: z.string().uuid().describe("Lead UUID."),
    status: z.string().describe("New status value."),
  },
  annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  handler: async ({ id, status }, ctx) => {
    if (!ctx.isAuthenticated()) return { content: [{ type: "text", text: "Not authenticated" }], isError: true };
    const { data, error } = await supabaseForUser(ctx)
      .from("leads")
      .update({ status })
      .eq("id", id)
      .select("id,status")
      .maybeSingle();
    if (error) return { content: [{ type: "text", text: error.message }], isError: true };
    if (!data) return { content: [{ type: "text", text: "Lead not found or not permitted." }], isError: true };
    return {
      content: [{ type: "text", text: `Updated ${data.id} → ${data.status}` }],
      structuredContent: { lead: data },
    };
  },
});
