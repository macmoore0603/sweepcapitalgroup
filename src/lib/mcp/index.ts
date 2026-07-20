import { auth, defineMcp } from "@lovable.dev/mcp-js";
import listLeads from "./tools/list-leads";
import revenueSummary from "./tools/revenue-summary";
import outboundStats from "./tools/outbound-stats";
import updateLeadStatus from "./tools/update-lead-status";

// See app-mcp-server-authoring: OAuth issuer must be the direct supabase.co
// host (not the .lovable.cloud proxy) or discovery/issuer verification fails.
const projectRef = import.meta.env.VITE_SUPABASE_PROJECT_ID ?? "project-ref-unset";

export default defineMcp({
  name: "sweep-capital-mcp",
  title: "Sweep Capital Group",
  version: "0.1.0",
  instructions:
    "Tools for the Sweep Capital Group admin/CRM: list mentorship leads, view revenue progress, view outbound outreach stats, and update lead statuses. All calls run as the signed-in user under RLS.",
  auth: auth.oauth.issuer({
    issuer: `https://${projectRef}.supabase.co/auth/v1`,
    acceptedAudiences: "authenticated",
  }),
  tools: [listLeads, revenueSummary, outboundStats, updateLeadStatus],
});
