import { createFileRoute } from "@tanstack/react-router";
import { supabaseAdmin } from "@/integrations/supabase/client.server";
import { publishToPlatform } from "@/lib/social/publishers";
import { MIN_POSTS_PER_DAY, type PostingWindow, type Platform } from "@/lib/social/types";

// Public hook called every minute by pg_cron. It:
//   1. Claims due `scheduled` posts and tries to publish them.
//   2. Ensures every active account has >= min_posts_per_day rows for "today";
//      creates empty `scheduled` slots in any unused posting windows.
export const Route = createFileRoute("/api/public/social/tick")({
  server: {
    handlers: {
      POST: async ({ request }) => {
        const expected = process.env.SUPABASE_SERVICE_ROLE_KEY;
        const authHeader = request.headers.get("Authorization");
        const token = authHeader?.startsWith("Bearer ") ? authHeader.slice(7).trim() : null;
        if (!expected || !token || token !== expected) {
          return new Response(JSON.stringify({ error: "Unauthorized" }), {
            status: 401,
            headers: { "Content-Type": "application/json" },
          });
        }

        const result = { claimed: 0, published: 0, failed: 0, topUpsCreated: 0 };

        // 1. Claim due posts
        const nowISO = new Date().toISOString();
        const { data: claimable } = await supabaseAdmin
          .from("scheduled_posts")
          .select("id")
          .eq("status", "scheduled")
          .lte("scheduled_for", nowISO)
          .limit(20);

        const ids = (claimable ?? []).map((r) => r.id);
        if (ids.length) {
          await supabaseAdmin
            .from("scheduled_posts")
            .update({ status: "publishing" })
            .in("id", ids)
            .eq("status", "scheduled");

          const { data: claimed } = await supabaseAdmin
            .from("scheduled_posts")
            .select("id, account_id, body, media_urls")
            .in("id", ids);

          result.claimed = claimed?.length ?? 0;

          for (const row of claimed ?? []) {
            const { data: account } = await supabaseAdmin
              .from("social_accounts")
              .select("platform, platform_account_id, access_token_encrypted")
              .eq("id", row.account_id)
              .single();

            const platform = (account?.platform ?? "x") as Platform;
            const publishResult = await publishToPlatform(platform, {
              body: row.body ?? "",
              mediaUrls: row.media_urls ?? [],
              accessTokenCipher: account?.access_token_encrypted ?? null,
              platformAccountId: account?.platform_account_id ?? null,
            });

            if (publishResult.ok) {
              result.published++;
              await supabaseAdmin
                .from("scheduled_posts")
                .update({
                  status: "published",
                  published_at: new Date().toISOString(),
                  platform_post_id: publishResult.platformPostId ?? null,
                  platform_post_url: publishResult.platformPostUrl ?? null,
                  error: null,
                })
                .eq("id", row.id);
            } else {
              result.failed++;
              await supabaseAdmin
                .from("scheduled_posts")
                .update({
                  status: "failed",
                  error: publishResult.error ?? "Unknown publish error",
                })
                .eq("id", row.id);
            }
          }
        }

        // 2. Quota top-ups: ensure every active account meets MIN per day
        const todayStart = new Date();
        todayStart.setUTCHours(0, 0, 0, 0);
        const todayEnd = new Date(todayStart);
        todayEnd.setUTCDate(todayEnd.getUTCDate() + 1);

        const { data: accounts } = await supabaseAdmin
          .from("social_accounts")
          .select("id, user_id, min_posts_per_day, posting_windows, active")
          .eq("active", true);

        for (const acc of accounts ?? []) {
          const { data: existing } = await supabaseAdmin
            .from("scheduled_posts")
            .select("scheduled_for")
            .eq("account_id", acc.id)
            .gte("scheduled_for", todayStart.toISOString())
            .lt("scheduled_for", todayEnd.toISOString())
            .neq("status", "cancelled");

          const have = existing?.length ?? 0;
          const need = Math.max(
            0,
            (acc.min_posts_per_day ?? MIN_POSTS_PER_DAY) - have,
          );
          if (need === 0) continue;

          const taken = new Set(
            (existing ?? []).map((e) => e.scheduled_for).filter(Boolean) as string[],
          );
          const windows = (acc.posting_windows ?? []) as PostingWindow[];
          const now = Date.now();
          const slots: string[] = [];
          for (const w of windows) {
            if (slots.length >= need) break;
            const t = new Date(
              Date.UTC(
                todayStart.getUTCFullYear(),
                todayStart.getUTCMonth(),
                todayStart.getUTCDate(),
                w.hour,
                w.minute,
                0,
                0,
              ),
            );
            if (t.getTime() <= now) continue;
            const iso = t.toISOString();
            if (taken.has(iso)) continue;
            slots.push(iso);
          }
          // If today's remaining windows can't cover the need, push to tomorrow
          if (slots.length < need) {
            const tomorrowStart = new Date(todayEnd);
            for (const w of windows) {
              if (slots.length >= need) break;
              const t = new Date(
                Date.UTC(
                  tomorrowStart.getUTCFullYear(),
                  tomorrowStart.getUTCMonth(),
                  tomorrowStart.getUTCDate(),
                  w.hour,
                  w.minute,
                  0,
                  0,
                ),
              );
              const iso = t.toISOString();
              if (taken.has(iso)) continue;
              slots.push(iso);
            }
          }

          if (slots.length) {
            const rows = slots.map((iso) => ({
              account_id: acc.id,
              user_id: acc.user_id,
              status: "scheduled" as const,
              scheduled_for: iso,
              body: "",
              source: "autofill-empty",
            }));
            await supabaseAdmin.from("scheduled_posts").insert(rows);
            result.topUpsCreated += rows.length;
          }
        }

        return new Response(JSON.stringify(result), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      },
    },
  },
});
