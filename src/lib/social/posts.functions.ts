import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { requireSupabaseAuth } from "@/integrations/supabase/auth-middleware";
import { buildSystemPrompt } from "./prompts";
import { runGuardrails } from "./guardrails";
import { PLATFORMS, type Platform, type PostingWindow, MIN_POSTS_PER_DAY } from "./types";

const platformEnum = z.enum(PLATFORMS as [string, ...string[]]);

type DraftedPost = {
  platform: Platform;
  body: string;
  ok: boolean;
  violations: string[];
  warnings: string[];
};

async function callLovableAI(
  systemPrompt: string,
  userPrompt: string,
  model = "google/gemini-2.5-flash",
): Promise<string> {
  const apiKey = process.env.LOVABLE_API_KEY;
  if (!apiKey) throw new Error("LOVABLE_API_KEY missing");

  const res = await fetch("https://ai.gateway.lovable.dev/v1/chat/completions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model,
      messages: [
        { role: "system", content: systemPrompt },
        { role: "user", content: userPrompt },
      ],
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`AI gateway error ${res.status}: ${text.slice(0, 200)}`);
  }
  const json = (await res.json()) as {
    choices?: Array<{ message?: { content?: string } }>;
  };
  return json.choices?.[0]?.message?.content?.trim() ?? "";
}

export const draftForPlatforms = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((input) =>
    z
      .object({
        goal: z.string().min(3).max(2000),
        platforms: z.array(platformEnum).min(1).max(PLATFORMS.length),
        brandVoiceNotes: z.string().max(2000).optional(),
      })
      .parse(input),
  )
  .handler(async ({ data }): Promise<{ drafts: DraftedPost[] }> => {
    const results = await Promise.all(
      data.platforms.map(async (platform) => {
        const system = buildSystemPrompt(platform as Platform, data.brandVoiceNotes);
        try {
          const raw = await callLovableAI(system, data.goal);
          const checked = runGuardrails(platform as Platform, raw);
          return {
            platform: platform as Platform,
            body: checked.sanitized,
            ok: checked.ok,
            violations: checked.violations,
            warnings: checked.warnings,
          };
        } catch (e) {
          const message = e instanceof Error ? e.message : String(e);
          return {
            platform: platform as Platform,
            body: "",
            ok: false,
            violations: [`AI error: ${message}`],
            warnings: [],
          };
        }
      }),
    );
    return { drafts: results };
  });

// Pick the next future slot for an account that has no post scheduled at that time.
function nextOpenSlots(
  windows: PostingWindow[],
  takenISO: Set<string>,
  fromDate: Date,
  needed: number,
): Date[] {
  const slots: Date[] = [];
  const seen = new Set<string>();
  for (let dayOffset = 0; slots.length < needed && dayOffset < 14; dayOffset++) {
    const day = new Date(fromDate);
    day.setUTCDate(day.getUTCDate() + dayOffset);
    for (const w of windows) {
      const t = new Date(
        Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), w.hour, w.minute, 0, 0),
      );
      if (t.getTime() <= fromDate.getTime()) continue;
      const key = t.toISOString();
      if (takenISO.has(key) || seen.has(key)) continue;
      seen.add(key);
      slots.push(t);
      if (slots.length >= needed) break;
    }
  }
  return slots;
}

export const autofillDay = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((input) =>
    z
      .object({
        accountId: z.string().uuid(),
        date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
        goalHint: z.string().max(500).optional(),
      })
      .parse(input),
  )
  .handler(async ({ data, context }) => {
    const { supabase, userId } = context;
    const { data: account, error: accErr } = await supabase
      .from("social_accounts")
      .select("id, platform, handle, min_posts_per_day, posting_windows, timezone, active")
      .eq("id", data.accountId)
      .single();
    if (accErr || !account) throw new Error(accErr?.message ?? "Account not found");

    const dayStart = new Date(`${data.date}T00:00:00.000Z`);
    const dayEnd = new Date(`${data.date}T23:59:59.999Z`);

    const { data: existing } = await supabase
      .from("scheduled_posts")
      .select("scheduled_for, status")
      .eq("account_id", account.id)
      .gte("scheduled_for", dayStart.toISOString())
      .lte("scheduled_for", dayEnd.toISOString())
      .neq("status", "cancelled");

    const validCount = (existing ?? []).filter((p) =>
      ["draft", "scheduled", "publishing", "published"].includes(p.status),
    ).length;

    const needed = Math.max(0, (account.min_posts_per_day ?? MIN_POSTS_PER_DAY) - validCount);
    if (needed === 0) return { created: 0, alreadyMet: true };

    const taken = new Set((existing ?? []).map((p) => p.scheduled_for).filter(Boolean) as string[]);
    const windows = account.posting_windows as PostingWindow[];
    const fromDate = new Date(Math.max(Date.now(), dayStart.getTime()));
    const slots = nextOpenSlots(windows, taken, fromDate, needed);

    const drafts = await draftForPlatforms({
      data: {
        goal:
          data.goalHint ??
          `Educational post for Lexus Nexus Capital Group about disciplined trading, capital preservation, or the mentorship program. Pick a fresh angle.`,
        platforms: [account.platform as Platform],
      },
    });

    const draftBody = drafts.drafts[0]?.body ?? "";
    const rows = slots.map((slot, idx) => ({
      account_id: account.id,
      user_id: userId,
      status: "scheduled" as const,
      scheduled_for: slot.toISOString(),
      body: idx === 0 ? draftBody : "",
      source: "autofill",
    }));

    if (rows.length) {
      const { error } = await supabase.from("scheduled_posts").insert(rows);
      if (error) throw new Error(error.message);
    }
    return { created: rows.length, alreadyMet: false };
  });

export const listPosts = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .inputValidator((input) =>
    z
      .object({
        fromISO: z.string().optional(),
        toISO: z.string().optional(),
      })
      .parse(input ?? {}),
  )
  .handler(async ({ data, context }) => {
    const { supabase } = context;
    let q = supabase
      .from("scheduled_posts")
      .select(
        "id, account_id, status, scheduled_for, body, platform_post_id, platform_post_url, error, source, created_at",
      )
      .order("scheduled_for", { ascending: true, nullsFirst: false })
      .limit(500);
    if (data.fromISO) q = q.gte("scheduled_for", data.fromISO);
    if (data.toISO) q = q.lte("scheduled_for", data.toISO);
    const { data: rows, error } = await q;
    if (error) throw new Error(error.message);
    return { posts: rows ?? [] };
  });

export const upsertPost = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((input) =>
    z
      .object({
        id: z.string().uuid().optional(),
        account_id: z.string().uuid(),
        body: z.string().max(8000),
        scheduled_for: z.string().datetime().nullable(),
        status: z
          .enum(["draft", "scheduled", "cancelled"])
          .optional(),
        media_urls: z.array(z.string().url()).max(10).optional(),
      })
      .parse(input),
  )
  .handler(async ({ data, context }) => {
    const { supabase, userId } = context;
    const payload = {
      account_id: data.account_id,
      user_id: userId,
      body: data.body,
      scheduled_for: data.scheduled_for,
      status: data.status ?? (data.scheduled_for ? "scheduled" : "draft"),
      media_urls: data.media_urls ?? [],
    };
    if (data.id) {
      const { data: row, error } = await supabase
        .from("scheduled_posts")
        .update(payload)
        .eq("id", data.id)
        .select()
        .single();
      if (error) throw new Error(error.message);
      return { post: row };
    }
    const { data: row, error } = await supabase
      .from("scheduled_posts")
      .insert(payload)
      .select()
      .single();
    if (error) throw new Error(error.message);
    return { post: row };
  });

export const deletePost = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((input) => z.object({ id: z.string().uuid() }).parse(input))
  .handler(async ({ data, context }) => {
    const { supabase } = context;
    const { error } = await supabase.from("scheduled_posts").delete().eq("id", data.id);
    if (error) throw new Error(error.message);
    return { ok: true };
  });

export const quotaToday = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    const { supabase } = context;
    const start = new Date();
    start.setUTCHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setUTCDate(end.getUTCDate() + 1);

    const { data: accounts } = await supabase
      .from("social_accounts")
      .select("id, platform, handle, min_posts_per_day")
      .eq("active", true);

    const { data: posts } = await supabase
      .from("scheduled_posts")
      .select("account_id, status, scheduled_for")
      .gte("scheduled_for", start.toISOString())
      .lt("scheduled_for", end.toISOString())
      .neq("status", "cancelled");

    const counts: Record<string, number> = {};
    for (const p of posts ?? []) {
      counts[p.account_id] = (counts[p.account_id] ?? 0) + 1;
    }

    return {
      date: start.toISOString().slice(0, 10),
      accounts: (accounts ?? []).map((a) => ({
        id: a.id,
        platform: a.platform,
        handle: a.handle,
        required: a.min_posts_per_day,
        scheduled: counts[a.id] ?? 0,
        meeting: (counts[a.id] ?? 0) >= a.min_posts_per_day,
      })),
    };
  });
