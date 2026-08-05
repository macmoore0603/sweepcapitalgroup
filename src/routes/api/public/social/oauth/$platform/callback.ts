import { createFileRoute } from "@tanstack/react-router";
import { supabaseAdmin } from "@/integrations/supabase/client.server";
import { encryptTokenToDb, verifyState } from "@/lib/social/crypto";

const PUBLIC_URL = "https://sweepcapitalgroup.lovable.app";

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
          codeVerifier?: string;
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
              access_token_encrypted: encryptTokenToDb(page.access_token),
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

        if (platform === "x") {
          try {
            const clientId = process.env.X_CLIENT_ID;
            const clientSecret = process.env.X_CLIENT_SECRET;
            if (!clientId || !clientSecret) {
              return back("x_error:x_credentials_missing");
            }
            if (!payload.codeVerifier) {
              return back("x_error:missing_pkce_verifier");
            }

            const basic = Buffer.from(`${clientId}:${clientSecret}`).toString("base64");
            const tokenRes = await fetch("https://api.twitter.com/2/oauth2/token", {
              method: "POST",
              headers: {
                Authorization: `Basic ${basic}`,
                "Content-Type": "application/x-www-form-urlencoded",
              },
              body: new URLSearchParams({
                code,
                grant_type: "authorization_code",
                redirect_uri: redirectUri,
                code_verifier: payload.codeVerifier,
              }).toString(),
            });
            const tokenJson = (await tokenRes.json()) as {
              access_token?: string;
              refresh_token?: string;
              expires_in?: number;
              scope?: string;
              error?: string;
              error_description?: string;
            };
            if (!tokenRes.ok || !tokenJson.access_token) {
              return back(
                `x_error:${(tokenJson.error_description ?? tokenJson.error ?? "token_exchange_failed").slice(0, 150)}`,
              );
            }

            // Fetch user handle
            const meRes = await fetch(
              "https://api.twitter.com/2/users/me?user.fields=username",
              {
                headers: { Authorization: `Bearer ${tokenJson.access_token}` },
              },
            );
            const meJson = (await meRes.json()) as {
              data?: { id?: string; username?: string };
              errors?: Array<{ message?: string }>;
            };
            const userId = meJson.data?.id;
            const handle = meJson.data?.username ?? "x";
            if (!userId) {
              return back(
                `x_error:${(meJson.errors?.[0]?.message ?? "user_lookup_failed").slice(0, 150)}`,
              );
            }

            const expiresAt = new Date(
              Date.now() + (tokenJson.expires_in ?? 7200) * 1000,
            );

            const { data: existing } = await supabaseAdmin
              .from("social_accounts")
              .select("id")
              .eq("user_id", payload.userId)
              .eq("platform", "x")
              .eq("platform_account_id", userId)
              .maybeSingle();

            const row = {
              user_id: payload.userId,
              platform: "x" as const,
              handle,
              platform_account_id: userId,
              access_token_encrypted: encryptTokenToDb(tokenJson.access_token),
              refresh_token_encrypted: tokenJson.refresh_token
                ? encryptTokenToDb(tokenJson.refresh_token)
                : null,
              expires_at: expiresAt.toISOString(),
              scopes: tokenJson.scope ? tokenJson.scope.split(" ") : ["tweet.write", "users.read", "offline.access"],
              active: true,
            };

            if (existing) {
              const { error } = await supabaseAdmin
                .from("social_accounts")
                .update(row)
                .eq("id", existing.id);
              if (error) return back(`x_error:${error.message}`);
            } else {
              const { error } = await supabaseAdmin.from("social_accounts").insert(row);
              if (error) return back(`x_error:${error.message}`);
            }
            return back("x_connected");
          } catch (e) {
            const m = e instanceof Error ? e.message : String(e);
            return back(`x_error:${m.slice(0, 150)}`);
          }
        }

        if (platform === "linkedin") {
          try {
            const clientId = process.env.LINKEDIN_CLIENT_ID;
            const clientSecret = process.env.LINKEDIN_CLIENT_SECRET;
            if (!clientId || !clientSecret) {
              return back("linkedin_error:linkedin_credentials_missing");
            }

            const tokenRes = await fetch(
              "https://www.linkedin.com/oauth/v2/accessToken",
              {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: new URLSearchParams({
                  grant_type: "authorization_code",
                  code,
                  redirect_uri: redirectUri,
                  client_id: clientId,
                  client_secret: clientSecret,
                }).toString(),
              },
            );
            const tokenJson = (await tokenRes.json()) as {
              access_token?: string;
              refresh_token?: string;
              expires_in?: number;
              scope?: string;
              error?: string;
              error_description?: string;
            };
            if (!tokenRes.ok || !tokenJson.access_token) {
              return back(
                `linkedin_error:${(tokenJson.error_description ?? tokenJson.error ?? "token_exchange_failed").slice(0, 150)}`,
              );
            }

            // Fetch OpenID user info
            const meRes = await fetch("https://api.linkedin.com/v2/userinfo", {
              headers: { Authorization: `Bearer ${tokenJson.access_token}` },
            });
            const meJson = (await meRes.json()) as {
              sub?: string;
              name?: string;
              preferred_username?: string;
              email?: string;
              error?: string;
            };
            const personId = meJson.sub;
            if (!personId) {
              return back(
                `linkedin_error:${(meJson.error ?? "user_lookup_failed").slice(0, 150)}`,
              );
            }
            const handle = meJson.preferred_username ?? meJson.name ?? "linkedin";

            const expiresAt = new Date(
              Date.now() + (tokenJson.expires_in ?? 7200) * 1000,
            );

            const { data: existing } = await supabaseAdmin
              .from("social_accounts")
              .select("id")
              .eq("user_id", payload.userId)
              .eq("platform", "linkedin")
              .eq("platform_account_id", personId)
              .maybeSingle();

            const row = {
              user_id: payload.userId,
              platform: "linkedin" as const,
              handle,
              platform_account_id: personId,
              access_token_encrypted: encryptTokenToDb(tokenJson.access_token),
              refresh_token_encrypted: tokenJson.refresh_token
                ? encryptTokenToDb(tokenJson.refresh_token)
                : null,
              expires_at: expiresAt.toISOString(),
              scopes: tokenJson.scope ? tokenJson.scope.split(" ") : ["openid", "profile", "w_member_social"],
              active: true,
            };

            if (existing) {
              const { error } = await supabaseAdmin
                .from("social_accounts")
                .update(row)
                .eq("id", existing.id);
              if (error) return back(`linkedin_error:${error.message}`);
            } else {
              const { error } = await supabaseAdmin.from("social_accounts").insert(row);
              if (error) return back(`linkedin_error:${error.message}`);
            }
            return back("linkedin_connected");
          } catch (e) {
            const m = e instanceof Error ? e.message : String(e);
            return back(`linkedin_error:${m.slice(0, 150)}`);
          }
        }

        return back(`${platform}_error:unsupported`);
      },
    },
  },
});
