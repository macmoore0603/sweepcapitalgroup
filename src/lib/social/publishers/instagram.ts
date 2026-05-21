import { decryptTokenFromDb } from "../crypto";

export async function publishInstagram(opts: {
  body: string;
  mediaUrls: string[];
  accessTokenCipher: string;
  igUserId: string;
}): Promise<{
  ok: boolean;
  platformPostId?: string;
  platformPostUrl?: string;
  error?: string;
}> {
  try {
    const token = decryptTokenFromDb(opts.accessTokenCipher);

    if (!opts.mediaUrls.length) {
      return {
        ok: false,
        error:
          "Instagram requires an image or video URL. Add media_urls before scheduling.",
      };
    }

    // Phase 1: single image. Carousel/video use the same endpoints with extra params later.
    const mediaUrl = opts.mediaUrls[0];

    const containerRes = await fetch(
      `https://graph.facebook.com/v21.0/${opts.igUserId}/media`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_url: mediaUrl,
          caption: opts.body,
          access_token: token,
        }),
      },
    );
    const containerJson = (await containerRes.json()) as {
      id?: string;
      error?: { message?: string };
    };
    if (!containerRes.ok || !containerJson.id) {
      return {
        ok: false,
        error: `IG container: ${containerJson.error?.message ?? JSON.stringify(containerJson).slice(0, 200)}`,
      };
    }

    const publishRes = await fetch(
      `https://graph.facebook.com/v21.0/${opts.igUserId}/media_publish`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          creation_id: containerJson.id,
          access_token: token,
        }),
      },
    );
    const publishJson = (await publishRes.json()) as {
      id?: string;
      error?: { message?: string };
    };
    if (!publishRes.ok || !publishJson.id) {
      return {
        ok: false,
        error: `IG publish: ${publishJson.error?.message ?? JSON.stringify(publishJson).slice(0, 200)}`,
      };
    }

    // Fetch permalink (best-effort).
    let permalink: string | undefined;
    try {
      const linkRes = await fetch(
        `https://graph.facebook.com/v21.0/${publishJson.id}?fields=permalink&access_token=${encodeURIComponent(token)}`,
      );
      const linkJson = (await linkRes.json()) as { permalink?: string };
      permalink = linkJson.permalink;
    } catch {
      // ignore
    }

    return {
      ok: true,
      platformPostId: publishJson.id,
      platformPostUrl: permalink,
    };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
}
