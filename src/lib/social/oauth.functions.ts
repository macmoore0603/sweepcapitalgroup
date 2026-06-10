import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { requireSupabaseAuth } from "@/integrations/supabase/auth-middleware";
import { signState } from "./crypto";

const PUBLIC_URL = "https://sweepcapitalgroup.lovable.app";

export const getOAuthStartUrl = createServerFn({ method: "POST" })
  .middleware([requireSupabaseAuth])
  .inputValidator((input) =>
    z.object({ platform: z.enum(["instagram"]) }).parse(input),
  )
  .handler(async ({ data, context }) => {
    const { platform } = data;
    const state = signState({
      userId: context.userId,
      platform,
      nonce: crypto.randomUUID(),
      exp: Date.now() + 10 * 60 * 1000,
    });
    const redirectUri = `${PUBLIC_URL}/api/public/social/oauth/${platform}/callback`;

    if (platform === "instagram") {
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
    throw new Error(`Unsupported platform: ${platform}`);
  });
