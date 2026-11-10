#!/usr/bin/env node
// compile-check.mjs - send Pine Script files to TradingView's public compiler
// and report what it says.
//
// Usage:  node tools/compile-check.mjs <file.pine> [more.pine ...]
//
// For each file this prints every compile error and warning as
//   path:line:column  error|warning  CODE  message
// with the message's {placeholders} filled in from the compiler's ctx object.
// The exit code is 1 when any file has at least one error (or could not be
// checked at all), and 0 otherwise. Warnings never fail the run.
//
// Node 22+, ESM, no dependencies. Network access to pine-facade.tradingview.com
// is required; the same request as:
//   curl -sS -m 60 -X POST '<ENDPOINT>' -H 'Referer: https://www.tradingview.com/' \
//        --data-urlencode "source@<file.pine>"

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const ENDPOINT =
  "https://pine-facade.tradingview.com/pine-facade/translate_light" +
  "?user_name=Guest&pine_id=00000000-0000-0000-0000-000000000000";
const TIMEOUT_MS = 60_000;

/** Replace {name} placeholders with values from ctx; unknown names stay as-is. */
export function fillMessage(template, ctx) {
  const text = String(template ?? "");
  if (!ctx || typeof ctx !== "object") return text;
  return text.replace(/\{([A-Za-z0-9_]+)\}/g, (whole, key) =>
    Object.prototype.hasOwnProperty.call(ctx, key) ? String(ctx[key]) : whole,
  );
}

/** Turn one errors2/warnings2 entry into a printable line. */
export function formatDiagnostic(file, kind, d) {
  const line = d?.start?.line ?? "?";
  const col = d?.start?.column ?? "?";
  const code = d?.code ? ` ${d.code}` : "";
  return `${file}:${line}:${col}  ${kind}${code}  ${fillMessage(d?.message, d?.ctx)}`;
}

async function compile(source) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(ENDPOINT, {
      method: "POST",
      headers: {
        Referer: "https://www.tradingview.com/",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({ source }).toString(),
      signal: controller.signal,
    });
    const body = await res.text();
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${body.slice(0, 300)}`);
    let json;
    try {
      json = JSON.parse(body);
    } catch {
      throw new Error(`compiler returned non-JSON: ${body.slice(0, 300)}`);
    }
    return json;
  } finally {
    clearTimeout(timer);
  }
}

async function checkFile(path) {
  const source = await readFile(resolve(path), "utf8");
  const json = await compile(source);
  if (!json || json.success === false || !json.result) {
    const reason = json?.reason ?? json?.error ?? JSON.stringify(json).slice(0, 300);
    return { errors: [`${path}:?:?  error  compiler request failed: ${reason}`], warnings: [] };
  }
  const errs = Array.isArray(json.result.errors2) ? json.result.errors2 : [];
  const warns = Array.isArray(json.result.warnings2) ? json.result.warnings2 : [];
  return {
    errors: errs.map((d) => formatDiagnostic(path, "error", d)),
    warnings: warns.map((d) => formatDiagnostic(path, "warning", d)),
  };
}

async function main(argv) {
  const files = argv.slice(2);
  if (files.length === 0 || files.includes("-h") || files.includes("--help")) {
    console.error("Usage: node tools/compile-check.mjs <file.pine> [more.pine ...]");
    return 2;
  }
  let failed = false;
  for (const file of files) {
    let result;
    try {
      result = await checkFile(file);
    } catch (err) {
      result = { errors: [`${file}:?:?  error  ${err?.message ?? err}`], warnings: [] };
    }
    for (const line of result.errors) console.log(line);
    for (const line of result.warnings) console.log(line);
    const status = result.errors.length === 0 ? "OK" : "FAIL";
    console.log(
      `${file}: ${status} (errors=${result.errors.length}, warnings=${result.warnings.length})`,
    );
    if (result.errors.length > 0) failed = true;
  }
  return failed ? 1 : 0;
}

const isMain = process.argv[1] !== undefined && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isMain) {
  main(process.argv).then(
    (code) => process.exit(code),
    (err) => {
      console.error(err?.stack ?? String(err));
      process.exit(1);
    },
  );
}
