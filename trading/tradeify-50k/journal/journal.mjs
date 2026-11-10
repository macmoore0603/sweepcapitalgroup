#!/usr/bin/env node
// journal.mjs - a prediction journal for MNQ / NQ calls on a Tradeify 50K Growth account.
//   add:   write a call down BEFORE the move (paper or live); it is checked and appended to a CSV.
//   score: grade every call against real bars with fixed, conservative rules, then summarize.
// Node 22, no dependencies. Run `node journal.mjs` for usage. Times are America/New_York.

import { readFileSync, writeFileSync, appendFileSync, existsSync } from 'node:fs';
import { basename } from 'node:path';
import { fileURLToPath } from 'node:url';

export const COLUMNS = ['id', 'time_et', 'symbol', 'side', 'entry', 'stop', 'target', 'size', 'mode', 'note'];
// pointValue in $ per point; cost = default round-trip commission per contract; maxSize = Growth 50K limit;
// mnq = MNQ-equivalent contracts per contract, for the combined limit (4 NQ or 40 MNQ).
export const SYMBOLS = {
  MNQ: { pointValue: 2, cost: 0.5, maxSize: 40, mnq: 1 },
  NQ: { pointValue: 20, cost: 1.5, maxSize: 4, mnq: 10 },
};
export const MAX_MNQ = 40;
export const FILL_WAIT_MIN = 30;
export const FLAT_BY = { h: 16, mi: 45 };
export const SESSION_START_HOUR = 18;
export const MAX_ROOM = 2000; // the trailing drawdown: room to the floor does not grow past this
export const MAX_BAR_MIN = 5;
export const FAR_ENTRY = 0.005; // a NOT FILLED entry this far (0.5%) from every price in its window may be the wrong contract
export const BOOTSTRAP = { resamples: 2000, seed: 1 };
export const MIN_CALLS_TO_JUDGE = 30;
const GRADED = new Set(['STOP', 'TARGET', 'FLAT']);
const NY = 'America/New_York';
const MINUTE = 60000;
const STAMP = /\[added (\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}) ET\]\s*$/;

export const RULES = [
  'Start: a call is live from the first bar that opens after the minute it was written (at or after its time + 1 minute), so no bar the trader could already see is used. On 5-minute bars a fill in the minutes between the call and the next bar is not seen; 1-minute bars show it.',
  'Fill: it fills when, within 30 minutes of the call, a bar touches the entry or price jumps over the entry between bars (the last close on one side, the next open on the other). A jump fills at the worse of the entry and that open. If not, the call is NOT FILLED and left out of the stats. If price jumped over the entry and the stop together, the call counts as filled at the entry and stopped at that open.',
  'Exit: a bar touching the stop is a STOP, at the stop (or at the bar\'s open if it gapped past). A bar touching the target is a TARGET, at the target. Stop and target in the same bar count as a STOP, because the order inside a bar is unknown (unless the bar opened past the target). On the fill bar a stop touch counts; a target touch counts only if price was already moving toward the target (the bar opened at or on the stop side of the entry, or the fill was at that open). A touch counts as a fill, which is optimistic for a resting limit: targets that were only touched are marked.',
  'Flat: still open at 16:45 ET, the call exits FLAT at the close of the last bar that ends by 16:45. A session runs 18:00 to 17:00 ET, so a call at or after 18:00 belongs to the next day. If the bars end first, the call is OPEN and left out of the stats.',
  'Money: $ = points x $2 (MNQ) or $20 (NQ) x size, minus cost x size. R = $ / the $ at risk (entry-to-stop points x point value x size), so commissions count against it; R before commissions is shown too. Fills are exact, with no slippage.',
  'Room: from your room to the floor (it never grows past $2,000, since the floor trails), every bar is walked in time order: the room left after closed trades plus the open P&L of every filled call at that bar\'s worst price, so calls open together add up. A closed trade is credited at its exit bar. The walk stops at the first breach.',
  'Counting: rows with the same time, side, entry and stop (split targets) are one idea, at their risk-weighted R; the stats and the 30-call minimum count ideas. A call stamped as added after its time is hindsight: it is listed but left out of every figure.',
];

// ---------- New York time (Intl only) ----------

const nyFormat = new Intl.DateTimeFormat('en-US', {
  timeZone: NY, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric',
});
const pad = (n) => String(n).padStart(2, '0');

function nyParts(ms) {
  const o = {};
  for (const p of nyFormat.formatToParts(new Date(ms))) if (p.type !== 'literal') o[p.type] = Number(p.value);
  return { y: o.year, m: o.month, d: o.day, h: o.hour % 24, mi: o.minute };
}

/** UTC ms of a New York wall-clock time; null if it does not exist (spring-forward). Fall-back picks EDT. */
export function nyToUtc(y, m, d, h, mi) {
  const asUtc = Date.UTC(y, m - 1, d, h, mi);
  for (const offsetHours of [4, 5]) {
    const ms = asUtc + offsetHours * 3600000;
    const p = nyParts(ms);
    if (p.y === y && p.m === m && p.d === d && p.h === h && p.mi === mi) return ms;
  }
  return null;
}

/** "YYYY-MM-DD HH:MM" in New York. */
export function formatEt(ms) {
  const p = nyParts(ms);
  return `${p.y}-${pad(p.m)}-${pad(p.d)} ${pad(p.h)}:${pad(p.mi)}`;
}

/** Parse a call time "YYYY-MM-DD HH:MM" (New York) -> { ms, session, flatByMs }. Throws a plain-language error. */
export function parseCallTime(text) {
  const s = String(text ?? '').trim();
  const m = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})$/.exec(s);
  if (!m) throw new Error(`time "${s}" must look like "2026-10-14 13:05" (New York time, 24-hour clock)`);
  const [y, mo, d, h, mi] = m.slice(1).map(Number);
  const cal = new Date(Date.UTC(y, mo - 1, d));
  if (cal.getUTCMonth() !== mo - 1 || cal.getUTCDate() !== d || h > 23 || mi > 59) throw new Error(`time "${s}" is not a real date and time`);
  const ms = nyToUtc(y, mo, d, h, mi);
  if (ms == null) throw new Error(`time "${s}" does not exist in New York (the clocks jump forward an hour that night)`);
  const day = new Date(Date.UTC(y, mo - 1, d + (h >= SESSION_START_HOUR ? 1 : 0)));
  if (day.getUTCDay() === 0 || day.getUTCDay() === 6) throw new Error(`time "${s}" is outside the futures week, which runs Sunday 18:00 to Friday 17:00 ET`);
  if (h * 60 + mi >= FLAT_BY.h * 60 + FLAT_BY.mi && h < SESSION_START_HOUR) throw new Error(`time "${s}" is between the 16:45 ET flat-by and the 18:00 ET session start, when no trade may be open`);
  const [sy, sm, sd] = [day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate()];
  return { ms, session: `${sy}-${pad(sm)}-${pad(sd)}`, flatByMs: nyToUtc(sy, sm, sd, FLAT_BY.h, FLAT_BY.mi) };
}

// ---------- calls ----------

function price(value, name, errs) {
  const s = String(value ?? '').trim();
  const x = s === '' ? NaN : Number(s);
  if (!Number.isFinite(x) || x <= 0) errs.push(`${name} must be a price above 0, got "${s}"`);
  else if (Math.abs(x * 4 - Math.round(x * 4)) > 1e-9) errs.push(`${name} ${s} is not a whole tick (NQ and MNQ move in 0.25 steps)`);
  return x;
}

/** Check one call (strings from the CLI or the CSV). Returns the normalized call or throws every problem found. */
export function validateCall(raw) {
  const errs = [];
  let t = null;
  try { t = parseCallTime(raw.time_et); } catch (e) { errs.push(e.message); }
  const symbol = String(raw.symbol ?? '').trim().toUpperCase();
  if (!SYMBOLS[symbol]) errs.push(`symbol must be MNQ or NQ, got "${raw.symbol ?? ''}"`);
  const side = String(raw.side ?? '').trim().toLowerCase();
  if (side !== 'long' && side !== 'short') errs.push(`side must be long or short, got "${raw.side ?? ''}"`);
  const entry = price(raw.entry, 'entry', errs);
  const stop = price(raw.stop, 'stop', errs);
  const target = price(raw.target, 'target', errs);
  if (side === 'long') {
    if (stop >= entry) errs.push(`a long's stop (${stop}) must be below its entry (${entry})`);
    if (target <= entry) errs.push(`a long's target (${target}) must be above its entry (${entry})`);
  } else if (side === 'short') {
    if (stop <= entry) errs.push(`a short's stop (${stop}) must be above its entry (${entry})`);
    if (target >= entry) errs.push(`a short's target (${target}) must be below its entry (${entry})`);
  }
  const sizeText = String(raw.size ?? '').trim();
  const size = sizeText === '' ? NaN : Number(sizeText);
  if (!Number.isInteger(size) || size < 1) errs.push(`size must be a whole number of contracts, 1 or more, got "${sizeText}"`);
  else if (SYMBOLS[symbol] && size > SYMBOLS[symbol].maxSize) errs.push(`size ${size} ${symbol} is above the Growth 50K limit of 4 NQ or 40 MNQ`);
  const mode = String(raw.mode ?? '').trim().toLowerCase();
  if (mode !== 'paper' && mode !== 'live') errs.push(`mode must be paper or live, got "${raw.mode ?? ''}"`);
  if (errs.length) throw new Error(errs.join('\n'));
  const note = String(raw.note ?? '');
  const stamp = STAMP.exec(note);
  const addedMs = stamp ? nyToUtc(...stamp.slice(1, 6).map(Number)) : null;
  return {
    id: raw.id == null ? null : Number(raw.id), time_et: String(raw.time_et).trim(), symbol, side, entry, stop, target, size, mode,
    note, ms: t.ms, session: t.session, flatByMs: t.flatByMs,
    added_et: stamp ? `${stamp[1]}-${stamp[2]}-${stamp[3]} ${stamp[4]}:${stamp[5]}` : null,
    backfilled: addedMs != null && addedMs > t.ms, // added in a later minute than its time: hindsight
  };
}

/** RFC 4180 CSV -> [{ line, cells }], blank lines dropped. */
export function parseCsv(text) {
  const rows = [];
  let cells = [], field = '', quoted = false, line = 1, rowLine = 1;
  const endRow = () => {
    cells.push(field);
    if (cells.length > 1 || cells[0].trim() !== '') rows.push({ line: rowLine, cells });
    cells = []; field = '';
  };
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '\n') line++;
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; } else if (c === '"') quoted = false; else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { cells.push(field); field = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') { i++; line++; } else if (c === '\r') line++;
      endRow(); rowLine = line;
    } else field += c;
  }
  if (quoted) throw new Error(`a quoted field starting on line ${rowLine} is never closed`);
  if (field !== '' || cells.length) endRow();
  return rows;
}

const csvField = (v) => (/[",\r\n]/.test(String(v)) || String(v) !== String(v).trim() ? `"${String(v).replace(/"/g, '""')}"` : String(v));
const callRow = (c) => [c.id, c.time_et, c.symbol, c.side, px(c.entry), px(c.stop), px(c.target), c.size, c.mode, c.note].map(csvField).join(',');

/** Read and check a calls CSV. A missing or empty file has no calls. */
export function readCalls(path) {
  if (!existsSync(path)) return [];
  let rows;
  try { rows = parseCsv(readFileSync(path, 'utf8').replace(/^﻿/, '')); } catch (e) { throw new Error(`${path}: ${e.message}`); }
  if (!rows.length) return [];
  const head = rows[0].cells.map((h) => h.trim().toLowerCase());
  if (head.join(',') !== COLUMNS.join(',')) throw new Error(`${path}: the first line must be ${COLUMNS.join(',')} (found ${head.join(',')})`);
  const calls = [], seen = new Set();
  for (const { line, cells } of rows.slice(1)) {
    const where = `${path} line ${line}`;
    if (cells.length !== COLUMNS.length) throw new Error(`${where}: expected ${COLUMNS.length} fields, found ${cells.length}. Put a note that contains a comma in "double quotes".`);
    const raw = Object.fromEntries(COLUMNS.map((c, i) => [c, cells[i]]));
    if (!/^\d+$/.test(raw.id.trim()) || Number(raw.id) < 1) throw new Error(`${where}: id must be a whole number, 1 or more, got "${raw.id}"`);
    if (seen.has(Number(raw.id))) throw new Error(`${where}: id ${raw.id} is used twice`);
    seen.add(Number(raw.id));
    try { calls.push(validateCall(raw)); } catch (e) { throw new Error(`${where} (call ${raw.id}): ${e.message.replace(/\n/g, '; ')}`); }
  }
  return calls;
}

/** Validate and append one call, stamped with the minute it was added. Returns { call, message, warning }.
 *  The time defaults to the current minute; a time before it is refused unless opts.backfill. */
export function addCall(opts, now = Date.now()) {
  const path = opts.calls;
  const existing = readCalls(path);
  const stamp = `[added ${formatEt(now)} ET]`;
  const call = validateCall({
    time_et: opts.time ?? formatEt(now), side: opts.side, entry: opts.entry, stop: opts.stop, target: opts.target,
    size: opts.size ?? '1', symbol: opts.symbol ?? 'MNQ', mode: opts.mode ?? 'paper',
    note: [String(opts.note ?? '').trim(), stamp].filter(Boolean).join(' '),
  });
  if (call.ms < now - (now % MINUTE) && !opts.backfill) {
    throw new Error(`time ${call.time_et} is before now (${formatEt(now)} ET). A call written after the move is hindsight: leave --time out to use the current minute, or add --backfill to record a past call (the score lists it but leaves it out of every figure)`);
  }
  call.id = existing.reduce((m, c) => Math.max(m, c.id), 0) + 1;
  const text = existsSync(path) ? readFileSync(path, 'utf8') : '';
  if (text.trim() === '') writeFileSync(path, `${COLUMNS.join(',')}\n${callRow(call)}\n`);
  else appendFileSync(path, `${text.endsWith('\n') ? '' : '\n'}${callRow(call)}\n`);
  const { pointValue } = SYMBOLS[call.symbol];
  const risk = Math.abs(call.entry - call.stop), reward = Math.abs(call.target - call.entry);
  const message = [
    `Added call ${call.id} to ${path}: ${call.time_et} ET ${call.side} ${call.size} ${call.symbol} (${call.mode})`,
    `  entry ${px(call.entry)}  stop ${px(call.stop)} (${risk.toFixed(2)} pts, $${(risk * pointValue * call.size).toFixed(2)} risk)` +
      `  target ${px(call.target)} (${reward.toFixed(2)} pts, $${(reward * pointValue * call.size).toFixed(2)})  reward:risk ${(reward / risk).toFixed(2)}`,
    `  Graded from the first bar that opens after ${call.time_et.slice(11)} ET (the minute you write it counts as seen); it must be flat by 16:45 ET on ${call.session}.`,
  ].join('\n');
  const warnings = [];
  if (call.backfilled) {
    const late = Math.round((now - call.ms) / MINUTE);
    const ago = late >= 2880 ? `${Math.round(late / 1440)} days` : late >= 120 ? `${Math.round(late / 60)} hours` : `${late} minutes`;
    warnings.push(`Backfilled: this call's time is ${ago} before now. It is stamped ${stamp}; the score lists it but leaves it out of every figure.`);
  }
  const [h, mi] = call.time_et.slice(11).split(':').map(Number);
  if (h * 60 + mi >= FLAT_BY.h * 60 + FLAT_BY.mi - 5 && h < SESSION_START_HOUR) {
    warnings.push(`Note: the score starts a call the minute after it and every trade is flat by 16:45 ET, so a call after 16:39 cannot fill on 5-minute bars, and one after 16:43 not on 1-minute bars either.`);
  }
  return { call, message, warning: warnings.join('\n') || null };
}

// ---------- bars ----------

function parseTime(v, where) {
  const s = String(v ?? '').trim();
  if (/^\d+(\.\d+)?$/.test(s)) return Number(s) > 1e11 ? Number(s) : Number(s) * 1000; // unix seconds (ms tolerated)
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(s)) throw new Error(`${where}: timestamp "${s}" needs a UTC offset (like 2026-10-14T13:05:00-04:00) or must be unix seconds`);
  const ms = Date.parse(s);
  if (Number.isNaN(ms)) throw new Error(`${where}: timestamp "${s}" is not a valid ISO-8601 time`);
  return ms;
}

function makeBar(t, o, h, l, c, where) {
  const [open, high, low, close] = [o, h, l, c].map(Number);
  if (![open, high, low, close].every(Number.isFinite) || [o, h, l, c].some((v) => v === '' || v == null)) throw new Error(`${where}: open, high, low and close must all be numbers`);
  if (high < Math.max(open, close, low) || low > Math.min(open, close)) throw new Error(`${where}: high/low do not contain open/close (o ${open} h ${high} l ${low} c ${close})`);
  return { t: parseTime(t, where), o: open, h: high, l: low, c: close };
}

function barsFromJson(text, name) {
  let j;
  try { j = JSON.parse(text); } catch (e) { throw new Error(`${name}: not valid JSON (${e.message})`); }
  const src = j && !Array.isArray(j) && j.bars !== undefined ? j.bars : j;
  if (Array.isArray(src)) return src.map((r, i) => makeBar(r?.t, r?.o, r?.h, r?.l, r?.c, `${name} bar ${i + 1}`));
  if (src && ['t', 'o', 'h', 'l', 'c'].every((k) => Array.isArray(src[k]) && src[k].length === src.t.length)) {
    return src.t.map((t, i) => makeBar(t, src.o[i], src.h[i], src.l[i], src.c[i], `${name} bar ${i + 1}`));
  }
  throw new Error(`${name}: expected {"bars":{"t":[...],"o":[...],"h":[...],"l":[...],"c":[...]}} (equal lengths) or a list of {t,o,h,l,c} rows`);
}

function barsFromCsv(text, name) {
  const rows = parseCsv(text);
  if (!rows.length) throw new Error(`${name}: the file is empty`);
  const head = rows[0].cells.map((h) => h.trim().toLowerCase());
  const col = (...names) => head.findIndex((h) => names.includes(h));
  const idx = [col('timestamp', 'time'), col('open', 'o'), col('high', 'h'), col('low', 'l'), col('close', 'c')];
  if (idx.some((i) => i < 0)) throw new Error(`${name}: the CSV header must have timestamp,open,high,low,close (found ${head.join(',')})`);
  return rows.slice(1).map(({ line, cells }) => makeBar(...idx.map((i) => cells[i]), `${name} line ${line}`));
}

/** Check sorted bars -> { bars, barMs (median gap) }. Timestamps must be each bar's open time. */
function checkBars(bars, name) {
  if (bars.length < 2) throw new Error(`${name}: need at least 2 bars, found ${bars.length}`);
  const gaps = [];
  for (let i = 1; i < bars.length; i++) {
    if (bars[i].t === bars[i - 1].t) throw new Error(`${name}: two bars at ${formatEt(bars[i].t)} ET`);
    gaps.push(bars[i].t - bars[i - 1].t);
  }
  gaps.sort((a, b) => a - b);
  const barMs = gaps[Math.floor(gaps.length / 2)];
  if (barMs > MAX_BAR_MIN * MINUTE) throw new Error(`${name}: bars are ${barMs / MINUTE} minutes apart; use 1- or 5-minute bars`);
  // CME equity futures stop 17:00-18:00 ET, so a bar stamped then was stamped at its close (or with a wrong UTC offset).
  const inBreak = bars.find((b) => [21, 22].includes(new Date(b.t).getUTCHours()) && nyParts(b.t).h === 17);
  if (inBreak) {
    throw new Error(`${name}: a bar is stamped ${formatEt(inBreak.t)} ET, in the 17:00-18:00 ET break when CME is closed. Each timestamp must be the time the bar opens, as TradingView exports it; this file looks stamped at each bar's close (or has the wrong UTC offset), which would let a call see a bar that ended before it`);
  }
  return { bars, barMs };
}

/** Parse bars (CSV or TradingView JSON) -> { bars sorted by time, barMs (median gap) }. */
export function parseBars(text, name = 'bars') {
  const s = String(text).replace(/^﻿/, '').trim();
  return checkBars((s.startsWith('{') || s.startsWith('[') ? barsFromJson(s, name) : barsFromCsv(s, name)).sort((a, b) => a.t - b.t), name);
}

/** Merge parsed bar files [{ name, bars, barMs }], oldest first: where two files have a bar at the same time, the later file's is used. */
export function mergeBars(files) {
  if (files.length === 1) return { bars: files[0].bars, barMs: files[0].barMs };
  const odd = files.find((f) => f.barMs !== files[0].barMs);
  if (odd) throw new Error(`${odd.name} has ${odd.barMs / MINUTE}-minute bars but ${files[0].name} has ${files[0].barMs / MINUTE}-minute bars: use one bar length`);
  const at = new Map();
  for (const f of files) for (const b of f.bars) at.set(b.t, b);
  return checkBars([...at.values()].sort((a, b) => a.t - b.t), files.map((f) => f.name).join(' + '));
}

// ---------- grading ----------

/** Grade one call against sorted bars. cost = round-trip $ per contract.
 *  A filled call carries `marks`: [bar time, open P&L in $ at that bar's worst price], fill bar to exit bar, for the room walk. */
export function gradeCall(call, bars, barMs, cost = SYMBOLS[call.symbol].cost) {
  const dir = call.side === 'long' ? 1 : -1;
  const { entry, stop, target, size } = call;
  const pointValue = SYMBOLS[call.symbol].pointValue;
  const riskDollars = Math.abs(entry - stop) * pointValue * size;
  const end = (b) => b.t + barMs;
  const startMs = call.ms + MINUTE; // the minute the call is written in counts as already seen
  const first = bars.findIndex((b) => b.t >= startMs);
  const prevBar = first > 0 ? bars[first - 1] : null;
  // On bars longer than a minute the rest of the bar the call was written in is never graded: flag it when it reached the entry.
  const unseen = Boolean(prevBar && barMs > MINUTE && call.ms < end(prevBar) && prevBar.l <= entry && entry <= prevBar.h);
  const base = {
    ...call, plannedRR: Math.abs(target - entry) / Math.abs(entry - stop), riskDollars,
    fill_et: null, fillPrice: null, exit_et: null, exitPrice: null, points: null, rGross: null, r: null, dollars: null,
    worstOpenPnl: null, touch: false, unseen, marks: null,
  };
  const hhmm = (t) => formatEt(t).slice(11);
  const pastStop = (p) => dir * (p - stop) < 0;
  const atOrPastTarget = (p) => dir * (p - target) >= 0;
  const touchesStop = (b) => (dir > 0 ? b.l <= stop : b.h >= stop);
  const touchesTarget = (b) => (dir > 0 ? b.h >= target : b.l <= target);
  const exactTarget = (b) => (dir > 0 ? b.h : b.l) === target;

  const unseenText = unseen && `the call's own ${hhmm(prevBar.t)} bar reached the entry (not seen)`;
  const join = (...parts) => parts.filter(Boolean).join('; ');
  const pending = (status, detail) => ({ ...base, status, detail: join(detail, unseenText) });

  if (Math.ceil(startMs / barMs) * barMs + barMs > call.flatByMs) {
    return { ...base, unseen: false, status: 'TOO LATE', detail: `no ${barMs / MINUTE}-minute bar starts after the call's minute and ends by the 16:45 flat-by` };
  }
  if (bars[0].t > startMs) return pending('NO DATA', 'the bars start after this call');
  if (first < 0) return pending('OPEN', 'the bars end before this call');
  const waitEnd = Math.min(call.ms + FILL_WAIT_MIN * MINUTE, call.flatByMs);
  let f = -1, j = first, fillPrice = entry, jumped = false, nearest = Infinity;
  let last = prevBar ? prevBar.c : null; // the last price seen before the bar being tested
  for (; j < bars.length && end(bars[j]) <= waitEnd; j++) {
    const b = bars[j];
    if (last != null && (last - entry) * (b.o - entry) < 0) { // price jumped over the entry between bars
      f = j; jumped = true; fillPrice = dir > 0 ? Math.max(entry, b.o) : Math.min(entry, b.o);
      break;
    }
    if (b.l <= entry && entry <= b.h) { f = j; break; }
    nearest = Math.min(nearest, entry < b.l ? b.l - entry : entry - b.h);
    last = b.c;
  }
  if (f < 0) {
    if (end(bars[bars.length - 1]) < waitEnd) return pending('OPEN', 'the bars end while the call waits for its fill');
    if (j === first) return pending('NO DATA', 'no bars in the 30 minutes after the call');
    const far = nearest / entry > FAR_ENTRY ? `; every price in that time was at least ${nearest.toFixed(2)} points away: is it the contract you trade (roll week?) or a typo?` : '';
    return pending('NOT FILLED', `price did not touch ${px(entry)} ${waitEnd < call.flatByMs ? 'within 30 minutes' : 'before the 16:45 flat-by'}${far}`);
  }

  const fb = bars[f];
  const marks = [];
  const adverse = (b) => Math.max(0, dir * (fillPrice - (dir > 0 ? b.l : b.h)));
  const markBar = (b) => marks.push([b.t, -(adverse(b) * pointValue * size + cost * size)]);
  const worstMark = () => marks.reduce((m, [, v]) => Math.min(m, v), Infinity);
  const how = !jumped ? '' : fillPrice === entry ? `price jumped over ${px(entry)} at the ${hhmm(fb.t)} open: filled at the entry`
    : `price jumped over ${px(entry)} at the ${hhmm(fb.t)} open: filled at that open, ${px(fillPrice)}`;
  const closed = (status, b, exitPrice, detail, { exitMark = false, touch = false } = {}) => {
    const points = dir * (exitPrice - fillPrice);
    const dollars = points * pointValue * size - cost * size;
    if (exitMark) marks.push([b.t, dollars]); // out at this price: the bar's later extreme does not count
    return {
      ...base, status, fill_et: formatEt(fb.t), fillPrice, exit_et: formatEt(b.t), exitPrice, points,
      rGross: points / Math.abs(entry - stop), r: dollars / riskDollars, dollars, worstOpenPnl: worstMark(), touch, marks,
      detail: join(how, detail, touch && 'the target was touched exactly, not traded through: a resting limit there might not have filled', unseenText),
    };
  };

  let note = '';
  if (jumped && pastStop(fb.o)) return closed('STOP', fb, fb.o, 'it jumped past the stop too: stopped at that open (measured from the entry, the worse case)', { exitMark: true });
  if (touchesStop(fb)) return closed('STOP', fb, stop, 'the fill bar also reached the stop (order inside a bar unknown: counted as a stop)', { exitMark: true });
  if (jumped && atOrPastTarget(fb.o)) return closed('TARGET', fb, fb.o, 'it jumped past the target too: out at that open', { exitMark: true });
  markBar(fb);
  if (touchesTarget(fb)) {
    if (jumped || dir * (fb.o - entry) <= 0) return closed('TARGET', fb, target, 'reached the target in the fill bar', { touch: exactTarget(fb) });
    note = 'a target touch in the fill bar was ignored (it may have come before the fill)';
  }
  let lastBar = fb;
  for (let k = f + 1; k < bars.length && end(bars[k]) <= call.flatByMs; k++) {
    const b = bars[k];
    if (pastStop(b.o)) return closed('STOP', b, b.o, 'gapped past the stop: exit at the open', { exitMark: true });
    if (atOrPastTarget(b.o)) return closed('TARGET', b, target, 'opened at or past the target', { exitMark: true });
    if (touchesStop(b) && touchesTarget(b)) return closed('STOP', b, stop, 'stop and target in the same bar: counted as a stop', { exitMark: true });
    if (touchesStop(b)) return closed('STOP', b, stop, note, { exitMark: true });
    markBar(b);
    if (touchesTarget(b)) return closed('TARGET', b, target, note, { touch: exactTarget(b) });
    lastBar = b;
  }
  if (end(bars[bars.length - 1]) < call.flatByMs && lastBar === bars[bars.length - 1]) {
    const atClose = dir * (lastBar.c - fillPrice) * pointValue * size - cost * size;
    return {
      ...base, status: 'OPEN', fill_et: formatEt(fb.t), fillPrice, worstOpenPnl: worstMark(), marks,
      detail: join(how, `the bars end with the trade still open (${money(atClose)} at the last close)`, unseenText),
    };
  }
  return closed('FLAT', lastBar, lastBar.c, note || 'neither stop nor target by 16:45 ET');
}

// ---------- summary ----------

function mulberry32(seed) {
  let a = seed | 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** 95% percentile bootstrap interval of the mean (seeded, reproducible). */
export function bootstrapMeanCI(values, { resamples = BOOTSTRAP.resamples, seed = BOOTSTRAP.seed } = {}) {
  const n = values.length;
  if (!n) return null;
  const rand = mulberry32(seed);
  const means = new Float64Array(resamples);
  for (let b = 0; b < resamples; b++) {
    let s = 0;
    for (let i = 0; i < n; i++) s += values[Math.floor(rand() * n)];
    means[b] = s / n;
  }
  means.sort();
  return { lo: means[Math.floor(0.025 * resamples)], hi: means[Math.ceil(0.975 * resamples) - 1] };
}

/** Walk every bar in time order from `room` dollars above the floor: the room left after closed trades plus the open P&L
 *  (at the bar's worst price) of every filled call open at that bar. A closed trade is credited at its exit bar.
 *  Stops at the first breach. Also reports calls open together and combined size over the 40 MNQ / 4 NQ limit. */
export function roomCheck(results, room) {
  const cap = Math.max(MAX_ROOM, room);
  const legs = results.filter((r) => r.marks?.length);
  const at = new Map();
  for (const g of legs) {
    const exitT = g.status === 'OPEN' ? null : g.marks[g.marks.length - 1][0];
    for (const [t, pnl] of g.marks) {
      if (!at.has(t)) at.set(t, []);
      at.get(t).push({ g, pnl, exits: t === exitT });
    }
  }
  let left = room, lowest = room, breach = null, sizeOver = null;
  const together = new Map();
  for (const t of [...at.keys()].sort((a, b) => a - b)) {
    const open = at.get(t);
    const ids = open.map((o) => o.g.id).sort((a, b) => a - b);
    const openPnl = open.reduce((s, o) => s + o.pnl, 0);
    if (ids.length > 1) together.set(ids.join(','), ids);
    const mnq = open.reduce((s, o) => s + o.g.size * SYMBOLS[o.g.symbol].mnq, 0);
    if (!sizeOver && mnq > MAX_MNQ) sizeOver = { time_et: formatEt(t), ids, mnq };
    lowest = Math.min(lowest, left + openPnl);
    if (left + openPnl <= 0) {
      breach = { time_et: formatEt(t), ids, roomLeft: left, openPnl, legs: open.map((o) => ({ id: o.g.id, status: o.g.status, dollars: o.g.dollars })) };
      break;
    }
    for (const o of open) if (o.exits) left = Math.min(cap, left + o.g.dollars);
  }
  return {
    start: room, end: left, lowest, breach, together: [...together.values()], sizeOver,
    walked: legs.length, stillOpen: legs.filter((g) => g.status === 'OPEN').map((g) => g.id),
  };
}

const byTime = (a, b) => a.ms - b.ms || a.id - b.id;
const mean = (xs) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null);

/** Graded rows -> ideas: rows with the same time, side, entry and stop (split targets) are one idea, at their risk-weighted R. */
export function groupIdeas(graded) {
  const ideas = new Map();
  for (const g of graded) {
    const key = [g.time_et, g.side, g.entry, g.stop].join('|');
    if (!ideas.has(key)) ideas.set(key, { ids: [], ms: g.ms, risk: 0, r: 0, rGross: 0, dollars: 0 });
    const i = ideas.get(key);
    i.ids.push(g.id); i.risk += g.riskDollars; i.r += g.r * g.riskDollars; i.rGross += g.rGross * g.riskDollars; i.dollars += g.dollars;
  }
  return [...ideas.values()].map((i) => ({ ids: i.ids, ms: i.ms, r: i.r / i.risk, rGross: i.rGross / i.risk, dollars: i.dollars }));
}

export function summarize(results, { room = 199, seed = BOOTSTRAP.seed } = {}) {
  const counted = results.filter((r) => !r.backfilled).sort(byTime);
  const graded = counted.filter((r) => GRADED.has(r.status));
  const ideas = groupIdeas(graded);
  const rs = ideas.map((i) => i.r);
  const counts = {};
  for (const r of counted) counts[r.status] = (counts[r.status] ?? 0) + 1;
  let streak = 0, longestLosingStreak = 0;
  for (const r of rs) { streak = r > 0 ? 0 : streak + 1; longestLosingStreak = Math.max(longestLosingStreak, streak); }
  const wins = rs.filter((r) => r > 0).length;
  const ci = bootstrapMeanCI(rs, { seed });
  const totalDollars = graded.reduce((s, g) => s + g.dollars, 0);
  const rc = roomCheck(counted, room);
  const n = ideas.length;
  const rows = graded.length > n ? ` (from ${graded.length} rows: rows with the same time, side, entry and stop count once)` : '';
  const interval = ci && `the average R interval after commissions (${sign(ci.lo)} to ${sign(ci.hi)})`;
  let verdict;
  if (n < MIN_CALLS_TO_JUDGE) verdict = `Too few calls to judge: ${n} graded${rows}, fewer than ${MIN_CALLS_TO_JUDGE}. Keep writing every call down before the move.`;
  else if (ci.lo > 0) verdict = `Edge shown: ${interval} is above 0 over ${n} graded calls${rows}, before slippage.`;
  else if (ci.hi < 0) verdict = `No edge: ${interval} is below 0. These calls lose money.`;
  else verdict = `No edge shown yet: ${interval} includes 0.`;
  if (rc.breach) verdict += ` And these sizes breach the account: starting from ${usd(room)} of room, the floor is touched on ${rc.breach.time_et} ET (${idList(rc.breach.ids)} open).`;
  return {
    calls: results.length, graded: graded.length, ideas: n, counts, wins, winRate: n ? wins / n : null,
    avgR: mean(rs), avgRGross: mean(ideas.map((i) => i.rGross)), avgRInterval95: ci, totalR: rs.reduce((s, r) => s + r, 0),
    totalDollars, avgDollars: n ? totalDollars / n : null,
    longestLosingStreak, avgPlannedRR: mean(graded.map((g) => g.plannedRR)),
    splits: ideas.filter((i) => i.ids.length > 1).map((i) => i.ids),
    touches: graded.filter((g) => g.touch).map((g) => g.id),
    unseen: counted.filter((r) => r.unseen).map((r) => r.id),
    backfilled: results.filter((r) => r.backfilled).map((r) => r.id),
    unstamped: results.filter((r) => !r.added_et).length,
    room: rc, verdict,
  };
}

/** {MNQ, NQ} round-trip $ per contract from null (defaults), one number (every symbol) or {MNQ?, NQ?}. */
export function resolveCosts(cost = null) {
  const pick = (s) => (cost == null ? SYMBOLS[s].cost : typeof cost === 'number' ? cost : cost[s] ?? SYMBOLS[s].cost);
  return Object.fromEntries(Object.keys(SYMBOLS).map((s) => [s, pick(s)]));
}

/** Grade every call. cost: see resolveCosts. */
export function scoreCalls(calls, { bars, barMs }, { cost = null, room = 199, seed } = {}) {
  const costs = resolveCosts(cost);
  const results = calls.slice().sort(byTime).map((c) => gradeCall(c, bars, barMs, costs[c.symbol]));
  return { results, summary: summarize(results, { room, seed }) };
}

// ---------- report ----------

const px = (x) => Number(x).toFixed(2);
const sign = (x, d = 2) => `${x < 0 ? '-' : '+'}${Math.abs(x).toFixed(d)}`;
const money = (x) => `${x < 0 ? '-' : '+'}$${Math.abs(x).toFixed(2)}`;
const usd = (x) => `$${x.toFixed(2)}`;
const idList = (ids) => `${ids.length === 1 ? 'call' : 'calls'} ${ids.join(',')}`;

function table(rows, cols) {
  const cells = rows.map((r) => cols.map(([, f]) => f(r)));
  const widths = cols.map(([h], i) => Math.max(h.length, ...cells.map((c) => c[i].length)));
  const line = (vals) => vals.map((v, i) => (i === vals.length - 1 ? v : cols[i][2] === 'r' ? v.padStart(widths[i]) : v.padEnd(widths[i]))).join('  ').trimEnd();
  return [line(cols.map(([h]) => h)), ...cells.map(line)].join('\n');
}

export function formatReport({ results, summary }, { callsName, barsName, bars, barMs, cost = null, room, dropped = null }) {
  const when = (et, r) => (!et ? '' : et.slice(0, 10) === r.time_et.slice(0, 10) ? et.slice(11) : et.slice(5));
  const cols = [
    ['id', (r) => String(r.id), 'r'], ['call ET', (r) => r.time_et], ['side', (r) => r.side], ['size', (r) => `${r.size} ${r.symbol}`],
    ['mode', (r) => r.mode], ['entry', (r) => px(r.entry), 'r'], ['stop', (r) => px(r.stop), 'r'], ['target', (r) => px(r.target), 'r'],
    ['result', (r) => r.status], ['fill', (r) => when(r.fill_et, r)], ['exit', (r) => when(r.exit_et, r)],
    ['exit @', (r) => (r.exitPrice == null ? '' : px(r.exitPrice)), 'r'], ['points', (r) => (r.points == null ? '' : sign(r.points)), 'r'],
    ['R', (r) => (r.r == null ? '' : sign(r.r)), 'r'], ['$', (r) => (r.dollars == null ? '' : money(r.dollars)), 'r'],
    ['worst $', (r) => (r.worstOpenPnl == null ? '' : money(r.worstOpenPnl)), 'r'],
    ['detail', (r) => [r.backfilled && `BACKFILLED (added ${r.added_et}, after its time): left out of every figure`, r.detail].filter(Boolean).join('; ')],
  ];
  const s = summary, rc = s.room;
  const costs = resolveCosts(cost);
  const out = [
    `Prediction journal: ${callsName} graded against ${barsName}`,
    `Bars: ${Math.round(barMs / MINUTE)}-minute, ${formatEt(bars[0].t)} to ${formatEt(bars[bars.length - 1].t)} ET` +
      (dropped ? ` (the last bar in the file, ${formatEt(dropped.t)}, is left out: it may still have been forming when the file was saved).` : '.'),
    `Cost per contract, round trip: ${Object.entries(costs).map(([k, v]) => `${k} ${usd(v)}`).join(', ')}. Room to the floor before the first call: ${usd(room)}.`,
    '',
    'Scoring rules:',
    ...RULES.map((r, i) => `  ${i + 1}. ${r}`),
    '',
  ];
  if (!results.length) return [...out, 'No calls yet. Add one with: node journal.mjs add --calls FILE ...'].join('\n');
  out.push(table(results, cols), '');
  const c = s.counts, ci = s.avgRInterval95;
  out.push(
    'Summary (graded = STOP, TARGET or FLAT; the rest are left out):',
    `  calls                  ${s.calls}: graded ${s.graded}, not filled ${c['NOT FILLED'] ?? 0}, open ${c.OPEN ?? 0}, no data ${c['NO DATA'] ?? 0}, too late ${c['TOO LATE'] ?? 0}` +
      (s.backfilled.length ? `, backfilled ${s.backfilled.length}` : ''),
  );
  if (s.backfilled.length) out.push(`  backfilled             ${idList(s.backfilled)}: added after ${s.backfilled.length === 1 ? 'its' : 'their'} time, so listed but left out of every figure`);
  if (s.unstamped) out.push(`  no add stamp           ${s.unstamped} of ${s.calls} calls: the journal cannot check they were written before the move`);
  if (s.splits.length) out.push(`  split targets          ${s.splits.map(idList).join('; ')} share a time, side, entry and stop: each group is one idea (${s.ideas} ideas graded)`);
  if (s.graded) {
    out.push(
      `  wins (R > 0)           ${s.wins} of ${s.ideas}, win rate ${(s.winRate * 100).toFixed(1)}%`,
      `  average R              ${sign(s.avgR)} after commissions (${sign(s.avgRGross)} before), 95% interval ${sign(ci.lo)} to ${sign(ci.hi)} (bootstrap, 2000 resamples, seed ${BOOTSTRAP.seed})`,
      `  total R                ${sign(s.totalR)}`,
      `  dollars                total ${money(s.totalDollars)}, average ${money(s.avgDollars)} per graded idea`,
      `  longest losing streak  ${s.longestLosingStreak} (a loss is any call with R <= 0)`,
      `  planned reward:risk    ${s.avgPlannedRR.toFixed(2)} on average`,
    );
    if (s.touches.length) out.push(`  exact touches          ${idList(s.touches)}: the target was only touched, not traded through; a resting limit there might not have filled`);
  }
  if (s.unseen.length) out.push(`  not seen               ${idList(s.unseen)}: the bar each was written in reached the entry, and the rest of that bar is not graded, so a fill right after the call is missed (1-minute bars avoid this)`);
  if (rc.walked) {
    out.push(`  room check             as if you had ${usd(rc.start)} of room before the first call, walked bar by bar with open P&L at each bar's worst price`);
    const b = rc.breach;
    if (b) {
      const done = b.legs.filter((l) => l.status !== 'OPEN');
      const after = done.length === b.legs.length ? done.reduce((x, l) => x + l.dollars, 0) : null;
      const recovered = after != null && after > b.openPnl ? ` (${b.legs.length === 1 ? 'it' : 'they'} closed at ${money(after)}${b.legs.length === 1 ? '' : ' together'}, but the floor had already been touched)` : '';
      out.push(`    ACCOUNT BREACHED on ${b.time_et} ET with ${idList(b.ids)} open: open P&L ${money(b.openPnl)} against ${usd(b.roomLeft)} of room left${recovered}. Later bars and calls are not walked.`);
    } else out.push(`    no breach: lowest ${usd(rc.lowest)} of room left (counting open losses), ${usd(rc.end)} after the last closed trade`);
    if (rc.together.length) {
      const shown = rc.together.slice(0, 5).map(idList).join('; ');
      out.push(`    open together: ${shown}${rc.together.length > 5 ? ` and ${rc.together.length - 5} more` : ''} (their open P&L is added together)`);
    }
    if (rc.sizeOver) out.push(`    SIZE: on ${rc.sizeOver.time_et} ET ${idList(rc.sizeOver.ids)} hold ${rc.sizeOver.mnq} MNQ-equivalent together, above the Growth 50K limit of 40 MNQ or 4 NQ`);
    if (rc.stillOpen.length) out.push(`    still open when the bars end: ${idList(rc.stillOpen)} (walked to the last bar, never credited)`);
  }
  out.push('', `Verdict: ${s.verdict}`);
  return out.join('\n');
}

// ---------- CLI ----------

const USAGE = `Prediction journal for MNQ / NQ calls (Tradeify 50K Growth). Times are New York time.

  node journal.mjs add --calls FILE --side long|short --entry PRICE --stop PRICE --target PRICE
                       [--time "YYYY-MM-DD HH:MM"] [--size 1] [--symbol MNQ|NQ] [--mode paper|live]
                       [--note "..."] [--backfill]
  node journal.mjs score --calls FILE --bars FILE [--bars FILE ...] [--room 199]
                         [--cost MNQ=0.5,NQ=1.5] [--json]

Write each call down before the move with add: --time defaults to the current minute, and a time
before it needs --backfill (the score then lists the call but leaves it out). score grades every
call against real 1- or 5-minute bars and says whether your read has an edge. Bars are CSV
timestamp,open,high,low,close, each timestamp the time the bar OPENS (as TradingView exports it),
or TradingView JSON. Give --bars once per file to merge pages, oldest first.`;

const OPTIONS = {
  add: ['calls', 'time', 'side', 'entry', 'stop', 'target', 'size', 'symbol', 'mode', 'note', 'backfill'],
  score: ['calls', 'bars', 'room', 'cost', 'json'],
};
const REQUIRED = { add: ['calls', 'side', 'entry', 'stop', 'target'], score: ['calls', 'bars'] };
const FLAGS = new Set(['json', 'backfill']);
const REPEATABLE = new Set(['bars']);

export function parseArgs(argv) {
  const [cmd, ...rest] = argv;
  if (!OPTIONS[cmd]) throw new Error(`unknown command "${cmd}" (use add or score)`);
  const opts = {};
  for (let i = 0; i < rest.length; i++) {
    const m = /^--([a-z]+)(?:=(.*))?$/s.exec(rest[i]);
    if (!m) throw new Error(`unexpected "${rest[i]}" (options look like --side long)`);
    const [, key, inline] = m;
    if (!OPTIONS[cmd].includes(key)) throw new Error(`${cmd} has no option --${key} (it takes ${OPTIONS[cmd].map((o) => `--${o}`).join(' ')})`);
    if (key in opts && !REPEATABLE.has(key)) throw new Error(`--${key} is given twice`);
    if (FLAGS.has(key)) { opts[key] = true; continue; }
    const value = inline ?? rest[++i];
    if (value === undefined || (inline === undefined && /^--[a-z]/.test(value))) throw new Error(`--${key} needs a value`);
    opts[key] = REPEATABLE.has(key) ? [...(opts[key] ?? []), value] : value;
  }
  const missing = REQUIRED[cmd].filter((k) => opts[k] === undefined);
  if (missing.length) throw new Error(`${cmd} needs ${missing.map((k) => `--${k}`).join(' ')}`);
  return { cmd, opts };
}

function amount(text, name) {
  const x = Number(String(text).trim());
  if (String(text).trim() === '' || !Number.isFinite(x) || x < 0) throw new Error(`--${name} must be a dollar amount of 0 or more, got "${text}"`);
  return x;
}

/** --cost: one amount for every symbol (0.5) or per symbol (MNQ=0.5,NQ=1.5; a symbol left out keeps its default). */
export function parseCost(text) {
  if (text === undefined) return null;
  if (!String(text).includes('=')) return amount(text, 'cost');
  const out = {};
  for (const part of String(text).split(',')) {
    const m = /^\s*([a-z]+)\s*=(.*)$/i.exec(part);
    if (!m || !SYMBOLS[m[1].toUpperCase()]) throw new Error(`--cost must be a dollar amount (0.5) or one per symbol (MNQ=0.5,NQ=1.5), got "${text}"`);
    out[m[1].toUpperCase()] = amount(m[2], 'cost');
  }
  return out;
}

export function main(argv, now = Date.now()) {
  if (!argv.length || ['help', '--help', '-h'].includes(argv[0])) { console.log(USAGE); return 0; }
  try {
    const { cmd, opts } = parseArgs(argv);
    if (cmd === 'add') {
      const { message, warning } = addCall(opts, now);
      console.log(message);
      if (warning) console.error(warning);
      return 0;
    }
    if (!existsSync(opts.calls)) throw new Error(`calls file ${opts.calls} not found (add a call first: node journal.mjs add --calls ${opts.calls} ...)`);
    for (const f of opts.bars) if (!existsSync(f)) throw new Error(`bars file ${f} not found`);
    const room = opts.room === undefined ? 199 : amount(opts.room, 'room');
    if (room <= 0) throw new Error('--room must be above 0: with no room left the account has already breached');
    const cost = parseCost(opts.cost);
    const calls = readCalls(opts.calls);
    const all = mergeBars(opts.bars.map((f) => ({ name: basename(f), ...parseBars(readFileSync(f, 'utf8'), basename(f)) })));
    // The newest bar may still have been forming when the file was saved (the TradingView connector says so): leave it out.
    const dropped = all.bars[all.bars.length - 1];
    const data = { bars: all.bars.slice(0, -1), barMs: all.barMs };
    const scored = scoreCalls(calls, data, { cost, room });
    const barsName = opts.bars.map((f) => basename(f)).join(' + ');
    if (opts.json) {
      const strip = ({ ms, flatByMs, marks, ...r }) => r;
      const out = {
        rules: RULES,
        bars: {
          files: opts.bars, barMinutes: data.barMs / MINUTE, first_et: formatEt(data.bars[0].t), last_et: formatEt(data.bars.at(-1).t),
          left_out_et: formatEt(dropped.t),
        },
        room, cost: resolveCosts(cost),
        calls: scored.results.map(strip), summary: scored.summary,
      };
      console.log(JSON.stringify(out, null, 2));
    } else {
      console.log(formatReport(scored, { callsName: basename(opts.calls), barsName, ...data, cost, room, dropped }));
    }
    return 0;
  } catch (e) {
    console.error(`journal: ${e.message.replace(/\n/g, '\n  ')}`);
    console.error('Run "node journal.mjs" with no arguments for usage.');
    return 1;
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) process.exitCode = main(process.argv.slice(2));
