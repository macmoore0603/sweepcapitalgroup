import type { Platform } from "../types";

export type PublishInput = {
  body: string;
  mediaUrls: string[];
  accessToken: string | null;
  platformAccountId: string | null;
};

export type PublishResult = {
  ok: boolean;
  platformPostId?: string;
  platformPostUrl?: string;
  error?: string;
};

async function notConfigured(platform: Platform): Promise<PublishResult> {
  return {
    ok: false,
    error: `${platform} credentials not configured. Add the OAuth app secrets and connect an account first.`,
  };
}

export async function publishToPlatform(
  platform: Platform,
  input: PublishInput,
): Promise<PublishResult> {
  if (!input.accessToken) return notConfigured(platform);

  // Phase 1: every publisher is stubbed and returns a configuration error.
  // Phase 2 adds real Graph / X v2 / LinkedIn / TikTok / YouTube calls.
  switch (platform) {
    case "instagram":
    case "x":
    case "linkedin":
    case "tiktok":
    case "youtube":
      return notConfigured(platform);
  }
}
