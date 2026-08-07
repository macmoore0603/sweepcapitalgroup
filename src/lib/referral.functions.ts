import { createServerFn } from "@tanstack/react-start";

/**
 * Public referral lookup: given the exact email a lead signed up with,
 * return their personal referral link and conversion stats.
 * Only non-sensitive aggregate data is returned.
 */
export const getReferralStats = createServerFn({ method: "POST" })
  .inputValidator((data: { email: string }) => {
    const email = String(data.email ?? "").trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 255) {
      throw new Error("Invalid email");
    }
    return { email };
  })
  .handler(async ({ data }) => {
    const url = process.env["SUPABASE_URL"];
    const key = process.env["SUPABASE_SERVICE_ROLE_KEY"];
    if (!url || !key) throw new Error("Backend unavailable");
    const { createClient } = await import("@supabase/supabase-js");
    const sb: any = createClient(url, key, { auth: { persistSession: false } });

    const { data: lead } = await sb
      .from("leads")
      .select("referral_code")
      .ilike("email", data.email)
      .maybeSingle();

    if (!lead?.referral_code) return { found: false as const };

    const code: string = lead.referral_code;

    const [clicks, conversions] = await Promise.all([
      sb.from("referral_clicks").select("id", { count: "exact", head: true }).eq("code", code),
      sb.from("referral_conversions").select("amount_cents").eq("code", code),
    ]);

    const rows: Array<{ amount_cents: number | null }> = conversions.data ?? [];
    const revenueCents = rows.reduce((sum, r) => sum + (r.amount_cents ?? 0), 0);

    return {
      found: true as const,
      code,
      link: `https://sweepcapitalgroup.com/ref/${code}`,
      clicks: clicks.count ?? 0,
      sales: rows.length,
      revenue: revenueCents / 100,
    };
  });
