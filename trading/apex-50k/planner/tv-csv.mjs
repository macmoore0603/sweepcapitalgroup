// tv-csv.mjs - parse a TradingView Strategy Tester "List of trades" CSV export.
//
// Output trades (sorted by exit time): { tradeNo, side, entryTime, exitTime (Date), dayKey (YYYY-MM-DD of
// the Apex / CME session in America/New_York: exits at or after 18:00 ET count toward the next day),
// contracts, pnl, runUp, drawdown, pnlPer, mfePer (>= max(0, pnlPer)), maePer (<= min(0, pnlPer)) }.
// pnl is the export's P&L, which already includes commission when the strategy set one, so callers
// should default any extra cost to 0 for CSV input.

import { readFileSync } from 'node:fs';
import { NY, SESSION_ROLL_HOUR, zonedTimeToUtc, dayKeyOf } from './time.mjs';

// Header aliases (matched after normalizeHeader). Currency suffix is optional and any 3-letter code.
const CUR = '(?: [a-z]{3})?';
const COLUMN_PATTERNS = {
  tradeNo: /^(?:trade ?#|trade ?no\.?|trade ?number|trade|#)$/,
  type: /^(?:type|action)$/,
  signal: /^signal$/,
  time: /^(?:date ?\/ ?time|date and time|date & time|datetime|date|time)$/,
  contracts: /^(?:contracts|quantity|qty|position size(?: \(qty\))?|size)$/,
  pnl: new RegExp(`^(?:net )?(?:profit|p ?& ?l|pnl)${CUR}$`),
  runUp: new RegExp(`^(?:run-?up|max(?:imum)? favorable excursion|favorable excursion|mfe)${CUR}$`),
  drawdown: new RegExp(`^(?:draw-?down|max(?:imum)? adverse excursion|adverse excursion|mae)${CUR}$`),
};

export function normalizeHeader(h) {
  return String(h)
    .replace(/^﻿/, '')
    .replace(/[   ]/g, ' ')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ');
}

/** Pick the delimiter that occurs most often (outside quotes) in the header line: ',' ';' or tab. */
export function detectDelimiter(text) {
  const counts = { ',': 0, ';': 0, '\t': 0 };
  let inQ = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') inQ = !inQ;
    else if (!inQ && (c === '\n' || c === '\r')) break;
    else if (!inQ && c in counts) counts[c]++;
  }
  let best = ',';
  for (const d of [';', '\t']) if (counts[d] > counts[best]) best = d;
  return best;
}

/** RFC 4180-style parser: quoted fields, "" escapes, CRLF/LF/CR line ends. Returns rows of strings. */
export function parseCsvRows(text, delimiter) {
  const rows = [];
  let row = [];
  let field = '';
  let inQ = false;
  let i = 0;
  const n = text.length;
  while (i < n) {
    const c = text[i];
    if (inQ) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQ = false;
        i++;
        continue;
      }
      field += c;
      i++;
      continue;
    }
    if (c === '"') {
      inQ = true;
      i++;
    } else if (c === delimiter) {
      row.push(field);
      field = '';
      i++;
    } else if (c === '\n' || c === '\r') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
      i += c === '\r' && text[i + 1] === '\n' ? 2 : 1;
    } else {
      field += c;
      i++;
    }
  }
  if (field !== '' || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter((r) => r.some((f) => f.trim() !== ''));
}

/**
 * Tolerant number parser: Unicode minus (U+2212 etc.), (parentheses) negatives, currency symbols/codes,
 * space / NBSP / apostrophe / '.' / ',' thousands separators, '.' or ',' decimals.
 * decimal: 'auto' (default) | '.' | ','.
 */
export function parseNumber(raw, decimal = 'auto') {
  if (raw == null) return NaN;
  let s = String(raw).trim();
  if (s === '') return NaN;
  s = s.replace(/[−‒–—﹣－]/g, '-');
  let neg = false;
  if (/^\(.*\)$/.test(s)) {
    neg = true;
    s = s.slice(1, -1);
  }
  s = s.replace(/[\s   ']/g, '').replace(/[^0-9.,+-]/g, '');
  while (s.startsWith('-') || s.startsWith('+')) {
    if (s[0] === '-') neg = !neg;
    s = s.slice(1);
  }
  if (s.endsWith('-')) {
    neg = !neg;
    s = s.slice(0, -1);
  }
  const hasDot = s.includes('.');
  const hasComma = s.includes(',');
  if (hasDot && hasComma) {
    if (s.lastIndexOf(',') > s.lastIndexOf('.')) s = s.replace(/\./g, '').replace(',', '.');
    else s = s.replace(/,/g, '');
  } else if (hasComma) {
    const thousands =
      decimal === '.' || (decimal !== ',' && ((s.match(/,/g) || []).length > 1 || /^[1-9]\d{0,2}(,\d{3})+$/.test(s)));
    s = thousands ? s.replace(/,/g, '') : s.replace(',', '.');
  } else if (hasDot) {
    if (decimal === ',' || (s.match(/\./g) || []).length > 1) s = s.replace(/\./g, '');
  }
  if (s === '' || s === '.') return NaN;
  const v = Number(s);
  if (!Number.isFinite(v)) return NaN;
  return neg ? -v : v;
}

const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };

function hour12(h, ampm) {
  if (!ampm) return h;
  const pm = ampm.toLowerCase() === 'pm';
  if (h === 12) return pm ? 12 : 0;
  return pm ? h + 12 : h;
}

/**
 * Parse a TradingView timestamp. Without an explicit offset the wall-clock time is read in `tz`
 * (the chart time zone used for the export; default America/New_York).
 * Accepts 2024-03-15 09:31[:00], 2024-03-15T09:31:00Z / +01:00, 2024/03/15 09:31, 15.03.2024 09:31,
 * 03/15/2024 9:31 PM (dateOrder 'mdy'; 'dmy' reads 15/03/2024; 'auto' decides per value, so a whole file
 * should be resolved once with detectDateOrder), Mar 15, 2024, 09:31, 15 Mar 2024 09:31, 15-Mar-2024.
 * Any other text is read by Date.parse only when it names its own offset (Z, GMT, UTC or +hh:mm), so the
 * result never depends on the host machine's time zone; otherwise null.
 */
export function parseTvDate(raw, { tz = NY, dateOrder = 'auto' } = {}) {
  const s = String(raw ?? '')
    .trim()
    .replace(/[  ]/g, ' ');
  if (!s) return null;
  const time = '(?:[ T,]+(\\d{1,2}):(\\d{2})(?::(\\d{2}))?(?:\\.\\d+)?\\s*(am|pm)?)?';
  const off = '\\s*(z|utc|gmt|[+-]\\d{2}:?\\d{2})?';
  let m;
  let y;
  let mo;
  let d;
  let h = 0;
  let mi = 0;
  let sec = 0;
  let ofs = null;
  if ((m = new RegExp(`^(\\d{4})[-/.](\\d{1,2})[-/.](\\d{1,2})${time}${off}$`, 'i').exec(s))) {
    [y, mo, d] = [+m[1], +m[2], +m[3]];
    [h, mi, sec] = [hour12(+(m[4] ?? 0), m[7]), +(m[5] ?? 0), +(m[6] ?? 0)];
    ofs = m[8] ?? null;
  } else if ((m = new RegExp(`^(\\d{1,2})([-/.])(\\d{1,2})\\2(\\d{4})${time}${off}$`, 'i').exec(s))) {
    const a = +m[1];
    const b = +m[3];
    const dmy = m[2] === '.' || dateOrder === 'dmy' || (dateOrder === 'auto' && a > 12);
    [d, mo] = dmy ? [a, b] : [b, a];
    y = +m[4];
    [h, mi, sec] = [hour12(+(m[5] ?? 0), m[8]), +(m[6] ?? 0), +(m[7] ?? 0)];
    ofs = m[9] ?? null;
  } else if ((m = new RegExp(`^([a-z]{3})[a-z]*\\.? (\\d{1,2}),? (\\d{4})${time}${off}$`, 'i').exec(s))) {
    mo = MONTHS[m[1].toLowerCase()];
    if (!mo) return null;
    [d, y] = [+m[2], +m[3]];
    [h, mi, sec] = [hour12(+(m[4] ?? 0), m[7]), +(m[5] ?? 0), +(m[6] ?? 0)];
    ofs = m[8] ?? null;
  } else if ((m = new RegExp(`^(?:[a-z]{3,9}\\.?,? )?(\\d{1,2})[ -]([a-z]{3})[a-z]*\\.?,?[ -](\\d{4})${time}${off}$`, 'i').exec(s))) {
    mo = MONTHS[m[2].toLowerCase()];
    if (!mo) return null;
    [d, y] = [+m[1], +m[3]];
    [h, mi, sec] = [hour12(+(m[4] ?? 0), m[7]), +(m[5] ?? 0), +(m[6] ?? 0)];
    ofs = m[8] ?? null;
  } else if (/(?:\b(?:gmt|utc)\b|\dz$|[+-]\d{2}:?\d{2}(?:\s*\([^)]*\))?$)/i.test(s)) {
    const t = Date.parse(s);
    return Number.isNaN(t) ? null : new Date(t);
  } else {
    return null;
  }
  if (!(mo >= 1 && mo <= 12 && d >= 1 && d <= 31 && h <= 23 && mi <= 59 && sec <= 60)) return null;
  if (ofs) {
    const o = ofs.toLowerCase();
    let offMin = 0;
    if (o !== 'z' && o !== 'utc' && o !== 'gmt') {
      const mm = /^([+-])(\d{2}):?(\d{2})$/.exec(o);
      offMin = (mm[1] === '-' ? -1 : 1) * (+mm[2] * 60 + +mm[3]);
    }
    return new Date(Date.UTC(y, mo - 1, d, h, mi, sec) - offMin * 60000);
  }
  return zonedTimeToUtc(y, mo, d, h, mi, sec, tz);
}

const NUMERIC_DATE = /^(\d{1,2})([-/])(\d{1,2})\2\d{4}/;

/**
 * Day/month order for a whole file of timestamps: 'dmy' when some first field is > 12, 'mdy' when some
 * second field is > 12. Returns { order, ambiguous } (ambiguous: numeric d/m dates were seen but none has a
 * field > 12, so 'mdy' is assumed). Throws when the file contradicts itself. Dotted (15.03.2024) and ISO
 * dates do not take part.
 */
export function detectDateOrder(values) {
  let numeric = 0;
  let dmy = null;
  let mdy = null;
  for (const v of values) {
    const m = NUMERIC_DATE.exec(String(v ?? '').trim());
    if (!m) continue;
    numeric++;
    if (+m[1] > 12 && dmy == null) dmy = v;
    if (+m[3] > 12 && mdy == null) mdy = v;
  }
  if (dmy != null && mdy != null) {
    throw new Error(`dates mix dd/mm ("${dmy}") and mm/dd ("${mdy}") order; pass an explicit date order (mdy | dmy)`);
  }
  if (dmy != null) return { order: 'dmy', ambiguous: false };
  return { order: 'mdy', ambiguous: numeric > 0 && mdy == null };
}

function mapColumns(header) {
  const norm = header.map(normalizeHeader);
  const cols = {};
  for (const [key, re] of Object.entries(COLUMN_PATTERNS)) {
    const idx = norm.findIndex((h) => re.test(h));
    if (idx >= 0) cols[key] = idx;
  }
  return { cols, norm };
}

/**
 * Parse CSV text. opts: { tz (chart time zone of the export, default America/New_York), includeOpen (keep a
 * trade whose exit signal is "Open", i.e. still open at the end of the test; default false),
 * dayTz (time zone for dayKey, default America/New_York), rollHour (hour in dayTz at/after which an exit
 * counts toward the next day's session; default SESSION_ROLL_HOUR = 18 for Apex / CME Globex sessions,
 * null = plain calendar date), delimiter (auto), decimal ('auto' | '.' | ','), dateOrder ('auto' | 'mdy' |
 * 'dmy'; 'auto' picks one order for the whole file, see detectDateOrder) }.
 * Returns { trades, delimiter, columns, warnings, fileWarnings } (fileWarnings: problems with the file as a
 * whole, such as missing optional columns; they are also the first entries of warnings).
 */
export function inspectTvCsv(text, opts = {}) {
  const { tz = NY, dayTz = NY, rollHour = SESSION_ROLL_HOUR, decimal = 'auto' } = opts;
  let dateOrder = opts.dateOrder ?? 'auto';
  if (!['auto', 'mdy', 'dmy'].includes(dateOrder)) throw new Error(`unknown date order "${dateOrder}" (expected auto | mdy | dmy)`);
  if (!['auto', '.', ','].includes(decimal)) throw new Error(`unknown decimal "${decimal}" (expected auto | . | ,)`);
  const src = String(text).replace(/^﻿/, '');
  const delimiter = opts.delimiter ?? detectDelimiter(src);
  const rows = parseCsvRows(src, delimiter);
  if (rows.length < 2) throw new Error('CSV has no data rows');
  const { cols, norm } = mapColumns(rows[0]);
  const missing = ['pnl', 'time'].filter((k) => cols[k] == null);
  if (missing.length) {
    throw new Error(`CSV is missing required column(s): ${missing.join(', ')} (headers: ${norm.join(' | ')})`);
  }
  const warnings = [];
  const fileWarnings = [];
  const cell = (row, key) => (cols[key] == null ? '' : (row[cols[key]] ?? '').trim());
  if (dateOrder === 'auto') {
    const det = detectDateOrder(rows.slice(1).map((row) => cell(row, 'time')));
    dateOrder = det.order;
    if (det.ambiguous) fileWarnings.push('date order is ambiguous (no day above 12): read as mm/dd; set the date order to dmy if the export uses dd/mm');
  }
  if (cols.contracts == null) {
    fileWarnings.push('no contracts column: every trade is read as 1 contract, so its whole P&L is taken as the per-contract P&L');
  }
  const noExcursion = ['runUp', 'drawdown'].filter((k) => cols[k] == null);
  if (noExcursion.length) {
    fileWarnings.push(
      `no ${noExcursion.map((k) => (k === 'runUp' ? 'Run-up' : 'Drawdown')).join('/')} column: intratrade excursions are unknown and fall back ` +
        'to each trade\'s close, so open-profit threshold lifts and intratrade breaches are missed (breach odds are optimistic)',
    );
  }
  const isExit = (row) => /exit|close/i.test(cell(row, 'type'));
  const isEntry = (row) => /entry|open/i.test(cell(row, 'type')) && !isExit(row);
  // A Type column that never says entry/exit (e.g. another language) cannot pick the exit row.
  const useType = cols.type != null && rows.slice(1).some(isExit);
  if (cols.type != null && !useType) {
    fileWarnings.push('Type column has no Exit rows: each trade\'s exit is taken as its latest row');
  }

  // Group rows by trade number (Entry row + Exit row per trade). Without a trade # column, each row is a trade.
  const groups = new Map();
  for (let r = 1; r < rows.length; r++) {
    const row = rows[r];
    let key;
    if (cols.tradeNo != null) {
      const n = parseNumber(cell(row, 'tradeNo'), '.');
      if (!Number.isFinite(n)) {
        warnings.push(`row ${r + 1}: no trade number, skipped`);
        continue;
      }
      key = n;
    } else {
      key = r;
    }
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }

  const trades = [];
  for (const [tradeNo, grp] of groups) {
    // Without a usable Type column, the exit is the row with the latest timestamp (exports list newest first).
    const latest = () => {
      let best = grp[grp.length - 1];
      let bestT = -Infinity;
      for (const row of grp) {
        const t = parseTvDate(cell(row, 'time'), { tz, dateOrder })?.getTime() ?? -Infinity;
        if (t > bestT) [best, bestT] = [row, t];
      }
      return best;
    };
    const exitRow = useType ? grp.find(isExit) : latest();
    if (!exitRow) {
      warnings.push(`trade ${tradeNo}: no exit row (truncated or filtered export?), skipped`);
      continue;
    }
    const entryRow = grp.find(isEntry) ?? (grp.length > 1 ? grp.find((r) => r !== exitRow) : null);
    if (!opts.includeOpen && /^open$/i.test(cell(exitRow, 'signal'))) {
      warnings.push(`trade ${tradeNo}: still open (exit signal "Open"), skipped`);
      continue;
    }
    const others = grp.filter((r) => r !== exitRow);
    const pick = (key) => {
      for (const row of [exitRow, ...others]) {
        const v = cell(row, key);
        if (v !== '') return v;
      }
      return '';
    };
    const pnl = parseNumber(pick('pnl'), decimal);
    if (!Number.isFinite(pnl)) {
      warnings.push(`trade ${tradeNo}: unreadable P&L "${pick('pnl')}", skipped`);
      continue;
    }
    const exitTime = parseTvDate(cell(exitRow, 'time') || pick('time'), { tz, dateOrder });
    if (!exitTime || Number.isNaN(exitTime.getTime())) {
      warnings.push(`trade ${tradeNo}: unreadable date "${cell(exitRow, 'time')}", skipped`);
      continue;
    }
    const entryTime = entryRow ? parseTvDate(cell(entryRow, 'time'), { tz, dateOrder }) : null;
    let contracts = Math.abs(parseNumber(pick('contracts'), decimal));
    if (!(contracts > 0)) {
      if (cols.contracts != null) warnings.push(`trade ${tradeNo}: unreadable contracts, assumed 1`);
      contracts = 1;
    }
    const runUpRaw = parseNumber(pick('runUp'), decimal);
    const ddRaw = parseNumber(pick('drawdown'), decimal);
    // The close is a point of the trade's path, so the excursions reach at least the close; a missing or
    // unreadable value falls back to it.
    const runUp = Math.max(Number.isFinite(runUpRaw) ? Math.abs(runUpRaw) : 0, pnl, 0);
    const drawdown = Math.min(Number.isFinite(ddRaw) ? 0 - Math.abs(ddRaw) : 0, pnl, 0); // printed positive in some versions
    const typeText = `${cell(exitRow, 'type')} ${entryRow ? cell(entryRow, 'type') : ''}`;
    const side = /short/i.test(typeText) ? 'short' : /long/i.test(typeText) ? 'long' : null;
    trades.push({
      tradeNo,
      side,
      entryTime,
      exitTime,
      dayKey: dayKeyOf(exitTime, dayTz, rollHour),
      contracts,
      pnl,
      runUp,
      drawdown,
      pnlPer: pnl / contracts,
      mfePer: runUp / contracts,
      maePer: 0 - Math.abs(drawdown) / contracts,
    });
  }
  trades.sort((a, b) => a.exitTime - b.exitTime || a.tradeNo - b.tradeNo);
  const columns = Object.fromEntries(Object.entries(cols).map(([k, i]) => [k, rows[0][i].replace(/^﻿/, '').trim()]));
  return { trades, delimiter, columns, warnings: [...fileWarnings, ...warnings], fileWarnings };
}

/** Parse CSV text into trades (see inspectTvCsv for options). */
export function parseTvCsv(text, opts = {}) {
  return inspectTvCsv(text, opts).trades;
}

/** Read and parse a CSV file. Returns { trades, delimiter, columns, warnings }. */
export function readTvCsv(path, opts = {}) {
  return inspectTvCsv(readFileSync(path, 'utf8'), opts);
}
