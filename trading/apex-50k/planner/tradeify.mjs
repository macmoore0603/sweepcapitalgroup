// tradeify.mjs - Tradeify 50K Sim Funded account: ledger, Monte Carlo and historical replay for the four
// funded plans in trading/tradeify-50k/rules.json (Growth, Select Flex, Select Daily, Lightning).
//
// Every rule number comes from the rules file at runtime (loadTradeifyRules); nothing is hard-coded here.
//
// TRADEIFY FUNDED LEDGER SPEC:
//   balance starts at startBalance; floor = startBalance - drawdown.amount; status ACTIVE until BREACHED.
//   Intraday: net liquidation = balance + open P&L. BREACHED the moment net liquidation <= floor. Per trade
//     the favorable extreme is observed first, then the adverse extreme ('conservative'; 'adverse-first'
//     swaps them), then the close. The floor never moves intraday and the favorable extreme is >= 0, so
//     only the adverse extreme can breach and the two orders give identical results (the CLI rejects
//     --order with --firm tradeify).
//   End of day (session ends 17:00 ET, the next starts 18:00 ET), in this order:
//     1. floor: if not locked, floor = max(floor, EOD balance - drawdown); EOD balance >=
//        drawdown.lockTriggerEodBalance locks the floor at drawdown.lockedFloor for good.
//     2. DLL raise (plans with dllRaise): an EOD balance >= dllRaise.atBalance sets the DLL to dllRaise.to
//        from the next session on, permanently (legacy Growth: dllRemovedAt removes the DLL instead).
//     3. Select scaling: the contract cap comes from the highest EOD profit reached so far (kept once
//        reached), effective the next session. Other plans: maxContractsMini (legacy: legacy value).
//     4. payout cycle: the day's P&L is added to the profit since the last payout; the largest profitable
//        day and the qualifying / winning day count since the last payout are updated.
//     5. payout check for the plan (payoutCheck); when eligible the largest allowed amount is requested
//        (or the minimum with payout policy 'min'). A request locks the floor (lockOnPayoutRequest), the
//        balance drops by the amount, the trader receives amount x split, and the cycle resets.
//   Daily loss limit (soft): when session P&L (realized today + open P&L at the adverse extreme) <= -DLL
//     the position is flattened and the rest of the session is skipped; the account stays open. Where it
//     is flattened follows dllFill, as in the Apex PA ('extreme': at the adverse extreme, after the
//     breach check; 'limit': exactly at the limit).
//   Money is kept in whole cents; payout amounts are rounded down to the cent.
//
// START STATE (opts.startState; resolveStartState validates it): instead of a fresh account, the ledger starts
//   at the last close of an account already held, as read off the Tradeify dashboard: balance B, floor F,
//   highest end-of-day balance H, cycle start S (startBalance before the first payout, else the balance right
//   after the last payout), qualifying days N and largest profitable day M since the last payout, and payouts
//   taken K. Then realized = B - startBalance, floor = F, locked when H >= lockTriggerEodBalance or (K > 0 and
//   lockOnPayoutRequest), maxEodProfit = H - startBalance, DLL raised when H >= dllRaise.atBalance (as in the
//   ledger, where a close at that balance raises it for good; Tradeify does not say whether it reverts),
//   qualDays = N, cycleProfit = B - S, cycleMaxDay = M, payouts = K (the next cap is caps[K]).
//   H defaults to the largest of B, startBalance and, before any payout, F + drawdown (an unlocked floor
//   trails H - drawdown), or, after one, S and the lowest close at which the plan pays at all.
//   A state the account cannot be in is rejected: an unlocked F outside [startBalance - drawdown, lockedFloor),
//   N = 0 with a qualifying M, M = 0 with B > S, a missing M where consistency needs it, and (Growth) an S
//   below minBalance - cap of payout K.
//   A start state that is already eligible requests its payout at once, before the first simulated session
//   (the start is a session close). Payout counts and amounts reported by the simulation and the replay are
//   the ones made after the start; the K payouts taken before it are not counted again. That payout is the
//   same in every run (simulateFunded reports it as payoutNow); P(payout), P(breach before the first payout)
//   and the days to the first payout count only the payouts after it.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { ACTIVE, BREACHED, cents, normalizeOrder, normalizeDllFill, normalizeUnit } from './ledger.mjs';
import {
  mulberry32,
  pathSeed,
  groupTradesByDay,
  sessionCalendar,
  defaultSizes,
  quantileSorted,
  mean,
  sortedCopy,
} from './sim.mjs';
import { NY, wallClock, dayKeyOf } from './time.mjs';

export { ACTIVE, BREACHED };

export const TRADEIFY_RULES_PATH = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'tradeify-50k', 'rules.json');
export const PLAN_KEYS = Object.freeze(['growth', 'select-flex', 'select-daily', 'lightning']);
export const PAYOUT_POLICIES = Object.freeze(['max', 'min']);
const FUNDED_STREAM = 0x54464644; // 'TFFD'
const EPS = 1e-7;
/** Legacy overrides the planner applies, by plan (resolvePlan sets them, the plan's payout reads them). */
const LEGACY_KEYS = Object.freeze({
  growth: new Set(['maxContractsMini', 'minBalance', 'caps', 'capAfterTiers', 'dllRemovedAt', 'consistency']),
  lightning: new Set(['maxContractsMini', 'caps', 'dllRemovedAt', 'consistency']),
  'select-flex': new Set(['maxContractsMini', 'dllRemovedAt']),
  'select-daily': new Set(['maxContractsMini', 'dllRemovedAt']),
});
/** Plans whose payout applies a consistency rule. */
const CONSISTENCY_PLANS = new Set(['growth', 'lightning']);
/** Plans whose payout counts qualifying / winning days (qualifies()). */
const DAY_COUNT_PLANS = new Set(['growth', 'select-flex']);
/**
 * fundedRules entries the planner knows (validateTradeifyRules rejects any other); each must be a string.
 * The CLI prints microscalping, kyc and payoutApproval in the start state's "also needed" list and
 * minActivity under "not modelled"; algo, hedging and news are kept in the JSON output only.
 */
const FUNDED_RULE_TEXTS = Object.freeze(['microscalping', 'minActivity', 'algo', 'hedging', 'news', 'kyc', 'payoutApproval']);
const START_KIND = 'TRADEIFY_START';
/** Start-state field -> CLI flag, for error messages. */
export const START_FLAGS = Object.freeze({
  balance: '--balance',
  floor: '--floor',
  highEod: '--high-eod',
  cycleStart: '--cycle-start',
  qualDays: '--qual-days',
  cycleMaxDay: '--cycle-max-day',
  payoutsTaken: '--payouts-taken',
});
/** fundedRules.microscalping, e.g. "more than 50% of trades and of profit ... held longer than 10 seconds". */
const MICROSCALPING_RE = /more than\s+(\d+(?:\.\d+)?)\s*%[^]*?longer than\s+(\d+(?:\.\d+)?)\s*s(?:ec(?:ond)?s?)?\b/i;

// ---------------------------------------------------------------------------------------------- rules

/** "16:45" -> minutes after midnight (null when malformed). */
export function parseHm(s) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(s ?? ''));
  if (!m || +m[1] > 23 || +m[2] > 59) return null;
  return +m[1] * 60 + +m[2];
}

export function loadTradeifyRules(path = TRADEIFY_RULES_PATH) {
  return validateTradeifyRules(JSON.parse(readFileSync(path, 'utf8')));
}

export function validateTradeifyRules(r) {
  const fail = (msg) => {
    throw new Error(`tradeify rules: ${msg}`);
  };
  const num = (v) => typeof v === 'number' && Number.isFinite(v);
  const numArr = (v) => Array.isArray(v) && v.length > 0 && v.every(num);
  if (!r || typeof r !== 'object') fail('not an object');
  if (!num(r.startBalance)) fail('startBalance must be a number');
  if (!num(r.microsPerMini) || r.microsPerMini <= 0) fail('microsPerMini must be a positive number');
  if (!num(r.split) || r.split <= 0 || r.split > 1) fail('split must be a number in (0, 1]');
  const d = r.drawdown;
  if (!d) fail('drawdown missing');
  for (const k of ['amount', 'lockTriggerEodBalance', 'lockedFloor']) if (!num(d[k])) fail(`drawdown.${k} must be a number`);
  if (typeof d.lockOnPayoutRequest !== 'boolean') fail('drawdown.lockOnPayoutRequest must be true or false');
  const s = r.session;
  if (!s) fail('session missing');
  for (const k of ['startEt', 'endEt', 'flatByEt', 'earlyCloseFlatByEt']) if (parseHm(s[k]) == null) fail(`session.${k} must be "HH:MM"`);
  if (r.fundedRules != null) {
    if (typeof r.fundedRules !== 'object') fail('fundedRules must be an object');
    for (const k of Object.keys(r.fundedRules)) {
      if (!FUNDED_RULE_TEXTS.includes(k)) fail(`fundedRules.${k} is not a rule the planner knows (expected ${FUNDED_RULE_TEXTS.join(', ')})`);
      if (typeof r.fundedRules[k] !== 'string') fail(`fundedRules.${k} must be a string`);
    }
  }
  const ms = r.fundedRules?.microscalping;
  if (ms != null && !MICROSCALPING_RE.test(String(ms))) {
    fail('fundedRules.microscalping must read "more than P% of trades and of profit ... held longer than S seconds" (the planner reads P and S from it)');
  }
  if (!r.plans || typeof r.plans !== 'object') fail('plans missing');
  for (const key of PLAN_KEYS) {
    const p = r.plans[key];
    const at = (k) => `plans.${key}.${k}`;
    if (!p) fail(`plans.${key} missing`);
    if (!num(p.maxContractsMini) || p.maxContractsMini < 1) fail(`${at('maxContractsMini')} must be a number >= 1`);
    if (p.scaling != null) {
      if (!Array.isArray(p.scaling) || p.scaling.length === 0) fail(`${at('scaling')} must be null or a non-empty array`);
      p.scaling.forEach((t, i) => {
        if (!num(t.minProfit) || !num(t.maxContractsMini)) fail(`${at('scaling')}[${i}] needs minProfit and maxContractsMini`);
      });
    }
    if (p.dailyLossLimit != null && !(num(p.dailyLossLimit) && p.dailyLossLimit > 0)) fail(`${at('dailyLossLimit')} must be null or > 0`);
    if (p.dllRaise != null && !(num(p.dllRaise.atBalance) && num(p.dllRaise.to))) fail(`${at('dllRaise')} needs atBalance and to`);
    if (p.dllRaise?.effective != null && p.dllRaise.effective !== 'next session') {
      fail(`${at('dllRaise.effective')} must be "next session", the only timing the planner models`);
    }
    if (p.consistency != null && !numArr(p.consistency)) fail(`${at('consistency')} must be null or a non-empty array of numbers`);
    if (p.consistency != null && !CONSISTENCY_PLANS.has(key)) fail(`${at('consistency')} is set but the ${key} payout has no consistency rule in the planner`);
    const P = p.payout;
    if (!P) fail(`${at('payout')} missing`);
    if (P.type !== key) fail(`${at('payout.type')} must be "${key}", got ${JSON.stringify(P.type)}`);
    const need = (keys) => keys.forEach((k) => num(P[k]) || fail(`${at(`payout.${k}`)} must be a number`));
    for (const k of ['capsRepeatLast', 'dayCountResetsAfterPayout']) {
      if (P[k] != null && typeof P[k] !== 'boolean') fail(`${at(`payout.${k}`)} must be true or false`);
    }
    if (P.capsRepeatLast != null && !Array.isArray(P.caps)) fail(`${at('payout.capsRepeatLast')} is set but the ${key} payout has no caps list`);
    if (P.dayCountResetsAfterPayout === false && key !== 'growth') {
      fail(`${at('payout.dayCountResetsAfterPayout')} false is modelled for growth only`);
    }
    if (P.capAfterTiers != null && key !== 'growth') fail(`${at('payout.capAfterTiers')} is modelled for growth only`);
    if (key === 'growth') {
      need(['minQualifyingDays', 'qualifyingDayProfitAbove', 'minBalance', 'minPayout']);
      if (!numArr(P.caps)) fail(`${at('payout.caps')} must be a non-empty array of numbers`);
      if (P.capAfterTiers != null && !num(P.capAfterTiers)) fail(`${at('payout.capAfterTiers')} must be a number`);
      if (!numArr(p.consistency)) fail(`${at('consistency')} is required for the growth payout`);
    } else if (key === 'select-flex') {
      need(['winningDays', 'winningDayProfitAtLeast', 'shareOfTotalProfit', 'cap', 'capIfBoughtBefore20260901', 'minPayout', 'positiveCycleProfitFromPayout']);
    } else if (key === 'select-daily') {
      need(['bufferBalance', 'multipleOfCycleProfit', 'cap', 'capIfBoughtBefore20260901', 'minPayout', 'positiveCycleProfitFromPayout']);
    } else if (key === 'lightning') {
      need(['minPayout']);
      if (!numArr(P.profitGoals)) fail(`${at('payout.profitGoals')} must be a non-empty array of numbers`);
      if (!numArr(P.caps)) fail(`${at('payout.caps')} must be a non-empty array of numbers`);
      if (!numArr(p.consistency)) fail(`${at('consistency')} is required for the lightning payout`);
    }
    if (p.legacy != null) {
      for (const k of Object.keys(p.legacy)) {
        // A legacy override the planner does not apply to this plan must fail loudly instead of being ignored.
        if (!LEGACY_KEYS[key].has(k)) fail(`${at(`legacy.${k}`)} is set but is not modelled by the planner for ${key}`);
      }
      const lg = p.legacy;
      if (lg.maxContractsMini != null && !num(lg.maxContractsMini)) fail(`${at('legacy.maxContractsMini')} must be a number`);
      if (lg.minBalance != null && !num(lg.minBalance)) fail(`${at('legacy.minBalance')} must be a number`);
      if (lg.caps != null && !numArr(lg.caps)) fail(`${at('legacy.caps')} must be a non-empty array of numbers`);
      if (lg.capAfterTiers != null && !num(lg.capAfterTiers)) fail(`${at('legacy.capAfterTiers')} must be a number`);
      if (lg.dllRemovedAt != null && !num(lg.dllRemovedAt)) fail(`${at('legacy.dllRemovedAt')} must be a number`);
      if (lg.consistency != null && !numArr(lg.consistency)) fail(`${at('legacy.consistency')} must be a non-empty array of numbers`);
    }
  }
  return r;
}

// ---------------------------------------------------------------------------------------------- options

export function normalizePlan(plan = 'growth') {
  const p = String(plan ?? 'growth')
    .toLowerCase()
    .replace(/[\s_]+/g, '-');
  if (PLAN_KEYS.includes(p)) return p;
  throw new Error(`unknown plan "${plan}" (expected ${PLAN_KEYS.join(' | ')})`);
}

export function normalizePayoutPolicy(policy = 'max') {
  const p = String(policy ?? 'max').toLowerCase();
  if (p === 'max' || p === 'maximum' || p === 'largest') return 'max';
  if (p === 'min' || p === 'minimum') return 'min';
  throw new Error(`unknown payout policy "${policy}" (expected max | min)`);
}

/**
 * Effective rules of one plan: the plan from the rules file with its legacy overrides applied (--legacy:
 * bought before plan.legacyBefore) and the Select caps for accounts bought before 2026-09-01.
 */
export function resolvePlan(rules, planKey, { legacy = false, boughtBefore20260901 = false } = {}) {
  const key = normalizePlan(planKey);
  const base = rules.plans[key];
  if (legacy && !base.legacy) throw new Error(`plan ${key} has no legacy variant in the rules file (legacy applies to growth and lightning)`);
  if (boughtBefore20260901 && base.payout.capIfBoughtBefore20260901 == null) {
    throw new Error(`plan ${key} has no cap for accounts bought before 2026-09-01 (applies to select-flex and select-daily)`);
  }
  const lg = legacy ? base.legacy : {};
  const payout = { ...base.payout };
  if (lg.minBalance != null) payout.minBalance = lg.minBalance;
  if (lg.caps != null) payout.caps = lg.caps.slice();
  if (lg.capAfterTiers != null) payout.capAfterTiers = lg.capAfterTiers;
  if (boughtBefore20260901) payout.cap = payout.capIfBoughtBefore20260901;
  let dllRaise = base.dllRaise ? { atBalance: base.dllRaise.atBalance, to: base.dllRaise.to } : null;
  if (lg.dllRemovedAt != null) dllRaise = { atBalance: lg.dllRemovedAt, to: null }; // DLL removed
  return {
    key,
    name: `${base.name}${legacy ? ' (legacy)' : ''}`,
    legacy: Boolean(legacy),
    legacyBefore: base.legacyBefore ?? null,
    boughtBefore20260901: Boolean(boughtBefore20260901),
    maxContractsMini: lg.maxContractsMini ?? base.maxContractsMini,
    scaling: base.scaling ? base.scaling.slice().sort((a, b) => a.minProfit - b.minProfit) : null,
    dailyLossLimit: base.dailyLossLimit ?? null,
    dllRaise,
    consistency: lg.consistency ?? base.consistency ?? null,
    payout,
  };
}

/** Contract cap in minis for a plan at a highest end-of-day profit (Select scaling; else the plan maximum). */
export function capMiniFor(plan, maxEodProfit) {
  if (!plan.scaling) return plan.maxContractsMini;
  let cap = plan.scaling[0].maxContractsMini;
  for (const t of plan.scaling) if (t.minProfit <= maxEodProfit) cap = t.maxContractsMini;
  return Math.min(cap, plan.maxContractsMini);
}

/** Largest size of the plan in the unit (minis, or micros = minis x microsPerMini). */
export function planCap(rules, plan, unit = 'mini') {
  return plan.maxContractsMini * (normalizeUnit(unit) === 'micro' ? rules.microsPerMini : 1);
}

/** Session roll hour (exits at or after it count toward the next session) from session.startEt. */
export function sessionRollHour(rules) {
  return Math.floor(parseHm(rules.session.startEt) / 60);
}

// ---------------------------------------------------------------------------------------------- start state

/** "$52,340.00" (messages only). */
function money(x) {
  const s = Math.abs(x).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${x < 0 && Math.abs(x) >= 0.005 ? '-' : ''}$${s}`;
}
const pctText = (x, d = 0) => `${(100 * x).toFixed(d)}%`;
/** Smallest whole-cent amount >= x. */
const ceilCents = (x) => Math.ceil(x * 100 - 1e-6) / 100;

/**
 * Lowest end-of-day balance at which the plan can request any payout (payoutCheck): a highest end-of-day
 * balance after a payout is at least this.
 */
function payoutMinBalance(rules, plan) {
  const P = plan.payout;
  const S0 = rules.startBalance;
  if (P.type === 'growth') return P.minBalance;
  if (P.type === 'lightning') return cents(S0 + P.profitGoals[0]);
  if (P.type === 'select-daily') return cents(P.bufferBalance + P.minPayout);
  if (P.type === 'select-flex') return ceilCents(S0 + P.minPayout / P.shareOfTotalProfit);
  return S0;
}

/**
 * Validate an account's current state (see START STATE in the header) for a plan and fill in the defaults.
 * input: { balance, floor, highEod?, cycleStart?, qualDays?, cycleMaxDay?, payoutsTaken? } in $ and counts.
 * Returns the resolved state ({ kind, balance, floor, highEod, cycleStart, qualDays, cycleMaxDay,
 * payoutsTaken, cycleProfit, roomToFloor, locked, lockedBy, expectedFloor, maxEodProfit, capMini,
 * dllRaised, dll, warnings, notes }); throws on a state the account cannot be in. An unlocked floor must be
 * in [startBalance - drawdown, lockedFloor); one that differs from H - drawdown by more than $1 is used as
 * typed, with a warning.
 */
export function resolveStartState(rules, planOrKey, input = {}) {
  const plan = typeof planOrKey === 'string' ? resolvePlan(rules, planOrKey) : planOrKey;
  // Already resolved for this plan: return it as is (resolving again would take its defaults for typed values).
  if (input.kind === START_KIND && input.planKey === plan.key && input.legacy === plan.legacy) return input;
  const fail = (msg) => {
    throw new Error(`start state: ${msg}`);
  };
  const S0 = rules.startBalance;
  const d = rules.drawdown;
  const P = plan.payout;
  const F = START_FLAGS;
  const amount = (k, def) => {
    const v = input[k];
    if (v == null) {
      if (def === undefined) fail(`${F[k]} is required`);
      return def;
    }
    if (typeof v !== 'number' || !Number.isFinite(v)) fail(`${F[k]} must be a number, got ${JSON.stringify(v)}`);
    return cents(v);
  };
  const count = (k) => {
    const v = input[k] ?? 0;
    if (!Number.isInteger(v) || v < 0) fail(`${F[k]} must be a whole number >= 0, got ${JSON.stringify(v)}`);
    return v;
  };
  const warnings = [];
  const notes = [];
  const balance = amount('balance');
  const floor = amount('floor');
  if (balance <= floor) {
    fail(`${F.balance} ${money(balance)} is not above ${F.floor} ${money(floor)}: the account has already breached (net liquidation at or below the floor fails it)`);
  }
  const payoutsTaken = count('payoutsTaken');
  const qualDays = count('qualDays');
  if (qualDays > 0 && !DAY_COUNT_PLANS.has(plan.key)) fail(`${F.qualDays} does not apply to ${plan.name}: its payout does not count qualifying days`);
  const cycleStart = amount('cycleStart', S0);
  if (payoutsTaken === 0 && cycleStart !== S0) {
    fail(`${F.cycleStart} must be the ${money(S0)} start balance while no payout has been taken (${F.payoutsTaken} 0), got ${money(cycleStart)}`);
  }
  // H defaults to what the other numbers prove: before a payout an unlocked floor trails H - drawdown, so
  // H = F + drawdown; after one, H is at least S and the lowest close at which the plan pays at all.
  const minPayBal = payoutMinBalance(rules, plan);
  const hTyped = input.highEod != null;
  const hFrom = payoutsTaken > 0 ? Math.max(cycleStart, minPayBal) : floor + d.amount;
  const highEod = amount('highEod', cents(Math.max(balance, S0, hFrom)));
  const hSource =
    payoutsTaken > 0
      ? `the largest of ${F.balance}, ${F.cycleStart} and ${money(minPayBal)}, the lowest close at which a payout is possible`
      : `the largest of ${F.balance}, the ${money(S0)} start balance and ${F.floor} + ${money(d.amount)}`;
  const hLabel = `${F.highEod} ${money(highEod)}${hTyped ? '' : ` (not given: ${hSource})`}`;
  if (highEod < balance) fail(`${F.highEod} ${money(highEod)} is below ${F.balance} ${money(balance)}: the last close is itself an end-of-day balance`);
  if (highEod < S0) fail(`${F.highEod} ${money(highEod)} is below the ${money(S0)} start balance`);
  const byEod = highEod >= d.lockTriggerEodBalance;
  const byPayout = payoutsTaken > 0 && d.lockOnPayoutRequest;
  const locked = byEod || byPayout;
  const lowestFloor = cents(S0 - d.amount);
  const expectedFloor = locked ? d.lockedFloor : cents(Math.max(lowestFloor, highEod - d.amount));
  if (floor > d.lockedFloor + 0.005) {
    fail(`${F.floor} ${money(floor)} is above ${money(d.lockedFloor)}: the floor never goes higher (it locks there once a close reaches ${money(d.lockTriggerEodBalance)}${d.lockOnPayoutRequest ? ' or a payout is requested' : ''})`);
  }
  if (locked && Math.abs(floor - d.lockedFloor) >= 0.005) {
    // Give the reason that is certain: a payout taken, unless the lock comes from a typed --high-eod.
    const why = byEod && (hTyped || !byPayout) ? `${hLabel} reached ${money(d.lockTriggerEodBalance)}` : `${F.payoutsTaken} ${payoutsTaken}: a payout was requested`;
    fail(`${F.floor} must be the locked floor ${money(d.lockedFloor)} (${why}), got ${money(floor)}`);
  }
  if (!locked) {
    if (floor < lowestFloor - 0.005) {
      // An unquoted "$49,000" reaches the program as "9,000": the shell expands $4.
      const shell = floor < S0 / 5 ? `; in a shell an unquoted $ amount loses its first digit ($49,000 arrives as 9,000): type 49000 or quote it` : '';
      fail(`${F.floor} ${money(floor)} is below ${money(lowestFloor)}, the lowest floor (the ${money(S0)} start balance - the ${money(d.amount)} drawdown; it never moves down)${shell}`);
    }
    if (floor >= d.lockedFloor - 0.005) {
      fail(
        `${F.floor} ${money(floor)} with ${hLabel}: the floor locks at ${money(d.lockedFloor)} only once a close reaches ${money(d.lockTriggerEodBalance)}` +
          `${d.lockOnPayoutRequest ? ' or a payout is requested' : ''}, so until then it is below ${money(d.lockedFloor)} (here ${money(expectedFloor)})`,
      );
    }
    if (Math.abs(floor - expectedFloor) > 1 + 1e-9) {
      warnings.push(
        `${F.floor} ${money(floor)} differs by ${money(Math.abs(floor - expectedFloor))} from ${hLabel} - ${money(d.amount)} = ${money(expectedFloor)}; ` +
          `the run uses the floor as typed (an unlocked floor is the highest end-of-day balance - ${money(d.amount)}, at least ${money(lowestFloor)}: check ${F.floor} and ${F.highEod})`,
      );
    }
  }
  if (payoutsTaken > 0 && cycleStart <= floor) {
    fail(
      `${F.cycleStart} ${money(cycleStart)} is not above the floor ${money(floor)}: after a payout the cycle starts at the balance right after the last payout, which stays above the floor`,
    );
  }
  if (payoutsTaken > 0 && P.type === 'growth') {
    // Payout K needed minBalance until approval and paid at most its cap, so S >= minBalance - cap.
    const lastCap = growthCap(P, payoutsTaken - 1);
    const minAfter = cents(P.minBalance - lastCap);
    if (cycleStart < minAfter) {
      fail(
        `${F.cycleStart} ${money(cycleStart)} is below ${money(minAfter)}, the lowest balance right after payout ${payoutsTaken}: ` +
          `a payout needs a ${money(P.minBalance)} balance until it is approved, and payout ${payoutsTaken} is at most ${money(lastCap)}`,
      );
    }
  }
  if (cycleStart > highEod) fail(`${F.cycleStart} ${money(cycleStart)} is above ${F.highEod} ${money(highEod)}: the balance after a payout is below the end-of-day balance it was paid from`);
  const cycleProfit = cents(balance - cycleStart);
  const usesConsistency = plan.consistency != null && CONSISTENCY_PLANS.has(plan.key);
  // Before the first payout a close above the start balance means this cycle has had a profitable day.
  const profitBefore = payoutsTaken === 0 && highEod > S0;
  if (input.cycleMaxDay == null && usesConsistency && (cycleProfit > 0 || qualDays > 0 || profitBefore)) {
    const why =
      cycleProfit > 0
        ? `${F.balance} is above ${F.cycleStart} (profit since the last payout ${money(cycleProfit)})`
        : qualDays > 0
          ? `${F.qualDays} is ${qualDays}`
          : `${hLabel} is above the ${money(S0)} start balance (this cycle has had a profitable day)`;
    fail(`${F.cycleMaxDay} is required when ${why}: the ${pctText(at(plan.consistency, payoutsTaken))} consistency rule depends on the largest day, and guessing it would change the result`);
  }
  const cycleMaxDay = amount('cycleMaxDay', 0);
  if (cycleMaxDay < 0) fail(`${F.cycleMaxDay} must be >= 0 (the largest profitable day; losing days are not counted), got ${money(cycleMaxDay)}`);
  if (input.cycleMaxDay != null && cycleMaxDay === 0 && cycleProfit > 0) {
    fail(`${F.cycleMaxDay} is ${money(0)} but the profit since the last payout is ${money(cycleProfit)}: a positive profit needs at least one profitable day`);
  }
  if (DAY_COUNT_PLANS.has(plan.key) && input.cycleMaxDay != null) {
    const growth = P.type === 'growth';
    const min = growth ? P.qualifyingDayProfitAbove : P.winningDayProfitAtLeast;
    const kind = growth ? 'qualifying' : 'winning';
    const counts = growth ? cycleMaxDay > min : cycleMaxDay >= min;
    if (qualDays > 0 && !counts) {
      fail(`${F.qualDays} ${qualDays} needs ${F.cycleMaxDay} ${growth ? 'above' : 'of at least'} ${money(min)}: each ${kind} day made that much, so the largest day did too, got ${money(cycleMaxDay)}`);
    }
    if (qualDays === 0 && counts) {
      fail(`${F.qualDays} is 0 but ${F.cycleMaxDay} ${money(cycleMaxDay)} is ${growth ? 'above' : 'at least'} ${money(min)}: that day was itself a ${kind} day, so give ${F.qualDays} (at least 1)`);
    }
  }
  const raise = plan.dllRaise;
  const dllRaised = Boolean(raise) && highEod >= raise.atBalance;
  const dll = dllRaised ? raise.to : plan.dailyLossLimit;
  if (dllRaised && balance < raise.atBalance) {
    const what = raise.to == null ? 'DLL removed' : `DLL ${money(raise.to)}`;
    notes.push(
      `${what}: a close reached ${money(raise.atBalance)} by ${hLabel}, and the planner keeps that once reached, as it does for a simulated account ` +
        '(Tradeify does not say whether it reverts once the balance drops)',
    );
  }
  if (!hTyped && payoutsTaken > 0 && plan.scaling) {
    notes.push(`${F.highEod} not given: assumed ${money(highEod)} (${hSource}); the Select contract limit comes from it, so give the real highest end-of-day balance`);
  }
  const maxEodProfit = cents(highEod - S0);
  return {
    kind: START_KIND,
    planKey: plan.key,
    legacy: plan.legacy,
    balance,
    floor,
    highEod,
    cycleStart,
    qualDays,
    cycleMaxDay,
    payoutsTaken,
    cycleProfit,
    roomToFloor: cents(balance - floor),
    locked,
    lockedBy: byEod ? 'eod' : byPayout ? 'payout' : null,
    expectedFloor,
    maxEodProfit,
    capMini: capMiniFor(plan, maxEodProfit),
    dllRaised,
    dll,
    warnings,
    notes,
  };
}

/** Put a ledger at a start state (resolved for its plan unless it already is). */
function applyStartState(L, rules, startState) {
  const st = resolveStartState(rules, L.plan, startState);
  L.start = st;
  L.realized = cents(st.balance - L.startBal);
  L.dayStartRealized = L.realized;
  L.floor = st.floor;
  L.locked = st.locked;
  L.lockedBy = st.lockedBy;
  L.maxEodProfit = st.maxEodProfit;
  L.dllRaised = st.dllRaised;
  L.dll = st.dll;
  L.qualDays = st.qualDays;
  L.cycleProfit = st.cycleProfit;
  L.cycleMaxDay = st.cycleMaxDay;
  L.payouts = st.payoutsTaken;
  L.payoutsBefore = st.payoutsTaken;
}

// ---------------------------------------------------------------------------------------------- ledger

/**
 * opts: { legacy, boughtBefore20260901, order: 'conservative'|'adverse-first', dllFill: 'extreme'|'limit',
 * payout: 'max'|'min', firstDay, startState } (startState: see START STATE in the header; null = fresh)
 */
export function makeFundedLedger(rules, planKey, opts = {}) {
  const plan = resolvePlan(rules, planKey, opts);
  const d = rules.drawdown;
  const L = {
    kind: 'TRADEIFY_FUNDED',
    plan,
    planKey: plan.key,
    startBal: rules.startBalance,
    microsPerMini: rules.microsPerMini,
    split: rules.split,
    drawdown: d.amount,
    lockTrigger: d.lockTriggerEodBalance,
    lockedFloor: d.lockedFloor,
    lockOnPayoutRequest: d.lockOnPayoutRequest,
    floor: cents(rules.startBalance - d.amount),
    locked: false,
    lockedBy: null,
    order: normalizeOrder(opts.order ?? 'conservative'),
    dllFill: normalizeDllFill(opts.dllFill ?? 'extreme'),
    payoutPolicy: normalizePayoutPolicy(opts.payout ?? 'max'),
    status: ACTIVE,
    reason: null,
    realized: 0,
    trades: 0,
    dllSkippedTrades: 0,
    sessions: 0, // sessions closed by endDay
    dayKey: opts.firstDay ?? null,
    dayStartRealized: 0,
    dayHalted: false,
    dllHits: 0,
    dllDays: 0,
    lastDayPnl: 0,
    dll: plan.dailyLossLimit,
    dllRaised: false,
    maxEodProfit: 0,
    capMini: 0,
    qualDays: 0, // Growth: days > qualifyingDayProfitAbove; Select Flex: days >= winningDayProfitAtLeast
    cycleProfit: 0, // net profit since the last payout (since the start before the first)
    cycleMaxDay: 0, // largest profitable day since the last payout
    payouts: 0, // payout number reached (including payoutsBefore)
    payoutsBefore: 0, // payouts taken before a start state; not counted again in results
    start: null,
    requested: 0,
    received: 0,
    payoutHistory: [],
  };
  if (opts.startState != null) applyStartState(L, rules, opts.startState);
  L.capMini = capMiniFor(plan, L.maxEodProfit);
  return L;
}

/** Payouts requested on this ledger (after its start state, if any). */
export function payoutsMade(L) {
  return L.payouts - L.payoutsBefore;
}

export function balance(L) {
  return cents(L.startBal + L.realized);
}

/**
 * Value the account ends with: for a breached account the net liquidation at the breach (an intraday
 * breach leaves the open loss out of the balance), else the balance.
 */
export function finalBalance(L) {
  return L.status === BREACHED ? L.breachNetLiq : balance(L);
}

/** Session P&L: realized today + open P&L, in cents. */
export function sessionPnl(L, openPnl = 0) {
  return cents(L.realized - L.dayStartRealized + openPnl);
}

/** Max contracts this session: the plan cap (Select: from scaling) in minis, x microsPerMini for micros. */
export function contractCap(L, unit = 'mini') {
  return normalizeUnit(unit) === 'micro' ? L.capMini * L.microsPerMini : L.capMini;
}

/** Observe one net-liquidation print (balance + open P&L). Touching the floor breaches the account. */
export function observe(L, netLiq) {
  if (L.status !== ACTIVE) return L.status;
  const nl = cents(netLiq);
  if (nl <= L.floor) {
    L.status = BREACHED;
    L.breachNetLiq = nl;
    L.breachDay = L.dayKey;
    L.reason = `net liquidation ${nl} touched floor ${L.floor}`;
  }
  return L.status;
}

/**
 * Apply one complete trade (all values in $ for the whole position): favorable = best open P&L (>= 0),
 * adverse = worst open P&L (<= 0), close = realized P&L net of costs, cost = round-trip cost (used only
 * when a daily-loss flatten replaces the close). Order follows L.order; each extreme is observed (breach
 * check) as it is reached. See the DLL note in the header.
 */
export function stepTrade(L, favorable, adverse, close, cost = 0) {
  if (L.status !== ACTIVE) return L.status;
  if (L.dayHalted) {
    L.dllSkippedTrades++;
    return L.status;
  }
  L.trades++;
  const fav = cents(favorable);
  let adv = cents(adverse);
  let flatten = false;
  if (L.dll != null) {
    const lim = cents(-L.dll - sessionPnl(L)); // open P&L at which session P&L = -DLL
    if (adv <= lim) {
      flatten = true;
      if (L.dllFill === 'limit') adv = lim;
    }
  }
  const base = L.startBal + L.realized;
  if (L.order === 'adverse-first') {
    if (observe(L, base + adv) !== ACTIVE) return L.status;
    if (!flatten && observe(L, base + fav) !== ACTIVE) return L.status;
  } else {
    if (observe(L, base + fav) !== ACTIVE) return L.status;
    if (observe(L, base + adv) !== ACTIVE) return L.status;
  }
  if (flatten) {
    L.dllHits++;
    return closeTrade(L, adv - cost, true);
  }
  return closeTrade(L, close);
}

/** Close the open position with net P&L `pnl`; observes the flat balance, then the daily loss limit. */
export function closeTrade(L, pnl, dllFlatten = false) {
  if (L.status !== ACTIVE) return L.status;
  L.realized = cents(L.realized + pnl);
  if (observe(L, L.startBal + L.realized) !== ACTIVE) return L.status;
  if (dllFlatten || (L.dll != null && sessionPnl(L) <= -L.dll)) L.dayHalted = true;
  return L.status;
}

/** Start a session: reset session P&L and the daily-loss pause. */
export function startDay(L, dayKey = null) {
  if (L.status !== ACTIVE) return L.status;
  L.dayKey = dayKey ?? L.sessions + 1;
  L.dayStartRealized = L.realized;
  L.dayHalted = false;
  return L.status;
}

function lock(L, by) {
  if (L.locked) return;
  L.locked = true;
  L.lockedBy = by;
  L.floor = L.lockedFloor;
}

const at = (arr, i) => arr[Math.min(i, arr.length - 1)];
/** Growth cap of payout k + 1: caps[k], after the tiers capAfterTiers when set (legacy: $25,000), else the last tier. */
const growthCap = (P, k) => (k < P.caps.length ? P.caps[k] : (P.capAfterTiers ?? at(P.caps, k)));
/** Round a payout amount down to the cent (a request can never exceed the rule by a rounding cent). */
const floorCents = (x) => Math.floor(x * 100 + 1e-6) / 100;

/** The floor a payout request would leave: the locked floor when a request locks it, else the floor. */
export function requestFloor(L) {
  return L.lockOnPayoutRequest && !L.locked ? L.lockedFloor : L.floor;
}

/**
 * Payout eligibility right now, without changing anything (call after the session is booked, as endDay
 * does). Returns { eligible, amount, maxAmount, n, checks: {name: bool}, ... }.
 *   growth:       >= minQualifyingDays days with profit > qualifyingDayProfitAbove since the last payout;
 *                 largest profitable day <= consistency x profit since the last payout; balance >=
 *                 minBalance; amount = min(caps[n], balance - floor - 0.01) >= minPayout (after the tiers:
 *                 capAfterTiers when set, else the last tier).
 *   select-flex:  >= winningDays days with profit >= winningDayProfitAtLeast since the last payout; from
 *                 payout positiveCycleProfitFromPayout on, profit since the last payout > 0; amount =
 *                 min(shareOfTotalProfit x (balance - start), cap) >= minPayout, balance stays above floor.
 *   select-daily: from payout positiveCycleProfitFromPayout on, profit since the last payout > 0; amount =
 *                 min(multipleOfCycleProfit x that profit, cap, balance - bufferBalance) >= minPayout.
 *   lightning:    profit since the last payout >= profitGoals[n]; largest profitable day <= consistency[n]
 *                 x that profit; amount = min(caps[n], balance - floor - 0.01) >= minPayout.
 * The floor in "balance - floor" is the floor after the request (requestFloor). With payout policy 'min'
 * the request is minPayout whenever the largest allowed amount reaches it.
 */
export function payoutCheck(L) {
  const plan = L.plan;
  const P = plan.payout;
  const bal = balance(L);
  const k = L.payouts; // this request would be payout k + 1
  const reqFloor = requestFloor(L);
  const checks = {};
  const info = {};
  let maxAmount;
  if (P.type === 'growth') {
    const share = at(plan.consistency, k);
    // capAfterTiers (legacy Growth: up to $25,000 per payout after the 6th) replaces the last tier's cap.
    info.cap = growthCap(P, k);
    info.consistencyShare = share;
    checks.days = L.qualDays >= P.minQualifyingDays;
    checks.consistency = L.cycleProfit > 0 && L.cycleMaxDay <= share * L.cycleProfit + EPS;
    checks.balance = bal >= P.minBalance;
    checks.count = P.capsRepeatLast !== false || k < P.caps.length || P.capAfterTiers != null;
    maxAmount = floorCents(Math.min(info.cap, bal - reqFloor - 0.01));
  } else if (P.type === 'select-flex') {
    info.cap = P.cap;
    checks.days = L.qualDays >= P.winningDays;
    checks.cycleProfit = k + 1 < P.positiveCycleProfitFromPayout || L.cycleProfit > 0;
    maxAmount = floorCents(Math.min(P.shareOfTotalProfit * (bal - L.startBal), P.cap));
  } else if (P.type === 'select-daily') {
    info.cap = P.cap;
    checks.cycleProfit = k + 1 < P.positiveCycleProfitFromPayout || L.cycleProfit > 0;
    maxAmount = floorCents(Math.min(P.multipleOfCycleProfit * L.cycleProfit, P.cap, bal - P.bufferBalance));
  } else if (P.type === 'lightning') {
    const share = at(plan.consistency, k);
    info.cap = at(P.caps, k);
    info.goal = at(P.profitGoals, k);
    info.consistencyShare = share;
    checks.goal = L.cycleProfit >= info.goal;
    checks.consistency = L.cycleProfit > 0 && L.cycleMaxDay <= share * L.cycleProfit + EPS;
    checks.count = P.capsRepeatLast !== false || k < P.caps.length;
    maxAmount = floorCents(Math.min(info.cap, bal - reqFloor - 0.01));
  } else {
    throw new Error(`unknown payout type ${P.type}`);
  }
  checks.minPayout = maxAmount >= P.minPayout;
  const amount = L.payoutPolicy === 'min' ? P.minPayout : maxAmount;
  checks.aboveFloor = cents(bal - amount) > reqFloor;
  return {
    eligible: L.status === ACTIVE && Object.values(checks).every(Boolean),
    amount: Math.max(0, amount),
    maxAmount: Math.max(0, maxAmount),
    n: k + 1,
    type: P.type,
    balance: bal,
    floor: L.floor,
    requestFloor: reqFloor,
    qualDays: L.qualDays,
    cycleProfit: L.cycleProfit,
    cycleMaxDay: L.cycleMaxDay,
    ...info,
    checks,
  };
}

/**
 * Cheap, allocation-free necessary conditions of payoutCheck(L).eligible: false means no payout is
 * possible now. endDay runs it at every session close so the full payoutCheck runs only when one may be.
 * Each test is one of payoutCheck's checks, or (select-daily balance) looser than its minPayout check.
 */
function payoutPossible(L) {
  const P = L.plan.payout;
  if (P.type === 'growth') return L.qualDays >= P.minQualifyingDays && balance(L) >= P.minBalance;
  if (P.type === 'select-flex') return L.qualDays >= P.winningDays;
  if (P.type === 'select-daily') {
    const positive = L.payouts + 1 < P.positiveCycleProfitFromPayout || L.cycleProfit > 0;
    return positive && balance(L) - P.bufferBalance >= P.minPayout - 0.01;
  }
  if (P.type === 'lightning') return L.cycleProfit >= at(P.profitGoals, L.payouts);
  return true;
}

function qualifies(P, dayPnl) {
  if (P.type === 'growth') return dayPnl > P.qualifyingDayProfitAbove;
  if (P.type === 'select-flex') return dayPnl >= P.winningDayProfitAtLeast;
  return false;
}

/** Request a payout of `amount` now: lock (lockOnPayoutRequest), pay, and reset the payout cycle. */
export function requestPayout(L, amount) {
  const P = L.plan.payout;
  const before = balance(L);
  if (L.lockOnPayoutRequest) lock(L, 'payout');
  L.realized = cents(L.realized - amount);
  L.payouts++;
  L.requested = cents(L.requested + amount);
  const toTrader = cents(amount * L.split);
  L.received = cents(L.received + toTrader);
  L.payoutHistory.push({
    n: L.payouts,
    day: L.dayKey,
    session: L.sessions,
    amount,
    toTrader,
    balanceBefore: before,
    balanceAfter: balance(L),
    floor: L.floor,
  });
  if (P.type !== 'growth' || P.dayCountResetsAfterPayout !== false) L.qualDays = 0;
  L.cycleProfit = 0;
  L.cycleMaxDay = 0;
  L.dayStartRealized = L.realized;
}

/**
 * End a session (the 17:00 ET close): floor update and lock, DLL raise, Select scaling, payout-cycle
 * bookkeeping, then one payout request when eligible. Returns the amount requested (0 if none).
 */
export function endDay(L) {
  if (L.status !== ACTIVE) return 0;
  const plan = L.plan;
  const dayPnl = sessionPnl(L);
  const bal = balance(L);
  L.sessions++;
  L.lastDayPnl = dayPnl;
  if (L.dayHalted) L.dllDays++;
  if (!L.locked) {
    const f = cents(bal - L.drawdown);
    if (f > L.floor) L.floor = f;
    if (bal >= L.lockTrigger) lock(L, 'eod');
  }
  if (plan.dllRaise && !L.dllRaised && bal >= plan.dllRaise.atBalance) {
    L.dllRaised = true;
    L.dll = plan.dllRaise.to; // null: the DLL is removed (legacy Growth)
  }
  const profit = cents(bal - L.startBal);
  if (profit > L.maxEodProfit) L.maxEodProfit = profit;
  L.capMini = capMiniFor(plan, L.maxEodProfit);
  L.cycleProfit = cents(L.cycleProfit + dayPnl);
  if (dayPnl > L.cycleMaxDay) L.cycleMaxDay = dayPnl;
  if (qualifies(plan.payout, dayPnl)) L.qualDays++;
  L.dayStartRealized = L.realized; // the session is closed
  return requestIfEligible(L);
}

/**
 * At a session close: request the payout (payout policy amount) when the account is eligible. Returns the
 * amount requested (0 if none). endDay ends with it; a start state calls it once before the first session.
 */
export function requestIfEligible(L) {
  if (L.status !== ACTIVE || !payoutPossible(L)) return 0;
  const c = payoutCheck(L);
  if (!c.eligible) return 0;
  requestPayout(L, c.amount);
  return c.amount;
}

/**
 * Why no payout can be requested now: one { check, message } per failed payoutCheck check, in check
 * order (empty when eligible). Messages give the amounts still missing, from the plan's rules.
 */
export function payoutBlockers(L, c = payoutCheck(L)) {
  const P = L.plan.payout;
  const cp = L.cycleProfit;
  const M = L.cycleMaxDay;
  const consistency = () => {
    const share = c.consistencyShare;
    const needProfit = ceilCents(M / share);
    if (!(cp > 0)) {
      const reach = M > 0 ? ` and reach ${money(needProfit)} for the largest day ${money(M)} to be within ${pctText(share)}` : '';
      return `profit since the last payout is ${money(cp)}: the ${pctText(share)} consistency rule needs it positive${reach}`;
    }
    return (
      `largest day ${money(M)} is ${pctText(M / cp, 1)} of the ${money(cp)} profit since the last payout (limit ${pctText(share)}): ` +
      `${money(cents(needProfit - cp))} more profit without a larger day`
    );
  };
  const text = {
    days: () => {
      const growth = P.type === 'growth';
      const need = (growth ? P.minQualifyingDays : P.winningDays) - L.qualDays;
      const kind = growth ? `qualifying day${need === 1 ? '' : 's'} (profit above ${money(P.qualifyingDayProfitAbove)})` : `winning day${need === 1 ? '' : 's'} (profit of at least ${money(P.winningDayProfitAtLeast)})`;
      return `${need} more ${kind}: ${L.qualDays} of ${need + L.qualDays} since the last payout`;
    },
    consistency,
    balance: () => `balance ${money(c.balance)} is below the ${money(P.minBalance)} minimum (${money(cents(P.minBalance - c.balance))} short)`,
    count: () => `the plan has no payout ${c.n} (its cap list ends and does not repeat)`,
    cycleProfit: () => `profit since the last payout ${money(cp)} must be positive (from payout ${P.positiveCycleProfitFromPayout} on)`,
    goal: () => `profit since the last payout ${money(cp)} is below the ${money(c.goal)} goal for payout ${c.n} (${money(cents(c.goal - cp))} short)`,
    minPayout: () => `the largest amount allowed now, ${money(c.maxAmount)}, is below the ${money(P.minPayout)} minimum`,
    aboveFloor: () => `a ${money(c.amount)} request would leave ${money(cents(c.balance - c.amount))}, not above the ${money(c.requestFloor)} floor`,
  };
  const out = [];
  if (L.status !== ACTIVE) out.push({ check: 'status', message: `the account is ${L.status}` });
  for (const [check, ok] of Object.entries(c.checks)) {
    if (!ok) out.push({ check, message: text[check] ? text[check]() : `${check} check fails` });
  }
  return out;
}

// ---------------------------------------------------------------------------------------------- simulation

function fundedOptions(rules, planKey, o = {}) {
  const plan = resolvePlan(rules, planKey, o);
  const unit = normalizeUnit(o.unit ?? 'mini');
  return {
    plan,
    contracts: o.contracts ?? 1,
    runs: o.runs ?? 20000,
    horizonDays: o.horizonDays ?? 120,
    seed: (o.seed ?? 1) >>> 0,
    unit,
    cap: planCap(rules, plan, unit),
    ledgerOpts: {
      legacy: plan.legacy,
      boughtBefore20260901: plan.boughtBefore20260901,
      order: normalizeOrder(o.order ?? 'conservative'),
      dllFill: normalizeDllFill(o.dllFill ?? 'extreme'),
      payout: normalizePayoutPolicy(o.payout ?? 'max'),
    },
    // Resolved once here; every ledger of the run starts from it (replay: the first account only).
    startState: o.startState != null ? resolveStartState(rules, plan, o.startState) : null,
  };
}

function assertSize(q) {
  if (!(Number.isInteger(q) && q >= 1)) throw new Error(`contracts must be a positive integer, got ${q}`);
}

/**
 * Simulate `runs` fresh funded accounts of a plan for up to `horizonDays` trading sessions each, at
 * `contracts` contracts (or, with a risk-scaled empirical source, each trade's as-traded size times
 * `contracts`), capped every trade at the session's plan cap. Sources are the planner's trade sources
 * (sim.mjs: empirical bootstrap with 'contracts' or 'risk' scaling, or parametric). Path r of a seed sees
 * the same sessions at every size. A run stops at a breach; payouts never end a run.
 * opts.startState: every account starts from that state instead of a fresh one; payouts and amounts then
 * count from the start. An eligible state pays at once, before session 1, the same payout in every run
 * (payoutNow: { n, amount, toTrader }, else null): it is in the payout counts and amounts, but pPayout,
 * pBreachBeforeFirstPayout and the days to the first payout count only the payouts after it.
 */
export function simulateFunded(rules, planKey, source, opts = {}) {
  const o = fundedOptions(rules, planKey, opts);
  assertSize(o.contracts);
  const ledgerOpts = o.startState ? { ...o.ledgerOpts, startState: o.startState } : o.ledgerOpts;
  const risk = source.scaling === 'risk';
  const qty = source.qty;
  const cost = source.extraCost ?? 0;
  const R = o.runs;
  const payouts = new Float64Array(R);
  const requested = new Float64Array(R);
  const received = new Float64Array(R);
  const firstPayoutDays = [];
  let withPayout = 0;
  let breachedBeforeFirst = 0;
  let breachedAny = 0;
  let dllDays = 0;
  let sessionsUsed = 0;
  let trades = 0;
  let capped = 0;
  let endBalance = 0;
  let payoutNow = null;
  for (let r = 0; r < R; r++) {
    const rng = mulberry32(pathSeed(o.seed, FUNDED_STREAM, r));
    const L = makeFundedLedger(rules, o.plan.key, ledgerOpts);
    let firstPayoutDay = -1; // first payout after the payout now, if any
    let paidNow = 0;
    if (o.startState && requestIfEligible(L) > 0) {
      paidNow = 1;
      const p = L.payoutHistory[0];
      payoutNow ??= { n: p.n, amount: p.amount, toTrader: p.toTrader };
    }
    for (let d = 1; d <= o.horizonDays; d++) {
      startDay(L, d);
      const capU = contractCap(L, o.unit);
      const q = o.contracts < capU ? o.contracts : capU;
      const n = source.sampleDay(rng);
      const buf = source.buf;
      const off = source.off;
      for (let i = 0, k = off; i < n; i++, k += 3) {
        if (L.dayHalted) break;
        let c = q;
        if (risk) {
          const want = o.contracts * qty[k / 3];
          c = want > capU ? capU : want;
          if (c < want) capped++;
        } else if (q < o.contracts) capped++;
        stepTrade(L, c * buf[k + 1], c * buf[k + 2], c * buf[k] - c * cost, c * cost);
        trades++;
        if (L.status !== ACTIVE) break;
      }
      sessionsUsed++;
      if (L.status !== ACTIVE) break;
      const p = endDay(L);
      if (p > 0 && firstPayoutDay < 0) firstPayoutDay = d;
    }
    const made = payoutsMade(L);
    const later = made - paidNow;
    dllDays += L.dllDays;
    payouts[r] = made;
    requested[r] = L.requested;
    received[r] = L.received;
    endBalance += finalBalance(L);
    if (later > 0) {
      withPayout++;
      firstPayoutDays.push(firstPayoutDay);
    }
    if (L.status === BREACHED) {
      breachedAny++;
      if (later === 0) breachedBeforeFirst++;
    }
  }
  const sp = sortedCopy(payouts);
  const sq = sortedCopy(requested);
  const sr = sortedCopy(received);
  const sd = sortedCopy(firstPayoutDays);
  return {
    plan: o.plan.key,
    contracts: o.contracts,
    scaling: risk ? 'risk' : 'contracts',
    unit: o.unit,
    cap: o.cap,
    runs: R,
    horizonDays: o.horizonDays,
    pPayout: withPayout / R,
    meanPayouts: mean(payouts),
    medianPayouts: quantileSorted(sp, 0.5),
    meanRequested: mean(requested),
    medianRequested: quantileSorted(sq, 0.5),
    meanReceived: mean(received),
    medianReceived: quantileSorted(sr, 0.5),
    p90Received: quantileSorted(sr, 0.9),
    pBreachBeforeFirstPayout: breachedBeforeFirst / R,
    pBreach: breachedAny / R,
    medianDaysToFirstPayout: quantileSorted(sd, 0.5),
    p90DaysToFirstPayout: quantileSorted(sd, 0.9),
    dllDaysPerRun: dllDays / R,
    tradingDaysPerRun: sessionsUsed / R,
    meanEndBalance: endBalance / R, // a breached account counts at its net liquidation at the breach
    cappedTradeShare: trades > 0 ? capped / trades : 0,
    tradesSimulated: trades,
    ...(o.startState ? { fromStartState: true, payoutsBefore: o.startState.payoutsTaken, payoutNow } : {}),
  };
}

/** Default sweep for a plan: contracts 1..cap, or the risk multipliers up to the one that caps every trade. */
export function fundedSizes(rules, planKey, source, opts = {}) {
  const plan = resolvePlan(rules, planKey, opts);
  return defaultSizes(source, planCap(rules, plan, opts.unit ?? 'mini'));
}

/**
 * Deterministic replay of the actual CSV trades (chronological) through one funded account of the plan,
 * session by session from the first to the last traded day (sessionCalendar: Monday..Friday plus any day
 * with trades; sessions without trades still close a day). A breach ends the account; later trades of
 * that session belong to no account, and a fresh account starts at the next session. opts: { contracts,
 * scaling: 'contracts'|'risk', extraCost, unit, order, dllFill, payout, legacy, boughtBefore20260901,
 * startState }. With startState the first account starts from it (an eligible state pays at once:
 * firstPayoutDay 'start', session 0) and its payouts count from the start; later accounts start fresh.
 */
export function replayFunded(rules, planKey, trades, opts = {}) {
  const o = fundedOptions(rules, planKey, opts);
  assertSize(o.contracts);
  const risk = (opts.scaling ?? 'contracts') === 'risk';
  const cost = opts.extraCost ?? 0;
  const days = groupTradesByDay(trades);
  const byKey = new Map(days.map((d) => [d.dayKey, d.trades]));
  const sessions = sessionCalendar(days);
  const accounts = [];
  let L = null;
  let cur = null;
  let skipped = 0;
  let capped = 0;
  let fed = 0;
  let pendingStart = o.startState;
  const finish = (status) => {
    accounts.push({
      ...cur,
      status,
      trades: L.trades,
      dllSkippedTrades: L.dllSkippedTrades,
      payouts: payoutsMade(L),
      requested: L.requested,
      received: L.received,
      dllDays: L.dllDays,
      balance: finalBalance(L), // a breached account: net liquidation at the breach
      floor: L.floor,
      locked: L.locked,
      breachDay: L.breachDay ?? null,
      breachNetLiq: L.breachNetLiq ?? null,
      reason: L.reason,
      payoutHistory: L.payoutHistory,
    });
    L = null;
    cur = null;
  };
  for (const key of sessions) {
    if (!L) {
      L = makeFundedLedger(rules, o.plan.key, { ...o.ledgerOpts, firstDay: key, startState: pendingStart });
      cur = { startDay: key, endDay: key, sessions: 0, firstPayoutDay: null, firstPayoutSession: null };
      if (pendingStart) {
        cur.fromStartState = true;
        cur.payoutsBefore = L.payoutsBefore;
        pendingStart = null;
        if (requestIfEligible(L) > 0) {
          cur.firstPayoutDay = 'start';
          cur.firstPayoutSession = 0;
        }
      }
    }
    startDay(L, key);
    cur.sessions++;
    cur.endDay = key;
    const capU = contractCap(L, o.unit);
    for (const t of byKey.get(key) ?? []) {
      if (L.status !== ACTIVE) {
        skipped++; // same session as this account's breach
        continue;
      }
      const want = risk ? o.contracts * (t.contracts >= 1 ? t.contracts : 1) : o.contracts;
      const c = want > capU ? capU : want;
      if (!L.dayHalted) {
        fed++;
        if (c < want) capped++;
      }
      stepTrade(L, c * t.mfePer, c * t.maePer, c * t.pnlPer - c * cost, c * cost);
    }
    if (L.status !== ACTIVE) {
      finish(L.status);
      continue;
    }
    const p = endDay(L);
    if (p > 0 && cur.firstPayoutDay == null) {
      cur.firstPayoutDay = key;
      cur.firstPayoutSession = cur.sessions;
    }
  }
  if (L) finish('OPEN');
  const sum = (f) => cents(accounts.reduce((s, a) => s + f(a), 0));
  const firstWithPayout = accounts.find((a) => a.firstPayoutDay != null);
  const last = accounts[accounts.length - 1] ?? null;
  return {
    plan: o.plan.key,
    contracts: o.contracts,
    scaling: risk ? 'risk' : 'contracts',
    unit: o.unit,
    firstDay: sessions[0] ?? null,
    lastDay: sessions[sessions.length - 1] ?? null,
    sessions: sessions.length,
    accounts,
    total: accounts.length,
    breached: accounts.filter((a) => a.status === BREACHED).length,
    open: accounts.filter((a) => a.status === 'OPEN').length,
    payouts: accounts.reduce((s, a) => s + a.payouts, 0),
    requested: sum((a) => a.requested),
    received: sum((a) => a.received),
    dllDays: accounts.reduce((s, a) => s + a.dllDays, 0),
    dllSkippedTrades: accounts.reduce((s, a) => s + a.dllSkippedTrades, 0),
    skippedTrades: skipped,
    cappedTradeShare: fed > 0 ? capped / fed : 0,
    firstPayoutDay: firstWithPayout?.firstPayoutDay ?? null,
    firstPayoutSession: firstWithPayout?.firstPayoutSession ?? null,
    // Payouts requested at the start state itself (0 or 1), included in payouts / requested / received.
    ...(o.startState ? { fromStartState: true, startPayouts: accounts.filter((a) => a.firstPayoutDay === 'start').length } : {}),
    last: last && {
      status: last.status,
      balance: last.balance,
      floor: last.floor,
      locked: last.locked,
      endDay: last.endDay,
      breachDay: last.breachDay,
      breachNetLiq: last.breachNetLiq,
    },
  };
}

// ---------------------------------------------------------------------------------------------- flat time

/**
 * Trades that break "flat by session.flatByEt" (session.earlyCloseFlatByEt on the early-close days):
 * exit (or entry) after the flat time and before the next session opens, or a position held across the
 * session break. New York wall clock. The planner has no exchange calendar: only the days listed in
 * earlyCloseDays ('YYYY-MM-DD' session days) are checked against the early-close flat time.
 */
export function flatTimeViolations(rules, trades, tz = NY, earlyCloseDays = []) {
  const flat = parseHm(rules.session.flatByEt);
  const earlyFlat = parseHm(rules.session.earlyCloseFlatByEt);
  const early = new Set(earlyCloseDays);
  const open = parseHm(rules.session.startEt);
  const roll = sessionRollHour(rules);
  const late = (d) => {
    if (!(d instanceof Date) || Number.isNaN(d.getTime())) return false;
    const w = wallClock(d, tz);
    const m = w.h * 60 + w.mi + (w.s > 0 ? 1 / 60 : 0);
    const f = early.size > 0 && early.has(dayKeyOf(d, tz, roll)) ? earlyFlat : flat;
    return m > f && m < open;
  };
  return trades.filter((t) => {
    if (late(t.exitTime) || late(t.entryTime)) return true;
    if (t.entryTime instanceof Date && t.exitTime instanceof Date) {
      return dayKeyOf(t.entryTime, tz, roll) !== dayKeyOf(t.exitTime, tz, roll);
    }
    return false;
  });
}

// ---------------------------------------------------------------------------------------------- microscalping

/**
 * fundedRules.microscalping as numbers: { minShare, minHoldSeconds } ("more than minShare of trades and of
 * profit must come from trades held longer than minHoldSeconds, or payouts are blocked"), or null when the
 * rules file has no such rule. validateTradeifyRules rejects a rule text it cannot read.
 */
export function microscalpingRule(rules) {
  const text = rules.fundedRules?.microscalping;
  if (text == null) return null;
  const m = MICROSCALPING_RE.exec(String(text));
  return m ? { minShare: +m[1] / 100, minHoldSeconds: +m[2] } : null;
}

/**
 * The microscalping rule on the CSV trades (hold = exitTime - entryTime; trades without both times are
 * left out). A hold of minHoldSeconds or less is short; profit is gross profit (winning trades), per
 * contract with scaling 'contracts' and as traded with 'risk', as the replay sizes them. A CSV with
 * minute timestamps shows a trade opened and closed within one minute as a 0-second hold (sameTimestamp).
 * passes: more than minShare of the trades, and of the gross profit when there is any, come from long
 * holds. The ledger does not apply the rule: payouts are simulated as if it were met. null without a rule.
 */
export function microscalpingCheck(rules, trades, { scaling = 'contracts' } = {}) {
  const rule = microscalpingRule(rules);
  if (!rule) return null;
  let known = 0;
  let long = 0;
  let sameTimestamp = 0;
  let gross = 0;
  let longGross = 0;
  for (const t of trades) {
    const hold = t.entryTime instanceof Date && t.exitTime instanceof Date ? (t.exitTime - t.entryTime) / 1000 : NaN;
    if (!Number.isFinite(hold)) continue;
    known++;
    if (hold === 0) sameTimestamp++;
    const isLong = hold > rule.minHoldSeconds;
    if (isLong) long++;
    const p = scaling === 'risk' ? t.pnl : t.pnlPer;
    if (p > 0) {
      gross += p;
      if (isLong) longGross += p;
    }
  }
  const longShareOfTrades = known > 0 ? long / known : null;
  const longShareOfProfit = gross > 0 ? longGross / gross : null;
  return {
    ...rule,
    trades: known,
    unknownHold: trades.length - known,
    sameTimestamp,
    longShareOfTrades,
    longShareOfProfit,
    passes: known > 0 && longShareOfTrades > rule.minShare && (longShareOfProfit == null || longShareOfProfit > rule.minShare),
  };
}
