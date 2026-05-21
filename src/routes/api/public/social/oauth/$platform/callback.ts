import { createFileRoute } from "@tanstack/react-router";
import { supabaseAdmin } from "@/integrations/supabase/client.server";
import { encryptToken, verifyState } from "@/lib/social/crypto";

const PUBLIC_URL = "https://lexusnexuscapital.lovable.app";

export const Route = createFileRoute("/api/public/social/oauth/$platform/callback")({
  server: {
    handlers: {
      GET: async ({ request, params }) => {
        const url = new URL(request.url);
        const code = url.searchParams.get("code");
        const state = url.searchParams.get("state");
        const errorParam =
          url.searchParams.get("error_description") ||
          url.searchParams.get("error");
        const platform = params.platform;

        const back = (msg: string) =>
          new Response(null, {
            status: 302,
            headers: {
              Location: `${PUBLIC_URL}/agent?oauth=${encodeURIComponent(msg)}`,
            },
          });

        if (errorParam) return back(`${platform}_error:${errorParam}`);
        if (!code || !state) return back(`${platform}_error:missing_params`);

        const payload = verifyState<{
          userId: string;
          platform: string;
          exp: number;
        }>(state);
        if (!payload || payload.platform !== platform) {
          return back(`${platform}_error:bad_state`);
        }

        const redirectUri = `${PUBLIC_URL}/api/public/social/oauth/${platform}/callback`;

        if (platform === "instagram") {
          try {
            const appId = process.env.META_APP_ID;
            const appSecret = process.env.META_APP_SECRET;
            if (!appId || !appSecret) {
              return back("instagram_error:meta_credentials_missing");
            }

            // 1. Short-lived user token
            const tokenUrl = new URL(
              "https://graph.facebook.com/v21.0/oauth/access_token",
            );
            tokenUrl.searchParams.set("client_id", appId);
            tokenUrl.searchParams.set("client_secret", appSecret);
            tokenUrl.searchParams.set("redirect_uri", redirectUri);
            tokenUrl.searchParams.set("code", code);
            const tokRes = await fetch(tokenUrl.toString());
            const tokJson = (await tokRes.json()) as {
              access_token?: string;
              error?: { message?: string };
            };
            if (!tokRes.ok || !tokJson.access_token) {
              return back(
                `instagram_error:${(tokJson.error?.message ?? "token_exchange_failed").slice(0, 150)}`,
              );
            }

            // 2. Exchange for long-lived (~60-day) user token
            const llUrl = new URL(
              "https://graph.facebook.com/v21.0/oauth/access_token",
            );
            llUrl.searchParams.set("grant_type", "fb_exchange_token");
            llUrl.searchParams.set("client_id", appId);
            llUrl.searchParams.set("client_secret", appSecret);
            llUrl.searchParams.set("fb_exchange_token", tokJson.access_token);
            const llRes = await fetch(llUrl.toString());
            const llJson = (await llRes.json()) as {
              access_token?: string;
              expires_in?: number;
            };
            const longUserToken = llJson.access_token ?? tokJson.access_token;
            const expiresAt = new Date(
              Date.now() + (llJson.expires_in ?? 60 * 24 * 3600) * 1000,
            );

            // 3. Find a Page with a linked IG business account
            const pagesRes = await fetch(
              `https://graph.facebook.com/v21.0/me/accounts?fields=id,name,access_token,instagram_business_account&access_token=${encodeURIComponent(longUserToken)}`,
            );
            const pagesJson = (await pagesRes.json()) as {
              data?: Array<{
                id: string;
                name: string;
                access_token: string;
                instagram_business_account?: { id: string };
              }>;
            };
            const page = (pagesJson.data ?? []).find(
              (p) => p.instagram_business_account?.id,
            );
            if (!page) {
              return back(
                "instagram_error:No Instagram Business account linked to a Facebook Page on this login.",
              );
            }
            const igId = page.instagram_business_account!.id;

            // 4. Fetch handle
            const igRes = await fetch(
              `https://graph.facebook.com/v21.0/${igId}?fields=username&access_token=${encodeURIComponent(page.access_token)}`,
            );
            const igJson = (await igRes.json()) as { username?: string };
            const handle = igJson.username ?? "instagram";

            // 5. Upsert social_accounts row. Page token (long-lived, doesn't expire) is what publishes IG.
            const { data: existing } = await supabaseAdmin
              .from("social_accounts")
              .select("id")
              .eq("user_id", payload.userId)
              .eq("platform", "instagram")
              .eq("platform_account_id", igId)
              .maybeSingle();

            const row = {
              user_id: payload.userId,
              platform: "instagram" as const,
              handle,
              platform_account_id: igId,
              access_token_encrypted: encryptToken(page.access_token),
              expires_at: expiresAt.toISOString(),
              active: true,
            };

            if (existing) {
              const { error } = await supabaseAdmin
                .from("social_accounts")
                .update(row)
                .eq("id", existing.id);
              if (error) return back(`instagram_error:${error.message}`);
            } else {
              const { error } = await supabaseAdmin
                .from("social_accounts")
                .insert(row);
              if (error) return back(`instagram_error:${error.message}`);
            }
            return back("instagram_connected");
          } catch (e) {
            const m = e instanceof Error ? e.message : String(e);
            return back(`instagram_error:${m.slice(0, 150)}`);
          }
        }

        return back(`${platform}_error:unsupported`);
      },
    },
  },
});
