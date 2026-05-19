import type { Platform } from "./types";

const FORBIDDEN_PHRASES = [
  /\bguaranteed\b/i,
  /\brisk[\s-]?free\b/i,
  /\bdouble your money\b/i,
  /\bget rich\b/i,
  /\b\d+\s*%\s*(returns?|gain|profit)\b/i,
  /\bguaranteed returns?\b/i,
];

const METHODOLOGY_TRIGGERS =
  /\b(trade|trading|capital|funded|profit|win rate|account|methodology|strategy|results)\b/i;

const AUDITED_STAT_PATTERN = /\b\d{1,3}(\.\d+)?\s*%\s*(win rate|return)\b/i;
const AUDITED_QUALIFIER = /audited.*past performance/i;

export type GuardrailResult = {
  ok: boolean;
  violations: string[];
  warnings: string[];
  sanitized: string;
};

export function runGuardrails(platform: Platform, raw: string): GuardrailResult {
  const violations: string[] = [];
  const warnings: string[] = [];
  let text = raw.trim();

  for (const re of FORBIDDEN_PHRASES) {
    if (re.test(text)) violations.push(`Forbidden phrase: ${re.source}`);
  }

  const emojiMatches = text.match(/\p{Extended_Pictographic}/gu) ?? [];
  if (emojiMatches.length > 2) violations.push(`Too many emojis (${emojiMatches.length}, max 2)`);

  const exclam = (text.match(/!/g) ?? []).length;
  if (exclam > 1) violations.push(`Too many exclamation marks (${exclam}, max 1)`);

  const capsLines = text
    .split(/\n+/)
    .filter((l) => l.trim().length > 6 && l === l.toUpperCase() && /[A-Z]/.test(l));
  if (capsLines.length > 0) violations.push("All-caps line detected");

  if (AUDITED_STAT_PATTERN.test(text) && !AUDITED_QUALIFIER.test(text)) {
    violations.push("Performance stat missing audited qualifier");
  }

  if (METHODOLOGY_TRIGGERS.test(text)) {
    const required =
      platform === "x" ? "Not financial advice." : "Educational content. Not financial advice.";
    if (!text.includes(required)) {
      text = `${text}\n\n${required}`;
      warnings.push(`Appended disclaimer for ${platform}`);
    }
  }

  if (platform === "x" && text.length > 280) {
    violations.push(`X post exceeds 280 characters (${text.length})`);
  }
  if (platform === "linkedin" && text.length > 3000) {
    violations.push(`LinkedIn post exceeds 3000 characters (${text.length})`);
  }

  return {
    ok: violations.length === 0,
    violations,
    warnings,
    sanitized: text,
  };
}
