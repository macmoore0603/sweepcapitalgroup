import type { Platform } from "../types";
import { publishInstagram } from "./instagram";

export type PublishInput = {
  body: string;
  mediaUrls: string[];
  accessTokenCipher: Buffer | Uint8Array | null;
  platformAccountId: string | null;
};

export type PublishResult = {
  ok: boolean;
  platformPostId?: string;
  platformPostUrl?: string;
  error?: string;
};

export async function publishToPlatform(
  platform: Platform,
  input: PublishInput,
): Promise<PublishResult> {
  if (!input.accessTokenCipher || !input.platformAccountId) {
    return {
      ok: false,
      error: `${platform} account not connected. Run OAuth from the agent dashboard first.`,
    };
  }

  switch (platform) {
    case "instagram":
      return publishInstagram({
        body: input.body,
        mediaUrls: input.mediaUrls,
        accessTokenCipher: input.accessTokenCipher,
        igUserId: input.platformAccountId,
      });
    case "x":
    case "linkedin":
    case "tiktok":
    case "youtube":
      return {
        ok: false,
        error: `${platform} OAuth credentials not configured yet. Add the platform's API keys to enable publishing.`,
      };
  }
}
