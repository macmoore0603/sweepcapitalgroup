// time.mjs - dependency-free time-zone helpers built on Intl (Node 22 ships full ICU).
// Used by tv-csv.mjs (CSV timestamps -> Date -> New York day key) and ledger.mjs (calendar-day expiry).

export const NY = 'America/New_York';
/**
 * New York hour at which an Apex / CME Globex session rolls to the next trading day: the session runs
 * 18:00 ET to 17:00 ET (flat by 16:59), so a trade exiting at or after 18:00 belongs to the next day's
 * session (as TradingView's time_tradingday counts it).
 */
export const SESSION_ROLL_HOUR = 18;
const DAY_MS = 86400000;
const fmtCache = new Map();

function formatter(tz) {
  let f = fmtCache.get(tz);
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      hourCycle: 'h23',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
    });
    fmtCache.set(tz, f);
  }
  return f;
}

/** Wall-clock fields of `date` in time zone `tz`. */
export function wallClock(date, tz = NY) {
  const o = {};
  for (const p of formatter(tz).formatToParts(date)) if (p.type !== 'literal') o[p.type] = Number(p.value);
  return { y: o.year, m: o.month, d: o.day, h: o.hour === 24 ? 0 : o.hour, mi: o.minute, s: o.second };
}

/** Offset (ms) of `tz` from UTC at instant `utcMs` (positive east of UTC). */
export function tzOffsetMs(utcMs, tz = NY) {
  const w = wallClock(new Date(utcMs), tz);
  const wholeSecond = utcMs - (((utcMs % 1000) + 1000) % 1000);
  return Date.UTC(w.y, w.m - 1, w.d, w.h, w.mi, w.s) - wholeSecond;
}

/** Convert a wall-clock time in `tz` to a UTC Date (handles DST transitions). */
export function zonedTimeToUtc(y, m, d, h = 0, mi = 0, s = 0, tz = NY) {
  const guess = Date.UTC(y, m - 1, d, h, mi, s);
  const off1 = tzOffsetMs(guess, tz);
  let utc = guess - off1;
  const off2 = tzOffsetMs(utc, tz);
  if (off2 !== off1) utc = guess - off2;
  return new Date(utc);
}

/**
 * YYYY-MM-DD of `date` in `tz` (default America/New_York).
 * rollHour (optional): wall-clock hour at/after which the time belongs to the next day's
 * session (e.g. 18 for CME Globex evenings). Default null = plain calendar date.
 */
export function dayKeyOf(date, tz = NY, rollHour = null) {
  const w = wallClock(date, tz);
  let t = Date.UTC(w.y, w.m - 1, w.d);
  if (rollHour != null && w.h >= rollHour) t += DAY_MS;
  return new Date(t).toISOString().slice(0, 10);
}

/** Integer day number for a 'YYYY-MM-DD' key, a Date (its New York date) or a number (returned as is). */
export function dayNumber(day) {
  if (typeof day === 'number') return day;
  if (day instanceof Date) return dayNumber(dayKeyOf(day));
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(day));
  if (!m) throw new Error(`bad day key "${day}" (expected YYYY-MM-DD)`);
  return Math.round(Date.UTC(+m[1], +m[2] - 1, +m[3]) / DAY_MS);
}

/** Calendar days from a to b (b - a). */
export function calendarDaysBetween(a, b) {
  return dayNumber(b) - dayNumber(a);
}

/** 'YYYY-MM-DD' + n calendar days. */
export function addDays(key, n) {
  return new Date((dayNumber(key) + n) * DAY_MS).toISOString().slice(0, 10);
}

/** Day of the week of a day key (or Date / day number): 0 = Sunday ... 6 = Saturday. */
export function weekday(day) {
  return new Date(dayNumber(day) * DAY_MS).getUTCDay();
}

/** True for Monday..Friday, the days that hold a trading session (exchange holidays are not modelled). */
export function isWeekday(day) {
  const w = weekday(day);
  return w >= 1 && w <= 5;
}

/**
 * Number of Monday..Friday sessions in a window of `calendarDays` calendar days, for a window starting on
 * each weekday Monday..Friday (index 0 = Monday). 30 calendar days -> [22, 22, 22, 22, 21].
 */
export function weekdaySessionsInWindow(calendarDays) {
  const out = [];
  for (let start = 1; start <= 5; start++) {
    let n = 0;
    for (let i = 0; i < calendarDays; i++) {
      const w = (start + i) % 7;
      if (w >= 1 && w <= 5) n++;
    }
    out.push(n);
  }
  return out;
}
