import type { Platform } from "../types";
import { publishInstagram } from "./instagram";
import { publishX } from "./x";
import { publishLinkedIn } from "./linkedin";

export type PublishInput = {
  body: string;
  mediaUrls: string[];
  accessTokenCipher: string | null;
  refreshTokenCipher?: string | null;
  expiresAt?: string | null;
  platformAccountId: string | null;
};

export type PublishResult = {
  ok: boolean;
  platformPostId?: string;
  platformPostUrl?: string;
  error?: string;
  refreshedAccessToken?: string;
  refreshedRefreshToken?: string;
  refreshedExpiresAt?: string;
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
      return publishX({
        body: input.body,
        mediaUrls: input.mediaUrls,
        accessTokenCipher: input.accessTokenCipher,
        refreshTokenCipher: input.refreshTokenCipher,
        expiresAt: input.expiresAt,
      });
    case "linkedin":
      return publishLinkedIn({
        body: input.body,
        mediaUrls: input.mediaUrls,
        accessTokenCipher: input.accessTokenCipher,
        refreshTokenCipher: input.refreshTokenCipher,
        expiresAt: input.expiresAt,
      });
    case "tiktok":
    case "youtube":
      return {
        ok: false,
        error: `${platform} OAuth credentials not configured yet. Add the platform's API keys to enable publishing.`,
      };
  }
}
