// ledger.mjs - Apex 50K Intraday trailing-drawdown ledger (EVAL and PA) as pure state + step functions.
//
// Every rule number comes from rules.json at runtime (loadRules); nothing is hard-coded here.
//
// APEX LEDGER SPEC (mirrored by the Pine strategy):
//   state: startBal, realized (closed P&L since attempt start, net of costs), peak, threshold, status.
//   init:  peak = startBal; threshold = startBal - maxDrawdown.
//   stopLevel: EVAL Rithmic/WealthCharts = evaluation.thresholdStopRithmic; EVAL Tradovate =
//          evaluation.thresholdStopTradovate (null = keeps trailing); PA = performanceAccount.thresholdStop.
//   observe(b): if b > peak { peak = b; threshold = max(threshold, min(peak - maxDrawdown, stopLevel)) }
//               then b <= threshold => BREACHED. Threshold never decreases.
//   ordering: 'conservative' (default) observes the favorable extreme, then the adverse extreme, then the
//             close; 'adverse-first' observes adverse, favorable, close.
//   EVAL pass: flat after a close and realized >= profitTarget. Open profit never counts.
//   EVAL expiry: not passed within accessDays calendar days of its first day => EXPIRED.
//   PA: tier from the prior session's closing balance; daily loss limit (session realized + open P&L at
//       the adverse extreme <= -DLL) flattens and halts the session (breach check first); payouts at end
//       of session.
//   Money is kept in whole cents (balances observed, realized, session and payout-window P&L are rounded
//   to the cent), so exact rule boundaries (+3,000.00 target, $1,500 tier, $200 day, threshold touch) are
//   not missed through binary floating-point drift.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { calendarDaysBetween } from './time.mjs';

export const ACTIVE = 'ACTIVE';
export const PASSED = 'PASSED';
export const BREACHED = 'BREACHED';
export const EXPIRED = 'EXPIRED';
export const STATUS = Object.freeze({ ACTIVE, PASSED, BREACHED, EXPIRED });

export const RULES_PATH = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'rules.json');

// ---------------------------------------------------------------------------------------------- rules

export function loadRules(path = RULES_PATH) {
  return validateRules(JSON.parse(readFileSync(path, 'utf8')));
}

export function validateRules(r) {
  const fail = (msg) => {
    throw new Error(`rules.json: ${msg}`);
  };
  const num = (v) => typeof v === 'number' && Number.isFinite(v);
  const numOrNull = (v) => v == null || num(v);
  if (!r || typeof r !== 'object') fail('not an object');
  if (!num(r.startBalance)) fail('startBalance must be a number');
  if (!num(r.microsPerMini) || r.microsPerMini <= 0) fail('microsPerMini must be a positive number');
  const e = r.evaluation;
  if (!e) fail('evaluation missing');
  for (const k of ['profitTarget', 'maxDrawdown', 'maxContractsMini', 'accessDays']) {
    if (!num(e[k])) fail(`evaluation.${k} must be a number`);
  }
  if (!numOrNull(e.thresholdStopRithmic)) fail('evaluation.thresholdStopRithmic must be a number or null');
  if (!numOrNull(e.thresholdStopTradovate)) fail('evaluation.thresholdStopTradovate must be a number or null');
  // Rules the planner does not model must stay unset, so a rules.json update cannot be silently ignored.
  const notModelled = (k) => fail(`evaluation.${k} is set (${JSON.stringify(e[k])}) but is not modelled by the planner`);
  if (e.dailyLossLimit != null) notModelled('dailyLossLimit');
  if (e.consistency != null) notModelled('consistency');
  if (e.minTradingDays != null && e.minTradingDays !== 0) notModelled('minTradingDays');
  const p = r.performanceAccount;
  if (!p) fail('performanceAccount missing');
  if (!num(p.maxDrawdown)) fail('performanceAccount.maxDrawdown must be a number');
  if (!numOrNull(p.thresholdStop)) fail('performanceAccount.thresholdStop must be a number or null');
  if (!Array.isArray(p.tiers) || p.tiers.length === 0) fail('performanceAccount.tiers must be a non-empty array');
  p.tiers.forEach((t, i) => {
    for (const k of ['minProfit', 'maxContractsMini', 'dailyLossLimit']) {
      if (!num(t[k])) fail(`performanceAccount.tiers[${i}].${k} must be a number`);
    }
  });
  const po = p.payout;
  if (!po) fail('performanceAccount.payout missing');
  for (const k of [
    'minQualifyingDays',
    'minDailyProfit',
    'consistencyMaxDayShare',
    'safetyNet',
    'minBalanceToRequest',
    'minPayout',
    'maxPayouts',
  ]) {
    if (!num(po[k])) fail(`performanceAccount.payout.${k} must be a number`);
  }
  if (!Array.isArray(po.maxPerRequest) || po.maxPerRequest.length === 0 || !po.maxPerRequest.every(num)) {
    fail('performanceAccount.payout.maxPerRequest must be a non-empty array of numbers');
  }
  return r;
}

// ---------------------------------------------------------------------------------------------- options

export function normalizeFeed(feed = 'rithmic') {
  const f = String(feed ?? 'rithmic').toLowerCase();
  if (f.includes('tradovate')) return 'tradovate';
  if (f.includes('rithmic') || f.includes('wealthcharts')) return 'rithmic';
  throw new Error(`unknown feed "${feed}" (expected rithmic | tradovate)`);
}

export function normalizeOrder(order = 'conservative') {
  const o = String(order ?? 'conservative').toLowerCase();
  if (o === 'conservative' || o === 'favorable-first') return 'conservative';
  if (o === 'adverse-first' || o === 'adverse') return 'adverse-first';
  throw new Error(`unknown order "${order}" (expected conservative | adverse-first)`);
}

export function normalizeUnit(unit = 'mini') {
  const u = String(unit ?? 'mini').toLowerCase();
  if (u === 'mini' || u === 'minis') return 'mini';
  if (u === 'micro' || u === 'micros') return 'micro';
  throw new Error(`unknown unit "${unit}" (expected mini | micro)`);
}

export function normalizeDllFill(fill = 'extreme') {
  const f = String(fill ?? 'extreme').toLowerCase();
  if (f === 'extreme' || f === 'limit') return f;
  throw new Error(`unknown DLL fill "${fill}" (expected extreme | limit)`);
}

/** EVAL threshold stop for a feed; Infinity when the feed keeps trailing (null in rules.json). */
export function evalStopLevel(rules, feed) {
  const e = rules.evaluation;
  const v = normalizeFeed(feed) === 'tradovate' ? e.thresholdStopTradovate : e.thresholdStopRithmic;
  return v == null ? Infinity : v;
}

export function paStopLevel(rules) {
  const v = rules.performanceAccount.thresholdStop;
  return v == null ? Infinity : v;
}

// ---------------------------------------------------------------------------------------------- construction

function baseLedger(kind, rules, maxDrawdown, stopLevel, opts) {
  const startBal = rules.startBalance;
  return {
    kind,
    startBal,
    realized: 0,
    peak: startBal,
    threshold: startBal - maxDrawdown,
    maxDrawdown,
    stopLevel,
    // `trailing: false` freezes the threshold at its initial value. Internal, for tests only.
    trailing: opts.trailing !== false,
    order: normalizeOrder(opts.order),
    microsPerMini: rules.microsPerMini,
    status: ACTIVE,
    reason: null,
    trades: 0,
  };
}

/** opts: { feed: 'rithmic'|'tradovate', order: 'conservative'|'adverse-first', firstDay } */
export function makeEvalLedger(rules, opts = {}) {
  const e = rules.evaluation;
  const L = baseLedger('EVAL', rules, e.maxDrawdown, evalStopLevel(rules, opts.feed), opts);
  L.feed = normalizeFeed(opts.feed);
  L.profitTarget = e.profitTarget;
  L.accessDays = e.accessDays;
  L.maxContractsMini = e.maxContractsMini;
  L.firstDay = opts.firstDay ?? null;
  return L;
}

/** opts: { order, dllFill: 'extreme'|'limit' (see stepTradeRaw), firstDay } */
export function makePaLedger(rules, opts = {}) {
  const pa = rules.performanceAccount;
  const L = baseLedger('PA', rules, pa.maxDrawdown, paStopLevel(rules), opts);
  L.dllFill = normalizeDllFill(opts.dllFill);
  L.tiers = pa.tiers;
  L.payoutRules = pa.payout;
  L.tier = tierFor(pa.tiers, 0); // first session: prior close = start balance
  L.dayKey = opts.firstDay ?? null;
  L.dayStartRealized = 0;
  L.dayHalted = false;
  L.dllHits = 0;
  L.lastDayPnl = 0;
  L.qualDays = 0; // qualifying days since the last payout
  L.windowProfit = 0; // total net profit since the last payout
  L.windowMaxDay = 0; // largest profitable day since the last payout
  L.payouts = 0;
  L.paid = 0;
  L.payoutHistory = [];
  return L;
}

// ---------------------------------------------------------------------------------------------- queries

export function balance(L, openPnl = 0) {
  return L.startBal + L.realized + openPnl;
}

/** Session P&L (PA): realized today + open P&L, in cents. */
export function sessionPnl(L, openPnl = 0) {
  return cents(L.realized - (L.dayStartRealized ?? 0) + openPnl);
}

/**
 * PA tier = highest tier whose minProfit <= profit (profit = prior session closing balance - start
 * balance); never below the lowest tier (Level 1). Accepts the tiers array or the whole rules object.
 */
export function tierFor(tiers, profit) {
  if (!Array.isArray(tiers)) tiers = tiers.performanceAccount.tiers;
  let best = null;
  let floor = tiers[0];
  for (const t of tiers) {
    if (t.minProfit < floor.minProfit) floor = t;
    if (t.minProfit <= profit && (best === null || t.minProfit > best.minProfit)) best = t;
  }
  return best ?? floor;
}

/** Max contracts right now: EVAL = evaluation.maxContractsMini; PA = current tier. x microsPerMini for micros. */
export function contractCap(L, unit = 'mini') {
  const minis = L.kind === 'EVAL' ? L.maxContractsMini : L.tier.maxContractsMini;
  return normalizeUnit(unit) === 'micro' ? minis * L.microsPerMini : minis;
}

// ---------------------------------------------------------------------------------------------- steps

/** Observe one balance print b = startBal + realized + openPnL. Returns the status. */
export function observe(L, b) {
  if (L.status !== ACTIVE) return L.status;
  b = cents(b);
  if (b > L.peak) {
    L.peak = b;
    if (L.trailing) {
      const t = cents(Math.min(b - L.maxDrawdown, L.stopLevel));
      if (t > L.threshold) L.threshold = t;
    }
  }
  if (b <= L.threshold) {
    L.status = BREACHED;
    L.breachBalance = b;
    L.reason = `balance ${cents(b)} touched threshold ${cents(L.threshold)}`;
  }
  return L.status;
}

/**
 * Apply one complete trade (all values in $ for the whole position):
 *   favorable = best open P&L (>= 0), adverse = worst open P&L (<= 0), close = realized P&L net of
 *   costs, cost = round-trip cost (used only when a PA daily-loss flatten replaces the close).
 * Order follows L.order. Each extreme is observe()d (breach check) as it is reached.
 * PA daily loss limit: when session P&L at the adverse extreme (realized today + adverse) <= -DLL the
 * position is flattened, the rest of the session is skipped and the account stays open. Where it is
 * flattened is L.dllFill:
 *   'extreme' (default, conservative, same precedence as the Pine strategy): the breach check runs on the
 *             true adverse extreme first, and the flatten books adverse - cost.
 *   'limit':  the platform liquidates exactly at the limit, so the adverse extreme is capped at the DLL
 *             level before the breach check (a DLL above the threshold then prevents the breach).
 * Either way, when the trailing threshold is at or above the DLL level the threshold is touched first.
 */
export function stepTradeRaw(L, favorable, adverse, close, cost = 0) {
  if (L.status !== ACTIVE) return L.status;
  if (L.kind === 'PA' && L.dayHalted) return L.status; // no more trades this session
  L.trades++;
  let adv = cents(adverse);
  let flatten = false;
  if (L.kind === 'PA') {
    const lim = -L.tier.dailyLossLimit - sessionPnl(L); // open P&L where session P&L = -DLL
    if (adv <= lim) {
      flatten = true;
      if (L.dllFill === 'limit') adv = lim;
    }
  }
  const base = L.startBal + L.realized;
  if (L.order === 'adverse-first') {
    if (observe(L, base + adv) !== ACTIVE) return L.status;
    if (!flatten && observe(L, base + favorable) !== ACTIVE) return L.status;
  } else {
    if (observe(L, base + favorable) !== ACTIVE) return L.status;
    if (observe(L, base + adv) !== ACTIVE) return L.status;
  }
  if (flatten) {
    L.dllHits++;
    return closeTrade(L, adv - cost, true);
  }
  return closeTrade(L, close, false);
}

/** Object form: stepTrade(L, { favorable, adverse, close, cost }). `pnl` is accepted for `close`. */
export function stepTrade(L, t) {
  return stepTradeRaw(L, t.favorable ?? 0, t.adverse ?? 0, t.close ?? t.pnl ?? 0, t.cost ?? 0);
}

/** Per-contract trade -> position values for q contracts with an extra round-trip cost per contract. */
export function scaleTrade(t, q, extraCost = 0) {
  return {
    favorable: q * t.mfePer,
    adverse: q * t.maePer,
    close: q * t.pnlPer - q * extraCost,
    cost: q * extraCost,
  };
}

/** Close the open position with net P&L `pnl`; observes the flat balance, then EVAL pass / PA DLL. */
export function closeTrade(L, pnl, dllFlatten = false) {
  if (L.status !== ACTIVE) return L.status;
  L.realized = cents(L.realized + pnl);
  if (observe(L, L.startBal + L.realized) !== ACTIVE) return L.status;
  if (L.kind === 'EVAL') {
    checkPass(L);
  } else if (dllFlatten || sessionPnl(L) <= -L.tier.dailyLossLimit) {
    L.dayHalted = true;
  }
  return L.status;
}

/** EVAL pass: flat and startBal + realized >= startBal + profitTarget. */
export function checkPass(L) {
  if (L.kind === 'EVAL' && L.status === ACTIVE && L.realized >= L.profitTarget) {
    L.status = PASSED;
    L.reason = `realized ${cents(L.realized)} >= target ${L.profitTarget} while flat`;
  }
  return L.status;
}

/**
 * EVAL expiry. `day` is a 'YYYY-MM-DD' key (New York date), a Date or an integer day number.
 * The first call fixes the attempt's first day; the attempt expires once `day` is accessDays or more
 * calendar days after it (first day + accessDays - 1 is the last tradable day).
 */
export function checkExpiry(L, day) {
  if (L.kind !== 'EVAL' || L.status !== ACTIVE) return L.status;
  if (L.firstDay == null) {
    L.firstDay = day;
    return L.status;
  }
  const elapsed = calendarDaysBetween(L.firstDay, day);
  if (elapsed >= L.accessDays) {
    L.status = EXPIRED;
    L.reason = `${elapsed} calendar days since first day ${L.firstDay} >= ${L.accessDays}`;
  }
  return L.status;
}

/** Mark an ACTIVE attempt EXPIRED (used by the Monte Carlo when its trading-day budget runs out). */
export function expire(L, reason = 'access period ended') {
  if (L.status === ACTIVE) {
    L.status = EXPIRED;
    L.reason = reason;
  }
  return L.status;
}

/**
 * Start a session. EVAL: expiry check. PA: tier from the prior session's closing balance
 * (balance now, flat, after any payout), reset session P&L and the DLL halt.
 */
export function startDay(L, day) {
  if (L.status !== ACTIVE) return L.status;
  if (L.kind === 'EVAL') return checkExpiry(L, day);
  L.dayKey = day;
  L.dayStartRealized = L.realized;
  L.dayHalted = false;
  L.tier = tierFor(L.tiers, L.realized); // closing balance - startBal == realized
  return L.status;
}

/**
 * Payout eligibility right now (PA), without changing anything:
 * >= minQualifyingDays days with net P&L >= minDailyProfit since the last payout; largest profitable day
 * since the last payout < consistencyMaxDayShare x total profit since the last payout; balance >=
 * minBalanceToRequest; amount = min(maxPerRequest[k], balance - safetyNet) >= minPayout; k < maxPayouts.
 */
export function payoutCheck(L) {
  const P = L.payoutRules;
  const bal = cents(L.startBal + L.realized);
  const cap = P.maxPerRequest[Math.min(L.payouts, P.maxPerRequest.length - 1)];
  const amount = cents(Math.min(cap, bal - P.safetyNet));
  const countOk = L.payouts < P.maxPayouts;
  const daysOk = L.qualDays >= P.minQualifyingDays;
  const consistencyOk = L.windowProfit > 0 && L.windowMaxDay < P.consistencyMaxDayShare * L.windowProfit;
  const balanceOk = bal >= P.minBalanceToRequest;
  const minPayoutOk = amount >= P.minPayout;
  return {
    eligible: L.status === ACTIVE && countOk && daysOk && consistencyOk && balanceOk && minPayoutOk,
    amount: Math.max(0, amount),
    balance: bal,
    countOk,
    daysOk,
    consistencyOk,
    balanceOk,
    minPayoutOk,
    qualDays: L.qualDays,
    windowProfit: L.windowProfit,
    windowMaxDay: L.windowMaxDay,
  };
}

/**
 * End a session. PA: books the day into the payout window and requests a payout when eligible
 * (balance -= amount, window and qualifying-day count reset). Returns the amount paid (0 if none).
 */
export function endDay(L) {
  if (L.kind !== 'PA' || L.status !== ACTIVE) return 0;
  const P = L.payoutRules;
  const dayPnl = sessionPnl(L);
  L.lastDayPnl = dayPnl;
  L.windowProfit = cents(L.windowProfit + dayPnl);
  if (dayPnl >= P.minDailyProfit) L.qualDays++;
  if (dayPnl > L.windowMaxDay) L.windowMaxDay = dayPnl;
  L.dayStartRealized = L.realized; // the session is closed
  const c = payoutCheck(L);
  if (!c.eligible) return 0;
  L.realized = cents(L.realized - c.amount);
  L.paid = cents(L.paid + c.amount);
  L.payouts++;
  L.payoutHistory.push({ n: L.payouts, day: L.dayKey, amount: c.amount, balanceAfter: L.startBal + L.realized });
  L.qualDays = 0;
  L.windowProfit = 0;
  L.windowMaxDay = 0;
  L.dayStartRealized = L.realized;
  return c.amount;
}

/** True once the PA has taken every payout rules.json allows. */
export function payoutsDone(L) {
  return L.kind === 'PA' && L.payouts >= L.payoutRules.maxPayouts;
}

/** Round dollars to whole cents (Infinity passes through). */
export function cents(x) {
  return Math.round(x * 100) / 100;
}
