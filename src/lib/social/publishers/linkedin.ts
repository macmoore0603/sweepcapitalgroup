import { decryptTokenFromDb, encryptTokenToDb } from "../crypto";

export async function publishLinkedIn(opts: {
  body: string;
  mediaUrls: string[];
  accessTokenCipher: string;
  refreshTokenCipher?: string | null;
  expiresAt?: string | null;
}): Promise<{
  ok: boolean;
  platformPostId?: string;
  platformPostUrl?: string;
  error?: string;
  refreshedAccessToken?: string;
  refreshedRefreshToken?: string;
  refreshedExpiresAt?: string;
}> {
  try {
    if (opts.mediaUrls.length > 0) {
      return {
        ok: false,
        error:
          "LinkedIn media posts require image asset registration and are not implemented yet. Schedule text-only posts or omit media_urls.",
      };
    }

    let accessToken = decryptTokenFromDb(opts.accessTokenCipher);
    const refreshToken = opts.refreshTokenCipher
      ? decryptTokenFromDb(opts.refreshTokenCipher)
      : undefined;
    let latestRefreshToken = refreshToken;

    const expiresAt = opts.expiresAt ? new Date(opts.expiresAt).getTime() : 0;
    const needsRefresh = Boolean(refreshToken) && (!expiresAt || expiresAt < Date.now() + 5 * 60 * 1000);

    if (needsRefresh && refreshToken) {
      const refreshed = await refreshLinkedInToken(refreshToken);
      if (!refreshed.ok || !refreshed.accessToken) {
        return { ok: false, error: `LinkedIn token refresh failed: ${refreshed.error ?? "no token"}` };
      }
      accessToken = refreshed.accessToken;
      if (refreshed.refreshToken) latestRefreshToken = refreshed.refreshToken;
    }

    // Fetch the authenticated member's person URN
    const meRes = await fetch("https://api.linkedin.com/v2/userinfo", {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    const meJson = (await meRes.json()) as { sub?: string; error?: string };
    if (!meRes.ok || !meJson.sub) {
      return {
        ok: false,
        error: `LinkedIn profile lookup failed: ${meJson.error ?? JSON.stringify(meJson).slice(0, 200)}`,
      };
    }

    const res = await fetch("https://api.linkedin.com/rest/posts", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
        "LinkedIn-Version": "202404",
        "X-Restli-Protocol-Version": "2.0.0",
      },
      body: JSON.stringify({
        author: `urn:li:person:${meJson.sub}`,
        lifecycleState: "PUBLISHED",
        visibility: "PUBLIC",
        commentary: opts.body,
        distribution: {
          feedDistribution: "MAIN_FEED",
          targetEntities: [],
          thirdPartyDistributionChannels: [],
        },
      }),
    });

    if (!res.ok) {
      const text = await res.text();
      return { ok: false, error: `LinkedIn publish: ${text.slice(0, 200)}` };
    }

    // LinkedIn returns the post URN in the Location header or x-restli-id header
    const postUrn = res.headers.get("x-restli-id") ?? res.headers.get("Location")?.split("/").pop();

    return {
      ok: true,
      platformPostId: postUrn ?? undefined,
      platformPostUrl: postUrn
        ? `https://www.linkedin.com/feed/update/${postUrn}`
        : undefined,
      ...(needsRefresh && latestRefreshToken
        ? {
            refreshedAccessToken: encryptTokenToDb(accessToken),
            refreshedRefreshToken: encryptTokenToDb(latestRefreshToken),
          }
        : {}),
    };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

async function refreshLinkedInToken(refreshToken: string): Promise<{
  ok: boolean;
  accessToken?: string;
  refreshToken?: string;
  expiresAt?: Date;
  error?: string;
}> {
  const clientId = process.env.LINKEDIN_CLIENT_ID;
  const clientSecret = process.env.LINKEDIN_CLIENT_SECRET;
  if (!clientId || !clientSecret) {
    return { ok: false, error: "LINKEDIN_CLIENT_ID or LINKEDIN_CLIENT_SECRET missing" };
  }

  const res = await fetch("https://www.linkedin.com/oauth/v2/accessToken", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id: clientId,
      client_secret: clientSecret,
    }).toString(),
  });

  const json = (await res.json()) as {
    access_token?: string;
    refresh_token?: string;
    expires_in?: number;
    error?: string;
    error_description?: string;
  };

  if (!res.ok || !json.access_token) {
    return {
      ok: false,
      error: json.error_description ?? json.error ?? JSON.stringify(json).slice(0, 200),
    };
  }

  return {
    ok: true,
    accessToken: json.access_token,
    refreshToken: json.refresh_token,
    expiresAt: new Date(Date.now() + (json.expires_in ?? 7200) * 1000),
  };
}
