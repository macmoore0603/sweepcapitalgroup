import { decryptTokenFromDb, encryptTokenToDb } from "../crypto";

export async function publishX(opts: {
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
          "X media uploads require the v1.1 media API and are not implemented yet. Schedule text-only posts or omit media_urls.",
      };
    }

    let accessToken = decryptTokenFromDb(opts.accessTokenCipher);
    let refreshToken = opts.refreshTokenCipher
      ? decryptTokenFromDb(opts.refreshTokenCipher)
      : undefined;

    const expiresAt = opts.expiresAt ? new Date(opts.expiresAt).getTime() : 0;
    const needsRefresh = refreshToken && (!expiresAt || expiresAt < Date.now() + 5 * 60 * 1000);

    if (needsRefresh) {
      const refreshed = await refreshXToken(refreshToken);
      if (!refreshed.ok) {
        return { ok: false, error: `X token refresh failed: ${refreshed.error}` };
      }
      accessToken = refreshed.accessToken;
      refreshToken = refreshed.refreshToken ?? refreshToken;
    }

    const res = await fetch("https://api.twitter.com/2/tweets", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ text: opts.body }),
    });
    const json = (await res.json()) as {
      data?: { id?: string; text?: string };
      errors?: Array<{ message?: string; detail?: string }>;
    };

    if (!res.ok) {
      const msg = json.errors?.[0]?.message ?? JSON.stringify(json).slice(0, 200);
      return { ok: false, error: `X publish: ${msg}` };
    }

    const id = json.data?.id;
    if (!id) return { ok: false, error: "X publish: no tweet id returned" };

    return {
      ok: true,
      platformPostId: id,
      platformPostUrl: `https://x.com/i/web/status/${id}`,
      ...(needsRefresh && refreshToken
        ? {
            refreshedAccessToken: encryptTokenToDb(accessToken),
            refreshedRefreshToken: refreshToken ? encryptTokenToDb(refreshToken) : undefined,
          }
        : {}),
    };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}

async function refreshXToken(refreshToken: string): Promise<{
  ok: boolean;
  accessToken?: string;
  refreshToken?: string;
  expiresAt?: Date;
  error?: string;
}> {
  const clientId = process.env.X_CLIENT_ID;
  const clientSecret = process.env.X_CLIENT_SECRET;
  if (!clientId || !clientSecret) {
    return { ok: false, error: "X_CLIENT_ID or X_CLIENT_SECRET missing" };
  }

  const basic = Buffer.from(`${clientId}:${clientSecret}`).toString("base64");
  const res = await fetch("https://api.twitter.com/2/oauth2/token", {
    method: "POST",
    headers: {
      Authorization: `Basic ${basic}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id: clientId,
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
