// sim.mjs - Monte Carlo of Apex 50K evaluation attempts and the performance account (PA) after a pass.
//
// Trade sources produce whole trading sessions of per-contract trades (pnlPer, mfePer, maePer); a session
// can hold no trades. A trade at q contracts is favorable = q*mfePer, adverse = q*maePer,
// close = q*pnlPer - q*extraCost, and is fed to the ledger in ledger.mjs (which holds every rule). All
// randomness is seeded (mulberry32) for reproducibility.

import {
  ACTIVE,
  PASSED,
  BREACHED,
  EXPIRED,
  makeEvalLedger,
  makePaLedger,
  stepTradeRaw,
  startDay,
  endDay,
  checkExpiry,
  expire,
  normalizeFeed,
  normalizeOrder,
  normalizeUnit,
  normalizeDllFill,
} from './ledger.mjs';
import { addDays, calendarDaysBetween, isWeekday, weekdaySessionsInWindow } from './time.mjs';

// ---------------------------------------------------------------------------------------------- RNG

export function mulberry32(seed) {
  let a = seed >>> 0;
  return function rng() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function fmix32(h) {
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13;
  h = Math.imul(h, 0xc2b2ae35);
  h ^= h >>> 16;
  return h >>> 0;
}

/** Independent seed for path i of a stream, so path i sees the same numbers at every size. */
export function pathSeed(seed, stream, i) {
  return fmix32((fmix32((seed >>> 0) ^ fmix32(stream)) + Math.imul(i + 1, 0x9e3779b1)) >>> 0);
}

const EVAL_STREAM = 0x4556414c; // 'EVAL'
const PA_STREAM = 0x50410000; // 'PA'

// ---------------------------------------------------------------------------------------------- sources

const byTime = (a, b) => (a.exitTime && b.exitTime ? a.exitTime - b.exitTime : 0) || (a.tradeNo ?? 0) - (b.tradeNo ?? 0);

/** Group trades into trading days (chronological), keeping each day's trades in exit order. */
export function groupTradesByDay(trades) {
  const map = new Map();
  for (const t of trades) {
    if (!map.has(t.dayKey)) map.set(t.dayKey, []);
    map.get(t.dayKey).push(t);
  }
  return [...map.keys()].sort().map((dayKey) => ({ dayKey, trades: map.get(dayKey).slice().sort(byTime) }));
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Every trading session from the first to the last traded day: each Monday..Friday plus any other day
 * that holds trades (exchange holidays are not known, so they count as sessions without trades).
 * Day keys that are not 'YYYY-MM-DD' have no calendar, so only the traded days are returned.
 */
export function sessionCalendar(days) {
  const keys = days.map((d) => d.dayKey);
  if (keys.length === 0 || !keys.every((k) => ISO_DAY.test(String(k)))) return keys;
  const traded = new Set(keys);
  const out = [];
  for (let k = keys[0]; k <= keys[keys.length - 1]; k = addDays(k, 1)) if (traded.has(k) || isWeekday(k)) out.push(k);
  return out;
}

/**
 * Empirical source: bootstrap whole trading sessions (with replacement) from parsed CSV trades. The pool is
 * every session from the first to the last traded day (see sessionCalendar), so sessions without trades
 * are drawn with their real frequency and a 21-22 session access window holds as much trading as it did
 * historically. Keeps the real number of trades per session and their order within the session.
 * extraCost is per contract round trip (default 0: TradingView P&L already includes the strategy's
 * commission).
 */
/**
 * Risk multipliers the risk-scaling sweep tries by default (each trade's as-traded size times k, capped at the
 * plan's contract limit). 1 = the size the strategy actually traded.
 */
export const RISK_MULTIPLIERS = Object.freeze([1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60]);

/**
 * Empirical source from parsed CSV trades. scaling 'contracts' (default): every trade is resized to the
 * simulated size, the right model for a fixed-size strategy. scaling 'risk': every trade keeps its own
 * as-traded size times the simulated multiplier, capped at the plan's contract limit, the right model for a
 * strategy that sizes each trade by dollar risk (stop width varies, so contracts vary).
 */
export function makeEmpiricalSource(trades, { extraCost = 0, scaling = 'contracts' } = {}) {
  if (!trades || trades.length === 0) throw new Error('empirical source needs at least one trade');
  if (scaling !== 'contracts' && scaling !== 'risk') throw new Error(`scaling must be 'contracts' or 'risk', got "${scaling}"`);
  const days = groupTradesByDay(trades);
  const byKey = new Map(days.map((d) => [d.dayKey, d]));
  const sessions = sessionCalendar(days);
  const data = new Float64Array(trades.length * 3);
  const qty = new Float64Array(trades.length); // as-traded contracts per trade, aligned with data / 3
  const start = new Int32Array(sessions.length);
  const len = new Int32Array(sessions.length);
  let k = 0;
  let sumPnl = 0;
  let wins = 0;
  sessions.forEach((key, i) => {
    const d = byKey.get(key);
    start[i] = k;
    len[i] = d ? d.trades.length : 0;
    if (!d) return;
    for (const t of d.trades) {
      data[3 * k] = t.pnlPer;
      data[3 * k + 1] = t.mfePer;
      data[3 * k + 2] = t.maePer;
      qty[k] = t.contracts >= 1 ? t.contracts : 1;
      sumPnl += t.pnlPer;
      if (t.pnlPer > 0) wins++;
      k++;
    }
  });
  const nSessions = sessions.length;
  let minQty = Infinity;
  let maxQty = 0;
  for (let i = 0; i < qty.length; i++) {
    if (qty[i] < minQty) minQty = qty[i];
    if (qty[i] > maxQty) maxQty = qty[i];
  }
  return {
    kind: 'empirical',
    scaling,
    extraCost,
    qty,
    minQty,
    maxQty,
    buf: data,
    off: 0,
    days: days.length, // sessions with at least one trade
    sessions: nSessions, // every session in the pool, with or without trades
    activeShare: days.length / nSessions,
    trades: trades.length,
    firstDay: days[0].dayKey,
    lastDay: days[days.length - 1].dayKey,
    tradesPerDay: trades.length / nSessions, // per session
    tradesPerActiveDay: trades.length / days.length,
    winRate: wins / trades.length,
    expectancyPerContract: sumPnl / trades.length - extraCost,
    sampleDay(rng) {
      const i = Math.floor(rng() * nSessions);
      this.off = 3 * start[i];
      return len[i];
    },
  };
}

export const PARAMETRIC_DEFAULTS = Object.freeze({
  avgLossR: 1,
  mfeOnLosersR: 0.3,
  maeOnWinnersR: 0.5,
  tradesPerDay: 1,
  costPerContract: 0,
  rSpread: 0,
});

/**
 * Parametric source: { winRate, avgWinR, avgLossR=1, riskPerContract ($ per 1R per contract),
 * mfeOnLosersR=0.3 (losers first run this far in favor), maeOnWinnersR=0.5 (winners first dip this far),
 * tradesPerDay (fraction allowed: whole part + Bernoulli remainder), costPerContract (round trip $),
 * rSpread=0 (each trade's 1R is scaled by a factor drawn uniformly from [1-rSpread, 1+rSpread], mean 1, so
 * expectancy is unchanged; it stands in for stops of different widths at a fixed size and removes the
 * lattice effect where fixed +-1R steps hit the target or the drawdown in exact multiples) }.
 * Path model: a loser runs up mfeOnLosersR, then falls to its stop and exits there; a winner dips
 * maeOnWinnersR, then runs to its target and exits there. A winner's run to the target is its exit, so it
 * is observed by the close; the winner's favorable value is its run-up before the dip, which is 0. Both
 * trades then follow the model's path under either intratrade order.
 */
export function makeParametricSource(params) {
  const p = { ...PARAMETRIC_DEFAULTS, ...params };
  const bad = (m) => {
    throw new Error(`parametric source: ${m}`);
  };
  if (!(p.winRate >= 0 && p.winRate <= 1)) bad('winRate must be in [0, 1]');
  if (!(p.avgWinR > 0)) bad('avgWinR must be > 0');
  if (!(p.avgLossR > 0)) bad('avgLossR must be > 0');
  if (!(p.riskPerContract > 0)) bad('riskPerContract must be > 0');
  if (!(p.tradesPerDay > 0)) bad('tradesPerDay must be > 0');
  if (!(p.costPerContract >= 0)) bad('costPerContract must be >= 0');
  if (!(p.rSpread >= 0 && p.rSpread < 1)) bad('rSpread must be in [0, 1)');
  const R = p.riskPerContract;
  const winPnl = p.avgWinR * R;
  const lossPnl = -p.avgLossR * R;
  const winMfe = 0; // run-up before the dip; the run to the target is the close (see above)
  const winMae = Math.max(-Math.abs(p.maeOnWinnersR) * R, lossPnl); // a winner cannot dip through its stop
  const lossMfe = Math.min(Math.abs(p.mfeOnLosersR) * R, winPnl); // a loser cannot run through its target
  const lossMae = lossPnl;
  const whole = Math.floor(p.tradesPerDay);
  const frac = p.tradesPerDay - whole;
  const buf = new Float64Array(3 * (whole + 1));
  const win = p.winRate;
  const spread = p.rSpread;
  return {
    kind: 'parametric',
    params: p,
    extraCost: p.costPerContract,
    buf,
    off: 0,
    tradesPerDay: p.tradesPerDay,
    winRate: win,
    expectancyPerContract: win * winPnl + (1 - win) * lossPnl - p.costPerContract,
    expectancyBeforeCosts: win * winPnl + (1 - win) * lossPnl,
    sampleDay(rng) {
      let n = whole;
      if (frac > 0 && rng() < frac) n++;
      for (let i = 0, k = 0; i < n; i++, k += 3) {
        const f = spread > 0 ? 1 + spread * (2 * rng() - 1) : 1; // no extra draw when spread is 0
        if (rng() < win) {
          buf[k] = winPnl * f;
          buf[k + 1] = winMfe * f;
          buf[k + 2] = winMae * f;
        } else {
          buf[k] = lossPnl * f;
          buf[k + 1] = lossMfe * f;
          buf[k + 2] = lossMae * f;
        }
      }
      return n;
    },
  };
}

/** Win rate at which expectancy before costs is exactly 0: w*avgWinR = (1-w)*avgLossR. */
export function zeroEdgeWinRate(avgWinR, avgLossR = 1) {
  return avgLossR / (avgWinR + avgLossR);
}

/** Zero-edge baseline: the same parametric params with winRate set so expectancy before costs is 0. */
export function zeroEdgeParams(params) {
  const p = { ...PARAMETRIC_DEFAULTS, ...params };
  return { ...p, winRate: zeroEdgeWinRate(p.avgWinR, p.avgLossR) };
}

export function makeZeroEdgeSource(params) {
  return makeParametricSource(zeroEdgeParams(params));
}

// ---------------------------------------------------------------------------------------------- stats

export function quantileSorted(sorted, q) {
  if (sorted.length === 0) return null;
  const i = Math.min(sorted.length - 1, Math.max(0, Math.ceil(q * sorted.length) - 1)); // nearest rank
  return sorted[i];
}

export function mean(arr) {
  if (arr.length === 0) return 0;
  let s = 0;
  for (let i = 0; i < arr.length; i++) s += arr[i];
  return s / arr.length;
}

export function sortedCopy(arr) {
  return Float64Array.from(arr).sort();
}

// ---------------------------------------------------------------------------------------------- options

/**
 * Trading sessions in one evaluation attempt: `tradingDays` when given, else the Monday..Friday sessions in
 * rules.json evaluation.accessDays calendar days for each start weekday (30 days -> 22, 22, 22, 22, 21).
 */
export function evalSessionBudgets(rules, tradingDays = null) {
  return tradingDays != null ? [tradingDays] : weekdaySessionsInWindow(rules.evaluation.accessDays);
}

function simOptions(rules, o = {}) {
  const unit = normalizeUnit(o.unit ?? 'mini');
  return {
    contracts: o.contracts ?? 1,
    attempts: o.attempts ?? 20000,
    tradingDays: o.tradingDays ?? null, // null: derived from rules.json accessDays (evalSessionBudgets)
    sessionBudgets: evalSessionBudgets(rules, o.tradingDays ?? null),
    horizonDays: o.horizonDays ?? 120,
    paRuns: o.paRuns ?? o.attempts ?? 20000,
    feed: normalizeFeed(o.feed ?? 'rithmic'),
    order: normalizeOrder(o.order ?? 'conservative'),
    dllFill: normalizeDllFill(o.dllFill ?? 'extreme'),
    seed: (o.seed ?? 1) >>> 0,
    fee: o.fee ?? 0,
    unit,
    trailing: o.trailing !== false, // internal: false freezes the threshold (tests only)
    mode: o.mode ?? 'both',
    evalCap: rules.evaluation.maxContractsMini * (unit === 'micro' ? rules.microsPerMini : 1),
  };
}

function assertSize(q) {
  if (!(Number.isInteger(q) && q >= 1)) throw new Error(`contracts must be a positive integer, got ${q}`);
}

// ---------------------------------------------------------------------------------------------- evaluation

/**
 * Simulate `attempts` independent evaluation attempts at `contracts` contracts, each lasting at most
 * `tradingDays` trading sessions (default: the sessions in rules.json accessDays calendar days, for a start
 * weekday drawn per attempt; see evalSessionBudgets). Per trade: favorable, then adverse (conservative
 * order; or adverse-first), then close. PASSED when flat with realized >= target.
 */
export function simulateEval(rules, source, opts = {}) {
  const o = simOptions(rules, opts);
  assertSize(o.contracts);
  const risk = source.scaling === 'risk';
  const q = risk ? o.contracts : Math.min(o.contracts, o.evalCap);
  const qty = source.qty;
  const cost = source.extraCost;
  let cappedTrades = 0;
  const passDays = [];
  let passed = 0;
  let breached = 0;
  let expired = 0;
  let trades = 0;
  const budgets = o.sessionBudgets;
  for (let a = 0; a < o.attempts; a++) {
    const rng = mulberry32(pathSeed(o.seed, EVAL_STREAM, a));
    const L = makeEvalLedger(rules, { feed: o.feed, order: o.order, trailing: o.trailing });
    const budget = budgets.length === 1 ? budgets[0] : budgets[Math.floor(rng() * budgets.length)];
    let d = 0;
    while (d < budget && L.status === ACTIVE) {
      d++;
      const n = source.sampleDay(rng);
      const buf = source.buf;
      const off = source.off;
      for (let i = 0, k = off; i < n; i++, k += 3) {
        let c = q;
        if (risk) {
          const want = q * qty[k / 3];
          c = want > o.evalCap ? o.evalCap : want;
          if (c < want) cappedTrades++;
        }
        stepTradeRaw(L, c * buf[k + 1], c * buf[k + 2], c * buf[k] - c * cost, c * cost);
        trades++;
        if (L.status !== ACTIVE) break;
      }
    }
    if (L.status === ACTIVE) expire(L, `no pass within ${budget} trading sessions`);
    if (L.status === PASSED) {
      passed++;
      passDays.push(d);
    } else if (L.status === BREACHED) breached++;
    else if (L.status === EXPIRED) expired++;
  }
  const N = o.attempts;
  const pPass = passed / N;
  const sortedDays = sortedCopy(passDays);
  return {
    contracts: q,
    scaling: risk ? 'risk' : 'contracts',
    requestedContracts: o.contracts,
    capped: risk ? cappedTrades > 0 : q < o.contracts,
    cappedTradeShare: risk ? (trades > 0 ? cappedTrades / trades : 0) : null,
    attempts: N,
    sessionBudgets: budgets,
    passed,
    breached,
    expired,
    pPass,
    pBreach: breached / N,
    pExpire: expired / N,
    pPassStdErr: Math.sqrt((pPass * (1 - pPass)) / N),
    medianDaysToPass: quantileSorted(sortedDays, 0.5),
    p90DaysToPass: quantileSorted(sortedDays, 0.9),
    meanDaysToPass: passed ? mean(passDays) : null,
    attemptsPerPass: pPass > 0 ? 1 / pPass : Infinity,
    feesPerPass: o.fee > 0 ? (pPass > 0 ? o.fee / pPass : Infinity) : 0,
    tradesSimulated: trades,
  };
}

// ---------------------------------------------------------------------------------------------- performance account

/**
 * Simulate `paRuns` fresh PAs for up to `horizonDays` trading days at `contracts` contracts, capped each
 * session by the tier (from the prior session close). DLL halts the session; payouts per ledger.endDay;
 * stops after the last allowed payout or a breach.
 */
export function simulatePa(rules, source, opts = {}) {
  const o = simOptions(rules, opts);
  assertSize(o.contracts);
  const risk = source.scaling === 'risk';
  const qty = source.qty;
  const cost = source.extraCost;
  const R = o.paRuns;
  const maxPayouts = rules.performanceAccount.payout.maxPayouts;
  const unitMult = o.unit === 'micro' ? rules.microsPerMini : 1;
  const payouts = new Float64Array(R);
  const paid = new Float64Array(R);
  const firstPayoutDays = [];
  let withPayout = 0;
  let breachedBeforeFirst = 0;
  let breachedAny = 0;
  let allPayouts = 0;
  let dllDays = 0;
  let tradingDaysUsed = 0;
  for (let r = 0; r < R; r++) {
    const rng = mulberry32(pathSeed(o.seed, PA_STREAM, r));
    const L = makePaLedger(rules, { order: o.order, trailing: o.trailing, dllFill: o.dllFill });
    let firstPayoutDay = 0;
    for (let d = 1; d <= o.horizonDays; d++) {
      startDay(L, d);
      const capU = L.tier.maxContractsMini * unitMult; // == contractCap(L, o.unit)
      const q = Math.min(o.contracts, capU);
      const n = source.sampleDay(rng);
      const buf = source.buf;
      const off = source.off;
      for (let i = 0, k = off; i < n; i++, k += 3) {
        if (L.dayHalted) break;
        const c = risk ? Math.min(o.contracts * qty[k / 3], capU) : q;
        stepTradeRaw(L, c * buf[k + 1], c * buf[k + 2], c * buf[k] - c * cost, c * cost);
        if (L.status !== ACTIVE) break;
      }
      tradingDaysUsed++;
      if (L.status !== ACTIVE) break;
      if (L.dayHalted) dllDays++;
      const p = endDay(L);
      if (p > 0 && firstPayoutDay === 0) firstPayoutDay = d;
      if (L.payouts >= maxPayouts) break;
    }
    payouts[r] = L.payouts;
    paid[r] = L.paid;
    if (L.payouts > 0) {
      withPayout++;
      firstPayoutDays.push(firstPayoutDay);
    }
    if (L.payouts >= maxPayouts) allPayouts++;
    if (L.status === BREACHED) {
      breachedAny++;
      if (L.payouts === 0) breachedBeforeFirst++;
    }
  }
  const sp = sortedCopy(payouts);
  const sd = sortedCopy(paid);
  return {
    contracts: o.contracts,
    scaling: risk ? 'risk' : 'contracts',
    runs: R,
    horizonDays: o.horizonDays,
    pPayout: withPayout / R,
    meanPayouts: mean(payouts),
    medianPayouts: quantileSorted(sp, 0.5),
    meanPaid: mean(paid),
    medianPaid: quantileSorted(sd, 0.5),
    p90Paid: quantileSorted(sd, 0.9),
    pBreachBeforeFirstPayout: breachedBeforeFirst / R,
    pBreach: breachedAny / R,
    pAllPayouts: allPayouts / R,
    medianDaysToFirstPayout: quantileSorted(sortedCopy(firstPayoutDays), 0.5),
    dllDaysPerRun: dllDays / R,
    tradingDaysPerRun: tradingDaysUsed / R,
  };
}

// ---------------------------------------------------------------------------------------------- sizes

/** Evaluation + PA for one size (mode 'eval' | 'pa' | 'both') plus combined per-attempt economics. */
export function runSize(rules, source, opts = {}) {
  const o = simOptions(rules, opts);
  const ev = o.mode === 'pa' ? null : simulateEval(rules, source, o);
  const pa = o.mode === 'eval' ? null : simulatePa(rules, source, o);
  let combined = null;
  if (ev && pa) {
    const paidPerAttempt = ev.pPass * pa.meanPaid;
    combined = {
      pPassAndPayout: ev.pPass * pa.pPayout,
      expectedPaidPerAttempt: paidPerAttempt,
      expectedNetPerAttempt: paidPerAttempt - o.fee,
      paidPerFee: o.fee > 0 ? paidPerAttempt / o.fee : null,
    };
  }
  return { contracts: o.contracts, eval: ev, pa, combined };
}

function argmax(rows, f) {
  let best = null;
  let bestV = -Infinity;
  for (const r of rows) {
    const v = f(r);
    if (v != null && v > bestV) {
      bestV = v;
      best = r;
    }
  }
  return best && bestV > 0 ? best : null;
}

/**
 * Default sweep: contracts 1..cap; with risk scaling, the RISK_MULTIPLIERS up to the first one at which even
 * the smallest as-traded trade hits the cap (beyond it every trade is capped and results stop changing).
 */
export function defaultSizes(source, evalCap) {
  if (source?.scaling !== 'risk') return Array.from({ length: evalCap }, (_, i) => i + 1);
  const limit = Math.ceil(evalCap / (source.minQty || 1));
  const out = RISK_MULTIPLIERS.filter((k) => k <= limit);
  return out.length ? out : [1];
}

/** Sizes 1..cap (or opts.sizes): runs every size and identifies the best ones. */
export function sweep(rules, source, opts = {}) {
  const o = simOptions(rules, opts);
  const sizes = opts.sizes ?? defaultSizes(source, o.evalCap);
  const results = sizes.map((contracts) => runSize(rules, source, { ...opts, contracts }));
  const bestPass = argmax(results, (r) => r.eval?.pPass);
  const bestPayout =
    o.mode === 'both'
      ? argmax(results, (r) => r.combined.expectedPaidPerAttempt)
      : o.mode === 'pa'
        ? argmax(results, (r) => r.pa.meanPaid)
        : null;
  const bestPassAndPayout = o.mode === 'both' ? argmax(results, (r) => r.combined.pPassAndPayout) : null;
  return {
    sizes,
    results,
    best: {
      pass: bestPass ? { contracts: bestPass.contracts, pPass: bestPass.eval.pPass } : null,
      payoutPerFee: bestPayout
        ? {
            contracts: bestPayout.contracts,
            expectedPaidPerAttempt: bestPayout.combined?.expectedPaidPerAttempt ?? null,
            paidPerFee: bestPayout.combined?.paidPerFee ?? null,
            meanPaidPerPa: bestPayout.pa.meanPaid,
          }
        : null,
      passAndPayout: bestPassAndPayout
        ? { contracts: bestPassAndPayout.contracts, pPassAndPayout: bestPassAndPayout.combined.pPassAndPayout }
        : null,
    },
  };
}

// ---------------------------------------------------------------------------------------------- history

/**
 * Deterministic sequential replay of the actual CSV trades (chronological), attempt after attempt as the
 * Pine strategy runs them. An attempt that PASSED or BREACHED on session D is followed by a fresh attempt
 * at the next session after D (later trades on D belong to no attempt and are counted as skipped). An
 * attempt EXPIRES at the first session on or after firstDay + accessDays calendar days, and the next one
 * starts at that session, so idle stretches expire attempts with no trades too. The first attempt starts
 * at the first trade's session; the last unfinished attempt is reported as OPEN. Sessions are Monday..
 * Friday plus any day that holds trades; day keys that are not 'YYYY-MM-DD' fall back to starting each
 * attempt at the next trade.
 */
export function replayEval(rules, trades, opts = {}) {
  const o = simOptions(rules, opts);
  assertSize(o.contracts);
  const risk = (opts.scaling ?? 'contracts') === 'risk';
  const q = risk ? o.contracts : Math.min(o.contracts, o.evalCap);
  const cost = opts.extraCost ?? 0;
  const ordered = trades.slice().sort(byTime);
  const cal = ordered.every((t) => ISO_DAY.test(String(t.dayKey)));
  const tradeDays = new Set(ordered.map((t) => t.dayKey));
  const sessionOnOrAfter = (k) => {
    while (!tradeDays.has(k) && !isWeekday(k)) k = addDays(k, 1);
    return k;
  };
  const attempts = [];
  let L = null;
  let cur = null;
  let nextStart = null;
  let skipped = 0;
  const begin = (day) => {
    L = makeEvalLedger(rules, { feed: o.feed, order: o.order, trailing: o.trailing, firstDay: day });
    cur = { startDay: day, endDay: day, trades: 0 };
  };
  const finish = (status, endDay = cur.endDay) => {
    attempts.push({ ...cur, endDay, status, realized: L.realized, reason: L.reason });
    L = null;
    cur = null;
  };
  for (const t of ordered) {
    const k = t.dayKey;
    if (!L) {
      if (nextStart != null && k < nextStart) {
        skipped++; // same session as the previous attempt's pass or breach
        continue;
      }
      begin(nextStart ?? k);
    }
    if (cal) {
      while (calendarDaysBetween(L.firstDay, k) >= L.accessDays) {
        const expiredOn = sessionOnOrAfter(addDays(L.firstDay, L.accessDays));
        checkExpiry(L, expiredOn);
        finish(EXPIRED, expiredOn);
        begin(expiredOn);
      }
    } else {
      checkExpiry(L, k);
      if (L.status === EXPIRED) {
        finish(EXPIRED);
        begin(k);
      }
    }
    const c = risk ? Math.min(q * (t.contracts >= 1 ? t.contracts : 1), o.evalCap) : q;
    stepTradeRaw(L, c * t.mfePer, c * t.maePer, c * t.pnlPer - c * cost, c * cost);
    cur.trades++;
    cur.endDay = k;
    if (L.status !== ACTIVE) {
      finish(L.status);
      nextStart = cal ? sessionOnOrAfter(addDays(k, 1)) : null;
    }
  }
  if (L) finish('OPEN');
  const count = (s) => attempts.filter((a) => a.status === s).length;
  const done = attempts.length - count('OPEN');
  return {
    contracts: q,
    scaling: risk ? 'risk' : 'contracts',
    attempts,
    total: attempts.length,
    passed: count(PASSED),
    breached: count(BREACHED),
    expired: count(EXPIRED),
    open: count('OPEN'),
    skippedTrades: skipped,
    passRate: done > 0 ? count(PASSED) / done : null,
  };
}
