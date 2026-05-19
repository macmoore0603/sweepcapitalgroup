import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { requireSupabaseAuth } from "@/integrations/supabase/auth-middleware";
import { PLATFORMS, DEFAULT_WINDOWS, MIN_POSTS_PER_DAY } from "./types";

const platformEnum = z.enum(["instagram", "x", "linkedin", "tiktok", "youtube"] as const);

const windowSchema = z.object({
  hour: z.number().int().min(0).max(23),
  minute: z.number().int().min(0).max(59),
});

export const listAccounts = createServerFn({ method: "GET" })
  .middleware([requireSupabaseAuth])
  .handler(async ({ context }) => {
    const { supabase } = context;
    const { data, error } = await supabase
      .from("social_accounts")
      .select(
        "id, platform, handle, active, min_posts_per_day, posting_windows, timezone, expires_at, created_at",
      )
      .order("created_at", { ascending: false });
    if (error) throw new Error(error.message);
    return { accounts: data ?? [] };
  });

export const upsertAccount = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((input) =>
    z
      .object({
        id: z.string().uuid().optional(),
        platform: platformEnum,
        handle: z.string().min(1).max(100),
        min_posts_per_day: z.number().int().min(MIN_POSTS_PER_DAY).max(20).optional(),
        posting_windows: z.array(windowSchema).min(MIN_POSTS_PER_DAY).max(20).optional(),
        timezone: z.string().min(1).max(64).optional(),
        active: z.boolean().optional(),
      })
      .parse(input),
  )
  .handler(async ({ data, context }) => {
    const { supabase, userId } = context;
    const payload = {
      user_id: userId,
      platform: data.platform,
      handle: data.handle,
      min_posts_per_day: data.min_posts_per_day ?? MIN_POSTS_PER_DAY,
      posting_windows: data.posting_windows ?? DEFAULT_WINDOWS,
      timezone: data.timezone ?? "UTC",
      active: data.active ?? true,
    };
    if (data.id) {
      const { data: row, error } = await supabase
        .from("social_accounts")
        .update(payload)
        .eq("id", data.id)
        .select()
        .single();
      if (error) throw new Error(error.message);
      return { account: row };
    }
    const { data: row, error } = await supabase
      .from("social_accounts")
      .insert(payload)
      .select()
      .single();
    if (error) throw new Error(error.message);
    return { account: row };
  });

export const deleteAccount = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((input) => z.object({ id: z.string().uuid() }).parse(input))
  .handler(async ({ data, context }) => {
    const { supabase } = context;
    const { error } = await supabase.from("social_accounts").delete().eq("id", data.id);
    if (error) throw new Error(error.message);
    return { ok: true };
  });
