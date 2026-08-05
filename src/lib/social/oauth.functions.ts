import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { requireSupabaseAuth } from "@/integrations/supabase/auth-middleware";
import { signState } from "./crypto";
import { createHash, randomBytes } from "crypto";

const PUBLIC_URL = "https://sweepcapitalgroup.lovable.app";

function base64url(buf: Buffer): string {
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}

function pkcePair(): { verifier: string; challenge: string } {
  const verifier = base64url(randomBytes(32));
  const challenge = base64url(createHash("sha256").update(verifier).digest());
  return { verifier, challenge };
}

export const getOAuthStartUrl = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((input) =>
    z.object({ platform: z.enum(["instagram", "x", "linkedin"]) }).parse(input),
  )
  .handler(async ({ data, context }) => {
    const { platform } = data;
    const redirectUri = `${PUBLIC_URL}/api/public/social/oauth/${platform}/callback`;

    if (platform === "instagram") {
      const state = signState({
        userId: context.userId,
        platform,
        nonce: crypto.randomUUID(),
        exp: Date.now() + 10 * 60 * 1000,
      });
      const appId = process.env.META_APP_ID;
      if (!appId) throw new Error("META_APP_ID missing");
      const scope = [
        "instagram_basic",
        "instagram_content_publish",
        "pages_show_list",
        "pages_read_engagement",
        "business_management",
      ].join(",");
      const url = new URL("https://www.facebook.com/v21.0/dialog/oauth");
      url.searchParams.set("client_id", appId);
      url.searchParams.set("redirect_uri", redirectUri);
      url.searchParams.set("state", state);
      url.searchParams.set("scope", scope);
      url.searchParams.set("response_type", "code");
      return { url: url.toString() };
    }

    if (platform === "x") {
      const clientId = process.env.X_CLIENT_ID;
      if (!clientId) throw new Error("X_CLIENT_ID missing");
      const { verifier, challenge } = pkcePair();
      const state = signState({
        userId: context.userId,
        platform,
        nonce: crypto.randomUUID(),
        codeVerifier: verifier,
        exp: Date.now() + 10 * 60 * 1000,
      });
      const url = new URL("https://twitter.com/i/oauth2/authorize");
      url.searchParams.set("response_type", "code");
      url.searchParams.set("client_id", clientId);
      url.searchParams.set("redirect_uri", redirectUri);
      url.searchParams.set("scope", "tweet.write users.read offline.access");
      url.searchParams.set("state", state);
      url.searchParams.set("code_challenge", challenge);
      url.searchParams.set("code_challenge_method", "S256");
      return { url: url.toString() };
    }

    if (platform === "linkedin") {
      const clientId = process.env.LINKEDIN_CLIENT_ID;
      if (!clientId) throw new Error("LINKEDIN_CLIENT_ID missing");
      const state = signState({
        userId: context.userId,
        platform,
        nonce: crypto.randomUUID(),
        exp: Date.now() + 10 * 60 * 1000,
      });
      const url = new URL("https://www.linkedin.com/oauth/v2/authorization");
      url.searchParams.set("response_type", "code");
      url.searchParams.set("client_id", clientId);
      url.searchParams.set("redirect_uri", redirectUri);
      url.searchParams.set("scope", "openid profile w_member_social");
      url.searchParams.set("state", state);
      return { url: url.toString() };
    }

    throw new Error(`Unsupported platform: ${platform}`);
  });
