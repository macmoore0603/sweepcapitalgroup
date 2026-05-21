// Server-only crypto helpers for social OAuth.
// AES-256-GCM at rest for tokens, HMAC-signed JSON for OAuth `state`.

import {
  createCipheriv,
  createDecipheriv,
  createHmac,
  randomBytes,
  scryptSync,
} from "crypto";

function tokenKey(): Buffer {
  const k = process.env.SOCIAL_TOKEN_KEY;
  if (!k) throw new Error("SOCIAL_TOKEN_KEY missing");
  return scryptSync(k, "lnc-social-v1", 32);
}

export function encryptToken(plain: string): Buffer {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", tokenKey(), iv);
  const enc = Buffer.concat([cipher.update(plain, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([iv, tag, enc]); // 12 + 16 + N
}

export function decryptToken(buf: Buffer | Uint8Array): string {
  const b = Buffer.from(buf);
  const iv = b.subarray(0, 12);
  const tag = b.subarray(12, 28);
  const enc = b.subarray(28);
  const decipher = createDecipheriv("aes-256-gcm", tokenKey(), iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(enc), decipher.final()]).toString("utf8");
}

// PostgREST round-trips bytea as a hex string (`\x...`). Use these wrappers
// so callers can stay string-typed end to end.
export function encryptTokenToDb(plain: string): string {
  return "\\x" + encryptToken(plain).toString("hex");
}

export function decryptTokenFromDb(stored: string | Uint8Array | null | undefined): string {
  if (!stored) throw new Error("no token stored");
  if (typeof stored === "string") {
    const hex = stored.startsWith("\\x") ? stored.slice(2) : stored;
    return decryptToken(Buffer.from(hex, "hex"));
  }
  return decryptToken(stored);
}

export function signState(payload: Record<string, unknown>): string {
  const k = process.env.SOCIAL_TOKEN_KEY;
  if (!k) throw new Error("SOCIAL_TOKEN_KEY missing");
  const body = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const sig = createHmac("sha256", k).update(body).digest("base64url");
  return `${body}.${sig}`;
}

export function verifyState<T = Record<string, unknown>>(token: string): T | null {
  const k = process.env.SOCIAL_TOKEN_KEY;
  if (!k) return null;
  const [body, sig] = token.split(".");
  if (!body || !sig) return null;
  const expected = createHmac("sha256", k).update(body).digest("base64url");
  if (expected.length !== sig.length || expected !== sig) return null;
  try {
    const parsed = JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as {
      exp?: number;
    };
    if (parsed.exp && parsed.exp < Date.now()) return null;
    return parsed as T;
  } catch {
    return null;
  }
}
